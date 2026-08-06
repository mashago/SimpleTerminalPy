"""SimpleTerminalPy — 终端网格数据模型（对应 vt100.h 的数据结构）。"""

from collections import deque

from config import DEFAULT_FG, DEFAULT_BG, SCROLLBACK_LINES, TAB_SPACES

# ── Glyph 属性位（对应 glyph_attribute 枚举）────────────
ATTR_NULL      = 0
ATTR_REVERSE   = 1
ATTR_UNDERLINE = 2
ATTR_BOLD      = 4
ATTR_GFX       = 8
ATTR_ITALIC    = 16
ATTR_BLINK     = 32

# ── 光标状态 ────────────────────────────────────────────
CURSOR_DEFAULT  = 0
CURSOR_HIDE     = 1
CURSOR_WRAPNEXT = 2

# ── Glyph 状态 ──────────────────────────────────────────
GLYPH_SET      = 1
GLYPH_DIRTY    = 2
GLYPH_WIDE_TAIL = 4   # 双列宽字符的后半列（不渲染）

# ── 终端模式位 ───────────────────────────────────────────
MODE_WRAP       = 1
MODE_INSERT     = 2
MODE_APPKEYPAD  = 4
MODE_ALTSCREEN  = 8
MODE_CRLF       = 16
MODE_MOUSEBTN   = 32
MODE_MOUSEMOTION = 64
MODE_MOUSE      = 32 | 64
MODE_REVERSE    = 128
MODE_KBDLOCK    = 256
MODE_BRACKETPASTE = 512   # DEC 2004 括号粘贴（粘贴时用 200~/201~ 包裹）

# ── Escape 状态位 ───────────────────────────────────────
ESC_START       = 1
ESC_CSI         = 2
ESC_STR         = 4
ESC_ALTCHARSET  = 8
ESC_STR_END     = 16
ESC_TEST        = 32

# ── UTF-8 常量 ──────────────────────────────────────────
UTF_SIZ     = 4
ESC_BUF_SIZ = 256
ESC_ARG_SIZ = 16
STR_BUF_SIZ = 256
STR_ARG_SIZ = 16

# ── 辅助宏 ──────────────────────────────────────────────
def limit(val, lo, hi):
    if val < lo: return lo
    if val > hi: return hi
    return val


def between(val, lo, hi):
    return lo <= val <= hi


def is_set(flags, bit):
    return bool(flags & bit)


# ── Glyph ───────────────────────────────────────────────
class Glyph:
    """终端中的一个字符格子。用 __slots__ 节省内存。"""
    __slots__ = ('c', 'mode', 'fg', 'bg', 'state')

    def __init__(self):
        self.c = ' '          # UTF-8 字符
        self.mode = 0        # ATTR_* 位组合
        self.fg = DEFAULT_FG  # 前景色：调色板索引 int 或真彩色 (R,G,B) 元组
        self.bg = DEFAULT_BG  # 背景色：同上
        self.state = 0        # GLYPH_SET / GLYPH_DIRTY

    def copy_from(self, other: 'Glyph'):
        self.c = other.c
        self.mode = other.mode
        self.fg = other.fg
        self.bg = other.bg
        self.state = other.state

    def clear(self):
        self.c = ' '
        self.mode = 0
        self.fg = DEFAULT_FG
        self.bg = DEFAULT_BG
        self.state = 0


# ── Cursor ──────────────────────────────────────────────
class Cursor:
    __slots__ = ('attr', 'x', 'y', 'state')

    def __init__(self):
        self.attr = Glyph()
        self.x = 0
        self.y = 0
        self.state = CURSOR_DEFAULT

    def attrcmp(self, other: 'Glyph') -> bool:
        """只比较文本属性（用于合并相邻相同格）——不对应 C 的 ATTRCMP 宏"""
        return (self.attr.mode == other.mode and
                self.attr.fg == other.fg and
                self.attr.bg == other.bg)


