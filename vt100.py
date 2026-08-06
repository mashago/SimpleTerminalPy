"""SimpleTerminalPy — VT100 转义序列解析器（对应 vt100.c）。"""

from terminal import (
    Term, Glyph, Cursor, CSIEscape, STREscape,
    ATTR_REVERSE, ATTR_UNDERLINE, ATTR_BOLD,
    ATTR_GFX, ATTR_ITALIC, ATTR_BLINK,
    CURSOR_HIDE, CURSOR_WRAPNEXT,
    GLYPH_SET, GLYPH_WIDE_TAIL,
    MODE_WRAP, MODE_INSERT, MODE_APPKEYPAD, MODE_ALTSCREEN,
    MODE_CRLF, MODE_MOUSEBTN, MODE_MOUSEMOTION,
    MODE_REVERSE, MODE_KBDLOCK, MODE_BRACKETPASTE,
    ESC_START, ESC_CSI, ESC_STR, ESC_ALTCHARSET, ESC_STR_END, ESC_TEST,
    UTF_SIZ, ESC_BUF_SIZ, ESC_ARG_SIZ, STR_BUF_SIZ,
    limit, between, is_set,
)
from wcwidth import char_width
from config import DEFAULT_FG, DEFAULT_BG, TAB_SPACES

# ── VT102 标识 ──────────────────────────────────────────
VT102ID = "\033[?6c"


# ── VT100 图形字符映射（完整 62 字符表，来自 C 版 rxvt 表）──
# DEC Special Graphics (ESC(0)：字符 'A'-'~' 的映射
_VT100_GFX = {
    'A': '↑', 'B': '↓', 'C': '→', 'D': '←', 'E': '█', 'F': '▚',
    'G': '☃',
    # H-O: 保留
    '`': '◆', 'a': '▒', 'b': '␉', 'c': '␌', 'd': '␍', 'e': '␊',
    'f': '°', 'g': '±', 'h': '␤', 'i': '␋',
    'j': '┘', 'k': '┐', 'l': '┌', 'm': '└', 'n': '┼',
    'o': '⎺', 'p': '⎻', 'q': '─', 'r': '⎼', 's': '⎽',
    't': '├', 'u': '┤', 'v': '┴', 'w': '┬', 'x': '│',
    'y': '≤', 'z': '≥', '{': 'π', '|': '≠', '}': '£', '~': '·',
}


