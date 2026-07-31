"""SimpleTerminalPy — 虚拟键盘 (On-Screen Keyboard)。

对应 C 版 keyboard.c 的全部 OSK 渲染与导航逻辑。

渲染为 PIL Image，由 renderer.draw_frame() 合成到终端画面上。
"""

from PIL import Image, ImageDraw, ImageFont

# ── 键盘布局 ────────────────────────────────────────────
# 每行: [(标签, 发送的字符串), ...]

ROW_LOWER = [
    [("Esc", "\033"), ("1", "1"), ("2", "2"), ("3", "3"),
     ("4", "4"), ("5", "5"), ("6", "6"), ("7", "7"),
     ("8", "8"), ("9", "9"), ("0", "0"), ("⌫", "\177")],
    [("Tab", "\t"), ("q", "q"), ("w", "w"), ("e", "e"),
     ("r", "r"), ("t", "t"), ("y", "y"), ("u", "u"),
     ("i", "i"), ("o", "o"), ("p", "p"), ("↵", "\r")],
    [("Ctrl", None), ("a", "a"), ("s", "s"), ("d", "d"),
     ("f", "f"), ("g", "g"), ("h", "h"), ("j", "j"),
     ("k", "k"), ("l", "l"), ("⇧", None), ("␣", " ")],
    [("Alt", None), ("z", "z"), ("x", "x"), ("c", "c"),
     ("v", "v"), ("b", "b"), ("n", "n"), ("m", "m"),
     (",", ","), (".", "."), ("/", "/"), ("#+=", None)],
]

ROW_UPPER = [
    [("Esc", "\033"), ("!", "!"), ("@", "@"), ("#", "#"),
     ("$", "$"), ("%", "%"), ("^", "^"), ("&", "&"),
     ("*", "*"), ("(", "("), (")", ")"), ("⌫", "\177")],
    [("Tab", "\t"), ("Q", "Q"), ("W", "W"), ("E", "E"),
     ("R", "R"), ("T", "T"), ("Y", "Y"), ("U", "U"),
     ("I", "I"), ("O", "O"), ("P", "P"), ("↵", "\r")],
    [("Ctrl", None), ("A", "A"), ("S", "S"), ("D", "D"),
     ("F", "F"), ("G", "G"), ("H", "H"), ("J", "J"),
     ("K", "K"), ("L", "L"), ("⇧", None), ("␣", " ")],
    [("Alt", None), ("Z", "Z"), ("X", "X"), ("C", "C"),
     ("V", "V"), ("B", "B"), ("N", "N"), ("M", "M"),
     ("<", "<"), (">", ">"), ("?", "?"), ("ABC", None)],
]

ROW_SYMBOLS = [
    [("F1", "\033OP"), ("F2", "\033OQ"), ("F3", "\033OR"),
     ("F4", "\033OS"), ("F5", "\033[15~"), ("F6", "\033[17~"),
     ("F7", "\033[18~"), ("F8", "\033[19~"),
     ("F9", "\033[20~"), ("F10", "\033[21~"),
     ("F11", "\033[23~"), ("F12", "\033[24~")],
    [("`", "`"), ("~", "~"), ("[", "["), ("]", "]"),
     ("{", "{"), ("}", "}"), ("|", "|"), ("\\", "\\"),
     ("(", "("), (")", ")"), ("\"", "\""), ("↵", "\r")],
    [("↑", "\033[A"), ("←", "\033[D"), ("↓", "\033[B"),
     ("→", "\033[C"), ("<", "<"), (">", ">"),
     (":", ":"), (";", ";"), ("'", "'"), ("⌫", "\177"),
     ("⇧", None), ("␣", " ")],
    [("-", "-"), ("_", "_"), ("=", "="), ("+", "+"),
     ("*", "*"), ("/", "/"), ("?", "?"),
     ("!", "!"), ("@", "@"), ("#", "#"),
     ("$", "$"), ("ABC", None)],
]

LAYOUTS = {
    "lower": ROW_LOWER,
    "upper": ROW_UPPER,
    "symbols": ROW_SYMBOLS,
}