# ── CSI Escape Sequence ─────────────────────────────────
class CSIEscape:
    __slots__ = ('buf', 'length', 'priv', 'arg', 'narg', 'mode')

    def __init__(self):
        self.buf: list[str] = []
        self.length = 0
        self.priv = False
        self.arg: list[int] = [0] * ESC_ARG_SIZ
        self.narg = 0
        self.mode = '\0'

    def reset(self):
        self.buf.clear()
        self.length = 0
        self.priv = False
        for i in range(len(self.arg)):
            self.arg[i] = 0
        self.narg = 0
        self.mode = '\0'


# ── STR Escape Sequence ─────────────────────────────────
class STREscape:
    __slots__ = ('type_', 'buf', 'length', 'args', 'narg')

    def __init__(self):
        self.type_ = '\0'
        self.buf: list[str] = []
        self.length = 0
        self.args: list[str] = [""] * STR_ARG_SIZ
        self.narg = 0

    def reset(self):
        self.type_ = '\0'
        self.buf.clear()
        self.length = 0
        for i in range(len(self.args)):
            self.args[i] = ""
        self.narg = 0


# ── Term ────────────────────────────────────────────────
class Term:
    """终端核心状态（对应 C 的 Term 结构体）。"""

    def __init__(self, col: int, row: int):
        self.col = col
        self.row = row

        # 屏幕网格
        self.lines: list[list[Glyph]] = []       # 主屏幕 [row][col]
        self.alt_lines: list[list[Glyph]] = []    # alt 屏幕
        self.dirty: list[bool] = []               # 行脏标记

        # 光标
        self.cursor = Cursor()
        self.top = 0                               # 滚动区域上界
        self.bot = row - 1                         # 滚动区域下界
        self.mode = MODE_WRAP                      # 模式位
        self.esc = 0                               # escape 状态位
        self.tabs: list[bool] = []                 # 制表位

        # scrollback
        self.scrollback: deque[list[Glyph]] = deque(maxlen=SCROLLBACK_LINES)
        self.scroll_offset = 0

        # 上次打印字符（用于 REP 命令）
        self.last_char = ' '

        self._alloc_grids()
        self._init_tabs()
        self.scroll_offset = 0

    def _alloc_grids(self):
        """分配屏幕网格和脏标记数组。"""
        self.lines = [[Glyph() for _ in range(self.col)] for _ in range(self.row)]
        self.alt_lines = [[Glyph() for _ in range(self.col)] for _ in range(self.row)]
        self.dirty = [True] * self.row   # 初始化时全脏，触发首帧绘制

    def _init_tabs(self):
        """初始化制表位——每 TAB_SPACES 列一个。"""
        self.tabs = [False] * self.col
        for i in range(TAB_SPACES, self.col, TAB_SPACES):
            self.tabs[i] = True

    # ── 脏标记 ─────────────────────────────────────────

    def set_dirt(self, top: int, bot: int):
        top = limit(top, 0, self.row - 1)
        bot = limit(bot, 0, self.row - 1)
        for i in range(top, bot + 1):
            self.dirty[i] = True

    def full_dirt(self):
        self.set_dirt(0, self.row - 1)

    # ── scrollback ──────────────────────────────────────

    def scrollback_add_line(self, line: list[Glyph]):
        """保存一行到 scrollback。deque 自动管理容量。"""
        copy = [Glyph() for _ in range(self.col)]
        for i in range(self.col):
            copy[i].copy_from(line[i])
        self.scrollback.append(copy)

    def scroll_view_up(self, n: int):
        if not self.scrollback:
            return
        self.scroll_offset = min(self.scroll_offset + n, len(self.scrollback))
        self.full_dirt()

    def scroll_view_down(self, n: int):
        if self.scroll_offset == 0:
            return
        self.scroll_offset = max(self.scroll_offset - n, 0)
        self.full_dirt()

    def scroll_view_reset(self):
        if self.scroll_offset == 0:
            return
        self.scroll_offset = 0
        self.full_dirt()