class Vt100:
    """VT100 终端状态机。"""

    def __init__(self, term: Term):
        self.term = term
        self.csiescseq = CSIEscape()
        self.strescseq = STREscape()

        # 光标保存（两个 slot：主屏和 alt 屏）
        self._saved_cursors: list[Cursor | None] = [None, None]

    # ══════════════════════════════════════════════════════
    # t_putc — 主入口
    # ══════════════════════════════════════════════════════

    def t_putc(self, ch: str):
        """处理从 PTY 收到的单个 UTF-8 字符。"""
        if not ch:
            return
        ascii_code = ord(ch[0])

        # ── STR 序列中 ──
        if self.term.esc & ESC_STR:
            return self._str_collect(ch, ascii_code)

        # ── 控制字符 ──
        if ascii_code < 0x20 or ascii_code == 0x7F:
            return self._handle_control(ch, ascii_code)

        # ── ESC 序列中 ──
        if self.term.esc & ESC_START:
            return self._handle_escape(ch, ascii_code)

        # ── 正常字符 ──
        # 如果设置了 GFX 模式，控制字符中的可显示图形也要渲染
        control = ascii_code < 0x20 or ascii_code == 0x7F
        if control and not (self.term.cursor.attr.mode & ATTR_GFX):
            return

        # 确定字符宽度（CJK 等宽字符占 2 列）
        w = char_width(ch)

        # WRAP 模式：上一字符到行尾后自动换行
        if is_set(self.term.mode, MODE_WRAP) and \
           is_set(self.term.cursor.state, CURSOR_WRAPNEXT):
            self.t_newline(True)

        # 宽字符在行尾的处理：如果只剩 1 列，先换行
        if w == 2 and self.term.cursor.x == self.term.col - 1:
            self.t_newline(True)

        self._t_set_char(ch, self.term.cursor.attr,
                         self.term.cursor.x, self.term.cursor.y)

        # 宽字符：标记下一格为 WIDE_TAIL
        if w == 2 and self.term.cursor.x + 1 < self.term.col:
            tail = self.term.lines[self.term.cursor.y][self.term.cursor.x + 1]
            tail.c = ' '
            tail.mode = self.term.cursor.attr.mode
            tail.fg = self.term.cursor.attr.fg
            tail.bg = self.term.cursor.attr.bg
            tail.state |= GLYPH_WIDE_TAIL

        # 保存最后字符（用于 REP 命令）
        self.term.last_char = ch

        new_x = self.term.cursor.x + w
        if new_x < self.term.col:
            self.t_move_to(new_x, self.term.cursor.y)
        else:
            self.term.cursor.state |= CURSOR_WRAPNEXT

    # ══════════════════════════════════════════════════════
    # STR 序列
    # ══════════════════════════════════════════════════════

    def _str_collect(self, ch: str, code: int):
        if ch == '\033':
            self.term.esc = ESC_START | ESC_STR_END
        elif ch == '\a':  # BEL 兼容
            self.term.esc = 0
        else:
            if self.strescseq.length + 1 >= STR_BUF_SIZ:
                self.term.esc = 0
                return
            self.strescseq.buf.append(ch)
            self.strescseq.length += 1

    # ══════════════════════════════════════════════════════
    # 控制字符处理
    # ══════════════════════════════════════════════════════

    def _handle_control(self, ch: str, code: int):
        if code == 0x09:            # HT
            self.t_put_tab(True)
        elif code == 0x08:          # BS
            self.t_move_to(self.term.cursor.x - 1, self.term.cursor.y)
        elif code == 0x0D:          # CR
            self.t_move_to(0, self.term.cursor.y)
        elif code in (0x0A, 0x0B, 0x0C):  # LF, VT, FF
            self.t_newline(is_set(self.term.mode, MODE_CRLF))
        elif code == 0x07:          # BEL
            pass                    # 忽略
        elif code == 0x1B:          # ESC
            self.csiescseq.reset()
            self.term.esc = ESC_START
        elif code == 0x0E:          # SO
            self.term.cursor.attr.mode |= ATTR_GFX
        elif code == 0x0F:          # SI
            self.term.cursor.attr.mode &= ~ATTR_GFX
        elif code in (0x1A, 0x18):  # SUB, CAN
            self.csiescseq.reset()
        elif code in (0x05, 0x00, 0x11, 0x13, 0x7F):
            pass                    # ENQ, NUL, XON, XOFF, DEL — 忽略

    # ══════════════════════════════════════════════════════
    # ESC 序列处理
    # ══════════════════════════════════════════════════════

    def _handle_escape(self, ch: str, code: int):
        if self.term.esc & ESC_CSI:
            return self._csi_collect(ch, code)

        if self.term.esc & ESC_STR_END:
            self.term.esc = 0
            return

        if self.term.esc & ESC_ALTCHARSET:
            return self._handle_altcharset(code)

        if self.term.esc & ESC_TEST:
            return self._handle_test(code)

        # ESC_START only
        if ch == '[':
            self.term.esc |= ESC_CSI
        elif ch == '#':
            self.term.esc |= ESC_TEST
        elif ch in ('P', '_', '^', ']', 'k'):
            self.strescseq.reset()
            self.strescseq.type_ = ch
            self.term.esc |= ESC_STR
        elif ch == '(':
            self.term.esc |= ESC_ALTCHARSET
        elif ch in (')', '*', '+'):
            # G1/G2/G3 字符集 — 忽略
            self.term.esc = 0
        elif ch == 'D':             # IND
            if self.term.cursor.y == self.term.bot:
                self.t_scroll_up(self.term.top, 1)
            else:
                self.t_move_to(self.term.cursor.x, self.term.cursor.y + 1)
            self.term.esc = 0
        elif ch == 'E':             # NEL
            self.t_newline(True)
            self.term.esc = 0
        elif ch == 'H':             # HTS
            if 0 <= self.term.cursor.x < self.term.col:
                self.term.tabs[self.term.cursor.x] = True
            self.term.esc = 0
        elif ch == 'M':             # RI
            if self.term.cursor.y == self.term.top:
                self.t_scroll_down(self.term.top, 1)
            else:
                self.t_move_to(self.term.cursor.x, self.term.cursor.y - 1)
            self.term.esc = 0
        elif ch == 'Z':             # DECID
            self.tty_write(VT102ID)
            self.term.esc = 0
        elif ch == 'c':             # RIS
            self.t_reset()
            self.term.esc = 0
        elif ch == '=':             # DECPAM
            self.term.mode |= MODE_APPKEYPAD
            self.term.esc = 0
        elif ch == '>':             # DECPNM
            self.term.mode &= ~MODE_APPKEYPAD
            self.term.esc = 0
        elif ch == '7':             # DECSC
            self.t_cursor(self.CURSOR_SAVE)
            self.term.esc = 0
        elif ch == '8':             # DECRC
            self.t_cursor(self.CURSOR_LOAD)
            self.term.esc = 0
        elif ch == '\\':            # ST
            self.term.esc = 0
        else:
            # 未知 ESC 序列 — 静默忽略
            self.term.esc = 0

    # ══════════════════════════════════════════════════════
    # CSI 收集和解析
    # ══════════════════════════════════════════════════════

    def _csi_collect(self, ch: str, code: int):
        """收集 CSI 序列的字符。"""
        seq = self.csiescseq

        # 防止缓冲区溢出
        if seq.length >= ESC_BUF_SIZ:
            self.term.esc = 0
            return

        seq.buf.append(ch)
        seq.length += 1

        # 判断是否是终止字符（0x40-0x7E 或缓冲区满）
        if between(code, 0x40, 0x7E):
            self.term.esc = 0
            self._csi_parse()
            self._csi_handle()

    def _csi_parse(self):
        """解析 CSI 参数：ESC [ arg1 ; arg2 ... mode 或 ESC [ ? arg ... mode"""
        seq = self.csiescseq
        buf = ''.join(seq.buf)

        # 私有前缀检测（? > !）
        p = 0
        seq.priv = False
        if p < len(buf) and buf[p] in ('?', '>', '!'):
            seq.priv = True
            p += 1

        # 解析参数
        seq.narg = 0
        current_num = 0
        has_digit = False

        while p < len(buf):
            ch = buf[p]
            if ch.isdigit():
                current_num = current_num * 10 + int(ch)
                has_digit = True
            elif ch in (';', ':'):
                if seq.narg < ESC_ARG_SIZ:
                    seq.arg[seq.narg] = current_num
                    seq.narg += 1
                current_num = 0
                has_digit = False
            else:
                # 终止字符 — 保存最后一个参数和模式
                # 与 C 版一致：无参数时默认 arg[0]=0, narg=1
                # （\x1b[m 等价 \x1b[0m = SGR 0 重置；vim 大量使用）
                if seq.narg < ESC_ARG_SIZ:
                    if has_digit or seq.narg > 0 or ch != buf[0]:
                        seq.arg[seq.narg] = current_num
                        seq.narg += 1
                    else:
                        seq.arg[0] = 0
                        seq.narg = 1
                seq.mode = ch
                return
            p += 1

        # 如果没有找到终止字符（不应该发生）
        seq.mode = '\0'

    # ══════════════════════════════════════════════════════
    # CSI 命令分发
    # ══════════════════════════════════════════════════════

    def _csi_handle(self):
        seq = self.csiescseq
        mode = seq.mode
        a0 = seq.arg[0]
        a1 = seq.arg[1]

        # 窗口操作
        if mode == 't':
            return self._csi_window_manip()

        if mode == '@':             # ICH
            n = a0 if a0 else 1
            return self._t_insert_blank(n)
        if mode in ('A', 'e'):     # CUU
            n = a0 if a0 else 1
            return self.t_move_to(self.term.cursor.x,
                                  self.term.cursor.y - n)
        if mode == 'B':            # CUD
            n = a0 if a0 else 1
            return self.t_move_to(self.term.cursor.x,
                                  self.term.cursor.y + n)
        if mode == 'c':            # DA — 不响应
            return
        if mode in ('C', 'a'):     # CUF
            n = a0 if a0 else 1
            return self.t_move_to(self.term.cursor.x + n,
                                  self.term.cursor.y)
        if mode == 'D':            # CUB
            n = a0 if a0 else 1
            return self.t_move_to(self.term.cursor.x - n,
                                  self.term.cursor.y)
        if mode == 'E':            # CNL
            n = a0 if a0 else 1
            return self.t_move_to(0, self.term.cursor.y + n)
        if mode == 'F':            # CPL
            n = a0 if a0 else 1
            return self.t_move_to(0, self.term.cursor.y - n)
        if mode == 'g':            # TBC
            if a0 == 0:
                if 0 <= self.term.cursor.x < self.term.col:
                    self.term.tabs[self.term.cursor.x] = False
            elif a0 == 3:
                for i in range(self.term.col):
                    self.term.tabs[i] = False
            return
        if mode in ('G', '`'):     # CHA / HPA
            n = a0 if a0 else 1
            return self.t_move_to(n - 1, self.term.cursor.y)
        if mode in ('H', 'f'):     # CUP / HVP
            r = a0 if a0 else 1
            c = a1 if a1 else 1
            return self.t_move_to(c - 1, r - 1)
        if mode == 'I':            # CHT
            n = a0 if a0 else 1
            for _ in range(n):
                self.t_put_tab(True)
            return
        if mode == 'J':            # ED
            return self._csi_erase_display(a0)
        if mode == 'K':            # EL
            return self._csi_erase_line(a0)
        if mode == 'S':            # SU
            n = a0 if a0 else 1
            return self.t_scroll_up(self.term.top, n)
        if mode == 'T':            # SD
            n = a0 if a0 else 1
            return self.t_scroll_down(self.term.top, n)
        if mode == 'L':            # IL
            n = a0 if a0 else 1
            return self._t_insert_blank_line(n)
        if mode == 'l':            # RM
            return self.t_set_mode(seq.priv, False,
                                    seq.arg, seq.narg)
        if mode == 'M':            # DL
            n = a0 if a0 else 1
            return self._t_delete_line(n)
        if mode == 'X':            # ECH
            n = a0 if a0 else 1
            return self._t_clear_region(
                self.term.cursor.x, self.term.cursor.y,
                self.term.cursor.x + n - 1, self.term.cursor.y)
        if mode == 'P':            # DCH
            n = a0 if a0 else 1
            return self._t_delete_char(n)
        if mode == 'Z':            # CBT
            n = a0 if a0 else 1
            for _ in range(n):
                self.t_put_tab(False)
            return
        if mode == 'd':            # VPA
            n = a0 if a0 else 1
            return self.t_move_to(self.term.cursor.x, n - 1)
        if mode == 'h':            # SM
            return self.t_set_mode(seq.priv, True,
                                    seq.arg, seq.narg)
        if mode == 'm':            # SGR
            # 跳过私有 SGR（如 ESC[>4;2m）
            if seq.buf and seq.buf[0] == '>':
                return
            return self.t_set_attr(seq.arg, seq.narg)
        if mode == 'r':            # DECSTBM
            if seq.priv:
                return
            top = a0 - 1 if a0 else 0
            bot = a1 - 1 if a1 else self.term.row - 1
            self._t_set_scroll(top, bot)
            self.t_move_to(0, 0)
            return
        if mode == 's':             # DECSC (ANSI.SYS)
            return self.t_cursor(self.CURSOR_SAVE)
        if mode == 'u':             # DECRC (ANSI.SYS)
            return self.t_cursor(self.CURSOR_LOAD)
        if mode == 'n':             # DSR
            return self._csi_dsr(a0)
        if mode == 'p':             # DECSTR
            if seq.priv:
                self.t_reset()
            return
        if mode == 'b':             # REP
            n = a0 if a0 else 1
            for _ in range(n):
                self.t_putc(self.term.last_char)
            return
        if mode == '%':             # 畸形序列 — 忽略
            return

    # ══════════════════════════════════════════════════════
    # CSI 子命令
    # ══════════════════════════════════════════════════════

    def _csi_erase_display(self, arg: int):
        """ED — 清除屏幕。"""
        if arg == 0:
            # 光标到屏尾
            self._t_clear_region(
                self.term.cursor.x, self.term.cursor.y,
                self.term.col - 1, self.term.cursor.y)
            if self.term.cursor.y < self.term.row - 1:
                self._t_clear_region(
                    0, self.term.cursor.y + 1,
                    self.term.col - 1, self.term.row - 1)
        elif arg == 1:
            # 屏首到光标
            if self.term.cursor.y > 1:
                self._t_clear_region(
                    0, 0,
                    self.term.col - 1, self.term.cursor.y - 1)
            self._t_clear_region(
                0, self.term.cursor.y,
                self.term.cursor.x, self.term.cursor.y)
        elif arg == 2:
            # 整屏
            self._t_clear_region(0, 0,
                                 self.term.col - 1, self.term.row - 1)
        elif arg == 3:
            # 整屏 + 清 scrollback
            self._t_clear_region(0, 0,
                                 self.term.col - 1, self.term.row - 1)
            self.term.scrollback.clear()
            self.term.scroll_offset = 0

    def _csi_erase_line(self, arg: int):
        """EL — 清除行。"""
        if arg == 0:
            self._t_clear_region(
                self.term.cursor.x, self.term.cursor.y,
                self.term.col - 1, self.term.cursor.y)
        elif arg == 1:
            self._t_clear_region(
                0, self.term.cursor.y,
                self.term.cursor.x, self.term.cursor.y)
        elif arg == 2:
            self._t_clear_region(
                0, self.term.cursor.y,
                self.term.col - 1, self.term.cursor.y)

    def _csi_dsr(self, arg: int):
        """DSR — 设备状态报告。只响应 arg=6（光标位置报告）。"""
        if arg == 6:
            self.tty_write(
                f"\033[{self.term.cursor.y + 1};{self.term.cursor.x + 1}R")

    def _csi_window_manip(self):
        """窗口操作（xterm 扩展）。"""
        a0 = self.csiescseq.arg[0]
        if a0 == 18:   # 报告像素大小
            self.tty_write(
                f"\033[4;{self.term.row * 16};{self.term.col * 8}t")
        elif a0 == 19:  # 报告字符大小
            self.tty_write(
                f"\033[8;{self.term.row};{self.term.col}t")

    # ══════════════════════════════════════════════════════
    # ALTCHARSET / TEST
    # ══════════════════════════════════════════════════════

    def _handle_altcharset(self, code: int):
        ch = chr(code)
        if ch == '0':           # 线条字符集
            self.term.cursor.attr.mode |= ATTR_GFX
        elif ch == 'B':         # USASCII
            self.term.cursor.attr.mode &= ~ATTR_GFX
        # A, <, 5, C, K — 忽略
        self.term.esc = 0

    def _handle_test(self, code: int):
        if chr(code) == '8':   # DEC 屏幕对齐测试 — 全屏填 'E'
            for y in range(self.term.row):
                for x in range(self.term.col):
                    self._t_set_char('E', self.term.cursor.attr, x, y)
        self.term.esc = 0

    # ══════════════════════════════════════════════════════
    # 终端操作
    # ══════════════════════════════════════════════════════

    def t_move_to(self, x: int, y: int):
        """移动光标到绝对位置。"""
        x = limit(x, 0, self.term.col - 1)
        y = limit(y, 0, self.term.row - 1)
        self.term.cursor.state &= ~CURSOR_WRAPNEXT
        self.term.cursor.x = x
        self.term.cursor.y = y

    def t_put_tab(self, forward: bool):
        """Tab 前进/后退。"""
        x = self.term.cursor.x
        if forward:
            if x >= self.term.col:
                return
            for nx in range(x + 1, self.term.col):
                if self.term.tabs[nx]:
                    self.t_move_to(nx, self.term.cursor.y)
                    return
        else:
            if x <= 0:
                return
            for nx in range(x - 1, -1, -1):
                if self.term.tabs[nx]:
                    self.t_move_to(nx, self.term.cursor.y)
                    return

    def _t_set_char(self, c: str, attr: Glyph, x: int, y: int):
        """在网格 (x, y) 写入字符。处理 GFX 图形映射。"""
        if attr.mode & ATTR_GFX:
            ch0 = c[0]
            if 'A' <= ch0 <= '~':
                mapped = _VT100_GFX.get(ch0)
                if mapped:
                    c = mapped

        self.term.dirty[y] = True
        g = self.term.lines[y][x]
        g.c = c[:UTF_SIZ]  # 只取前 UTF_SIZ 字节
        g.mode = attr.mode
        g.fg = attr.fg
        g.bg = attr.bg
        # 覆盖宽字符尾格时必须清除 WIDE_TAIL 标记——
        # 否则 renderer 把该格当尾格跳过，显示为空白
        # （tmux 重绘覆盖宽字符区域后文字交替消失的根因）
        g.state = (g.state | GLYPH_SET) & ~GLYPH_WIDE_TAIL

    def _t_clear_region(self, x1: int, y1: int, x2: int, y2: int):
        """清除矩形区域。含 WIDE_TAIL 处理。"""
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1

        x1 = limit(x1, 0, self.term.col - 1)
        x2 = limit(x2, 0, self.term.col - 1)
        y1 = limit(y1, 0, self.term.row - 1)
        y2 = limit(y2, 0, self.term.row - 1)

        for y in range(y1, y2 + 1):
            self.term.dirty[y] = True
            for x in range(x1, x2 + 1):
                # 清除 WIDE_TAIL 的同时清除前一个主字符
                if (self.term.lines[y][x].state & GLYPH_WIDE_TAIL) and x > x1:
                    self.term.lines[y][x - 1].state = 0
                self.term.lines[y][x].state = 0

    def t_scroll_up(self, orig: int, n: int):
        """向上滚 n 行（orig 到 bot 区域）。"""
        n = limit(n, 0, self.term.bot - orig + 1)

        # 保存滚出行到 scrollback（仅滚动区域顶部）
        if orig == self.term.top:
            for i in range(n):
                if orig + i <= self.term.bot:
                    self.term.scrollback_add_line(
                        self.term.lines[orig + i])

        # 清除滚出区域
        self._t_clear_region(0, orig, self.term.col - 1,
                              orig + n - 1)

        # 逐行上移
        for i in range(orig, self.term.bot - n + 1):
            # 交换行
            self.term.lines[i], self.term.lines[i + n] = \
                self.term.lines[i + n], self.term.lines[i]
            self.term.dirty[i] = True
            self.term.dirty[i + n] = True

        # 滚动时重置浏览偏移
        self.term.scroll_view_reset()

    def t_scroll_down(self, orig: int, n: int):
        """向下滚 n 行（orig 到 bot 区域）。"""
        n = limit(n, 0, self.term.bot - orig + 1)

        # 清除上方区域
        self._t_clear_region(0, self.term.bot - n + 1,
                              self.term.col - 1, self.term.bot)

        # 逐行下移
        for i in range(self.term.bot, orig + n - 1, -1):
            self.term.lines[i], self.term.lines[i - n] = \
                self.term.lines[i - n], self.term.lines[i]
            self.term.dirty[i] = True
            self.term.dirty[i - n] = True

    def t_newline(self, first_col: bool):
        """换行。如果光标在底部则滚动，否则下移。"""
        y = self.term.cursor.y
        if y == self.term.bot:
            self.t_scroll_up(self.term.top, 1)
        else:
            y += 1
        self.t_move_to(0 if first_col else self.term.cursor.x, y)

    def _t_insert_blank(self, n: int):
        """插入 n 个空字符（ICH）。"""
        src = self.term.cursor.x + n
        dst = self.term.cursor.x
        size = self.term.col - src
        self.term.dirty[self.term.cursor.y] = True

        if src >= self.term.col:
            self._t_clear_region(
                self.term.cursor.x, self.term.cursor.y,
                self.term.col - 1, self.term.cursor.y)
            return

        # 右移
        line = self.term.lines[self.term.cursor.y]
        for i in range(dst + size - 1, dst - 1, -1):
            line[i].copy_from(line[i - n])
        # 清空插入区域
        for i in range(dst, min(dst + n, self.term.col)):
            line[i].clear()

    def _t_delete_char(self, n: int):
        """删除 n 个字符（DCH）。"""
        src = self.term.cursor.x + n
        dst = self.term.cursor.x
        size = self.term.col - src
        self.term.dirty[self.term.cursor.y] = True

        if src >= self.term.col:
            self._t_clear_region(
                self.term.cursor.x, self.term.cursor.y,
                self.term.col - 1, self.term.cursor.y)
            return

        # 左移
        line = self.term.lines[self.term.cursor.y]
        for i in range(dst, dst + size):
            line[i].copy_from(line[i + n])
        # 清空尾部
        for i in range(self.term.col - n, self.term.col):
            line[i].clear()

    def _t_insert_blank_line(self, n: int):
        """插入 n 行（IL）。"""
        if self.term.cursor.y < self.term.top or \
           self.term.cursor.y > self.term.bot:
            return
        self.t_scroll_down(self.term.cursor.y, n)

    def _t_delete_line(self, n: int):
        """删除 n 行（DL）。"""
        if self.term.cursor.y < self.term.top or \
           self.term.cursor.y > self.term.bot:
            return
        self.t_scroll_up(self.term.cursor.y, n)

    def _t_set_scroll(self, t: int, b: int):
        """设置滚动区域。"""
        t = limit(t, 0, self.term.row - 1)
        b = limit(b, 0, self.term.row - 1)
        if t > b:
            t, b = b, t
        self.term.top = t
        self.term.bot = b

    # ══════════════════════════════════════════════════════
    # SGR — 字符属性设置
    # ══════════════════════════════════════════════════════

    def t_set_attr(self, args: list[int], narg: int):
        """处理 SGR (Select Graphic Rendition) 序列。"""
        i = 0
        while i < narg:
            a = args[i]
            if a == 0:
                self.term.cursor.attr.mode &= ~(
                    ATTR_REVERSE | ATTR_UNDERLINE | ATTR_BOLD |
                    ATTR_ITALIC | ATTR_BLINK)
                self.term.cursor.attr.fg = DEFAULT_FG
                self.term.cursor.attr.bg = DEFAULT_BG
            elif a == 1:
                self.term.cursor.attr.mode |= ATTR_BOLD
            elif a == 3:
                self.term.cursor.attr.mode |= ATTR_ITALIC
            elif a == 4:
                self.term.cursor.attr.mode |= ATTR_UNDERLINE
            elif a == 5:
                self.term.cursor.attr.mode |= ATTR_BLINK
            elif a == 7:
                self.term.cursor.attr.mode |= ATTR_REVERSE
            elif a in (21, 22):
                self.term.cursor.attr.mode &= ~ATTR_BOLD
            elif a == 23:
                self.term.cursor.attr.mode &= ~ATTR_ITALIC
            elif a == 24:
                self.term.cursor.attr.mode &= ~ATTR_UNDERLINE
            elif a == 25:
                self.term.cursor.attr.mode &= ~ATTR_BLINK
            elif a == 27:
                self.term.cursor.attr.mode &= ~ATTR_REVERSE
            elif a == 29:       # 删除线 — 不支持，忽略
                pass
            elif a == 38:       # 前景色（扩展）
                i = self._sgr_color(args, i, narg, fg=True)
            elif a == 39:
                self.term.cursor.attr.fg = DEFAULT_FG
            elif a == 48:       # 背景色（扩展）
                i = self._sgr_color(args, i, narg, fg=False)
            elif a == 49:
                self.term.cursor.attr.bg = DEFAULT_BG
            elif between(a, 30, 37):
                self.term.cursor.attr.fg = a - 30
            elif between(a, 40, 47):
                self.term.cursor.attr.bg = a - 40
            elif between(a, 90, 97):
                self.term.cursor.attr.fg = a - 90 + 8
            elif between(a, 100, 107):
                self.term.cursor.attr.bg = a - 100 + 8
            # 其他值静默忽略
            i += 1

    def _sgr_color(self, args: list[int], i: int, narg: int,
                   fg: bool) -> int:
        """处理 SGR 38;5;N / 48;5;N 扩展色或 38;2;R;G;B / 48;2 真彩色。
        返回更新后的索引 i。"""
        if i + 2 < narg and args[i + 1] == 5:
            # 256 色模式: 38;5;N
            color_idx = args[i + 2]
            if between(color_idx, 0, 255):
                if fg:
                    self.term.cursor.attr.fg = color_idx
                else:
                    self.term.cursor.attr.bg = color_idx
            return i + 2
        elif i + 4 < narg and args[i + 1] == 2:
            # RGB 模式: 38;2;R;G;B — 存真彩色元组 (R,G,B)，
            # renderer 直接使用，粗体不做亮化（C 版只取 R 分量，
            # 这里是超越原版）
            rgb = (args[i + 2], args[i + 3], args[i + 4])
            if all(between(c, 0, 255) for c in rgb):
                if fg:
                    self.term.cursor.attr.fg = rgb
                else:
                    self.term.cursor.attr.bg = rgb
            return i + 4
        return i

    # ══════════════════════════════════════════════════════
    # 模式设置（SM / RM）
    # ══════════════════════════════════════════════════════

    def t_set_mode(self, priv: bool, set_: bool,
                   args: list[int], narg: int):
        """处理模式设置（h=SM, l=RM）。"""
        for i in range(narg):
            a = args[i]
            if priv:
                self._set_priv_mode(a, set_)
            else:
                self._set_std_mode(a, set_)

    def _set_priv_mode(self, a: int, set_: bool):
        """DEC 私有模式。"""
        if a == 1:              # DECCKM — 光标键模式
            self._modbit(set_, MODE_APPKEYPAD)
        elif a == 5:            # DECSCNM — 反视频
            old = self.term.mode
            self._modbit(set_, MODE_REVERSE)
            if old != self.term.mode:
                # 等价 C 版的 redraw()：全屏重绘让反视频立即生效
                self.term.full_dirt()
        elif a == 7:            # DECAWM — 自动换行
            self._modbit(set_, MODE_WRAP)
        elif a == 25:           # 光标显示/隐藏
            if set_:
                self.term.cursor.state &= ~CURSOR_HIDE
            else:
                self.term.cursor.state |= CURSOR_HIDE
        elif a == 1000:         # xterm mouse report (button)
            self._modbit(set_, MODE_MOUSEBTN)
        elif a == 1002:         # xterm mouse report (motion)
            self._modbit(set_, MODE_MOUSEMOTION)
        elif a == 1049:         # 1047 + 1048 组合
            if set_:
                if not is_set(self.term.mode, MODE_ALTSCREEN):
                    self.t_cursor(self.CURSOR_SAVE)
                    self._t_swap_screen()
                    self.t_move_to(0, 0)
            else:
                if is_set(self.term.mode, MODE_ALTSCREEN):
                    self._t_swap_screen()
                    self.t_cursor(self.CURSOR_LOAD)
        elif a in (47, 1047):   # alt screen（不含光标保存）
            if set_:
                if not is_set(self.term.mode, MODE_ALTSCREEN):
                    self._t_swap_screen()
            else:
                if is_set(self.term.mode, MODE_ALTSCREEN):
                    self._t_swap_screen()
        elif a == 1048:         # 仅光标保存/恢复
            self.t_cursor(self.CURSOR_SAVE if set_ else self.CURSOR_LOAD)
        elif a == 2004:         # xterm bracketed paste — 括号粘贴
            self._modbit(set_, MODE_BRACKETPASTE)
        # 其他模式（3, 4, 6, 8, 12, 69, 1006, 1015）— 忽略

    def _set_std_mode(self, a: int, set_: bool):
        """标准模式（非私有）。"""
        if a == 2:              # KAM — 键盘锁定
            self._modbit(set_, MODE_KBDLOCK)
        elif a == 4:            # IRM — 插入模式
            self._modbit(set_, MODE_INSERT)
        elif a == 20:           # LNM — LF 变 CR+LF
            self._modbit(set_, MODE_CRLF)

    def _modbit(self, set_: bool, bit: int):
        """辅助：根据 set_ 设置或清除位。"""
        if set_:
            self.term.mode |= bit
        else:
            self.term.mode &= ~bit

    # ══════════════════════════════════════════════════════
    # 屏幕切换
    # ══════════════════════════════════════════════════════

    def _t_swap_screen(self):
        """切换主屏幕和 alt 屏幕。"""
        self.term.lines, self.term.alt_lines = \
            self.term.alt_lines, self.term.lines
        self.term.mode ^= MODE_ALTSCREEN
        self.term.full_dirt()
        # 确保光标在范围内
        self.term.cursor.x = limit(self.term.cursor.x, 0, self.term.col - 1)
        self.term.cursor.y = limit(self.term.cursor.y, 0, self.term.row - 1)

    # ══════════════════════════════════════════════════════
    # 光标保存/恢复
    # ══════════════════════════════════════════════════════

    CURSOR_SAVE = 4
    CURSOR_LOAD = 5

    def t_cursor(self, mode: int):
        """保存/恢复光标位置。"""
        screen_idx = 1 if is_set(self.term.mode, MODE_ALTSCREEN) else 0

        if mode == self.CURSOR_SAVE:
            saved = Cursor()
            saved.attr.copy_from(self.term.cursor.attr)
            saved.x = self.term.cursor.x
            saved.y = self.term.cursor.y
            saved.state = self.term.cursor.state
            self._saved_cursors[screen_idx] = saved
        elif mode == self.CURSOR_LOAD:
            if self._saved_cursors[screen_idx] is not None:
                sc = self._saved_cursors[screen_idx]
                self.term.cursor.attr.copy_from(sc.attr)
                self.term.cursor.x = sc.x
                self.term.cursor.y = sc.y
                self.term.cursor.state = sc.state

    # ══════════════════════════════════════════════════════
    # 重置
    # ══════════════════════════════════════════════════════

    def t_reset(self):
        """软重置终端到初始状态。"""
        self.term.cursor = Cursor()
        self.term.cursor.attr.fg = DEFAULT_FG
        self.term.cursor.attr.bg = DEFAULT_BG

        # 初始化制表位
        for i in range(self.term.col):
            self.term.tabs[i] = False
        tab_spaces = 4
        for i in range(tab_spaces, self.term.col, tab_spaces):
            self.term.tabs[i] = True

        self.term.top = 0
        self.term.bot = self.term.row - 1
        self.term.mode = MODE_WRAP

        self._t_clear_region(0, 0, self.term.col - 1, self.term.row - 1)

    # ══════════════════════════════════════════════════════
    # 窗口 resize
    # ══════════════════════════════════════════════════════

    def t_resize(self, col: int, row: int) -> bool:
        """调整终端网格尺寸。返回是否发生了滑动。"""
        if col < 1 or row < 1:
            return False

        slide = self.term.cursor.y - row + 1

        # 释放超出新行数的行
        old_row = self.term.row
        old_lines = list(self.term.lines)
        old_alt = list(self.term.alt_lines)

        if slide > 0:
            # 滑动屏幕以保持光标位置
            old_lines = old_lines[slide:]

        # 构建新网格
        new_lines = []
        new_alt = []
        new_dirty = []

        for i in range(row):
            if i < len(old_lines):
                line = old_lines[i]
                new_line = []
                for x in range(col):
                    if x < len(line):
                        new_line.append(line[x])
                    else:
                        new_line.append(Glyph())
                new_lines.append(new_line)
            else:
                new_lines.append([Glyph() for _ in range(col)])

            if i < len(old_alt) and i < old_row:
                alt_line = old_alt[i]
                new_alt_line = []
                for x in range(col):
                    if x < len(alt_line):
                        new_alt_line.append(alt_line[x])
                    else:
                        new_alt_line.append(Glyph())
                new_alt.append(new_alt_line)
            else:
                new_alt.append([Glyph() for _ in range(col)])

            new_dirty.append(True)

        self.term.lines = new_lines
        self.term.alt_lines = new_alt
        self.term.dirty = new_dirty
        self.term.col = col
        self.term.row = row

        # 重组制表位
        old_tabs = list(self.term.tabs)
        self.term.tabs = [False] * col
        for x in range(min(len(old_tabs), col)):
            self.term.tabs[x] = old_tabs[x]
        bp = len(old_tabs) - 1
        while bp >= 0 and not old_tabs[bp]:
            bp -= 1
        bp += 4
        while bp < col:
            self.term.tabs[bp] = True
            bp += TAB_SPACES

        # 限制光标
        self.t_move_to(self.term.cursor.x, self.term.cursor.y)
        self._t_set_scroll(0, row - 1)

        return slide > 0

    # ══════════════════════════════════════════════════════
    # PTY 接口桩（Phase 3 pty_handler.py 会替换）
    # ══════════════════════════════════════════════════════

    def tty_write(self, s: str):
        """向 PTY 写入数据。Phase 3 由 PtyHandler 实现。"""
        # 占位：打印到 stderr 用于调试
        import sys
        sys.stderr.write(f"[PTY_WRITE] {repr(s)}\n")