class OSK:
    """虚拟键盘 — 渲染为 PIL Image，合成到终端画面上。"""

    def __init__(self, screen_w: int, screen_h: int):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.active = True
        self.location_bottom = True   # True=底部, False=顶部

        # 导航
        self.col = 0         # 当前选中的列
        self.row = 0         # 当前选中的行
        self.mode = "lower"  # lower / upper / symbols

        # 修饰键
        self.ctrl = False
        self.alt = False
        self.shift_locked = False

        # 键盘视觉参数
        self.key_w = 48
        self.key_h = 34
        self.key_gap = 2
        self.margin = 4

        # 颜色
        self.COLOR_BG = (40, 40, 50, 220)
        self.COLOR_KEY = (60, 60, 75, 255)
        self.COLOR_SEL = (70, 130, 180, 255)
        self.COLOR_LOCKED = (50, 120, 255, 255)
        self.COLOR_TOGGLED = (192, 192, 0, 255)
        self.COLOR_TEXT = (220, 220, 220, 255)

    # ── 布局 ──────────────────────────────────────────

    @property
    def current_layout(self) -> list:
        return LAYOUTS[self.mode]

    @property
    def current_key(self) -> tuple[str, str | None]:
        """当前选中键的 (标签, 输出)。"""
        r = self.current_layout[self.row]
        return r[self.col]

    # ── 导航 ──────────────────────────────────────────

    def move_left(self):
        row = self.current_layout[self.row]
        self.col = (self.col - 1) % len(row)

    def move_right(self):
        row = self.current_layout[self.row]
        self.col = (self.col + 1) % len(row)

    def move_up(self):
        nrows = len(self.current_layout)
        old_row = self.row
        self.row = (self.row - 1) % nrows
        # 对齐列数
        new_len = len(self.current_layout[self.row])
        if self.col >= new_len:
            self.col = new_len - 1

    def move_down(self):
        nrows = len(self.current_layout)
        old_row = self.row
        self.row = (self.row + 1) % nrows
        new_len = len(self.current_layout[self.row])
        if self.col >= new_len:
            self.col = new_len - 1

    # ── 按键动作 ──────────────────────────────────────

    def press_selected(self) -> str | None:
        """按下当前选中的键。返回要发送到 PTY 的字符串（或 None）。

        原版行为：
        - A 按修饰键（Ctrl/Alt/⇧）= 瞬时按下，不锁定
        - 锁定由 R1 (toggle_sticky) 负责
        - Ctrl/Alt 锁定状态下按字母 → 应用修饰，锁定保持（需 R1 解锁）
        """
        label, output = self.current_key

        if output is None:
            # 修饰键 — 仅瞬时切换布局（不锁定）
            if label == "Ctrl":
                pass  # 锁定由 R1 负责
            elif label == "Alt":
                pass
            elif label == "⇧":
                self.mode = "upper"
            elif label == "#+=":
                self.mode = "symbols"
            elif label == "ABC":
                self.mode = "lower"
                self.shift_locked = False
            return None

        # 普通字符 — 应用锁定的 Ctrl/Alt 修饰
        result = label
        if self.ctrl:
            ch = label[0].lower()
            if 'a' <= ch <= 'z':
                result = chr(ord(ch) - ord('a') + 1)
            # Ctrl 锁定保持 — 由 R1 解锁
        elif self.alt:
            result = "\033" + label
            # Alt 锁定保持 — 由 R1 解锁

        # 单次 Shift（非锁定时打完一个自动回小写）
        if self.mode == "upper" and not self.shift_locked:
            self.mode = "lower"

        return result

    # ── 修饰键控制 ────────────────────────────────────

    def toggle_sticky(self):
        """R1 → 锁定/解锁当前选中的修饰键（sticky）。

        原版 KEY_OSKTOGGLE 行为：
        - 选中 Ctrl/Alt/⇧ 键时按 R1 → 锁定；再按 → 解锁
        - 普通键忽略
        """
        label, output = self.current_key
        if output is not None:
            return  # 普通键不 sticky

        if label == "Ctrl":
            self.ctrl = not self.ctrl
        elif label == "Alt":
            self.alt = not self.alt
        elif label == "⇧":
            if not self.shift_locked:
                self.mode = "upper"
                self.shift_locked = True
            else:
                self.mode = "lower"
                self.shift_locked = False

    def shift_down(self):
        """L1 按下 → 切到 upper 布局（原版按住式 Shift）。"""
        if not self.shift_locked:
            self.mode = "upper"

    def shift_up(self):
        """L1 松开 → 回 lower 布局。"""
        if not self.shift_locked:
            self.mode = "lower"

    # ── 渲染 ──────────────────────────────────────────

    def render(self) -> Image.Image:
        """把键盘渲染为一张 RGBA PIL Image。

        尺寸 = 屏幕宽度 × 键盘高度。位置由调用方合成时决定。
        """
        layout = self.current_layout
        nrows = len(layout)

        # 计算键盘尺寸
        max_cols = max(len(row) for row in layout)
        kb_w = max_cols * (self.key_w + self.key_gap) + self.margin * 2
        kb_h = nrows * (self.key_h + self.key_gap) + self.margin * 2

        # 创建画布
        img = Image.new("RGBA", (self.screen_w, kb_h),
                        (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 背景
        draw.rectangle(
            (0, 0, self.screen_w - 1, kb_h - 1),
            fill=self.COLOR_BG)

        # 居中键盘内容
        offset_x = (self.screen_w - kb_w) // 2 + self.margin

        # 加载字体
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except OSError:
            font = ImageFont.load_default()

        for r, row in enumerate(layout):
            for c, (label, output) in enumerate(row):
                x = offset_x + c * (self.key_w + self.key_gap)
                y = self.margin + r * (self.key_h + self.key_gap)

                # 键背景色
                is_mod = output is None
                is_sel = (c == self.col and r == self.row)
                is_locked = (is_mod and
                             ((label == "Ctrl" and self.ctrl) or
                              (label == "Alt" and self.alt) or
                              (label == "⇧" and self.shift_locked)))

                if is_sel and is_locked:
                    bg = self.COLOR_TOGGLED
                elif is_sel:
                    bg = self.COLOR_SEL
                elif is_locked:
                    bg = self.COLOR_LOCKED
                else:
                    bg = self.COLOR_KEY

                draw.rectangle(
                    (x, y, x + self.key_w, y + self.key_h),
                    fill=bg)

                # 键标签（居中）
                bbox = draw.textbbox((0, 0), label, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = x + (self.key_w - tw) // 2
                ty = y + (self.key_h - th) // 2
                draw.text((tx, ty), label,
                          fill=self.COLOR_TEXT, font=font)

        return img
