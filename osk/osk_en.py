"""osk_en.py — 英文键盘。

lower/upper/symbols 三套布局、Ctrl/Alt/⇧ 修饰键语义、
"中"键请求切换到拼音键盘。
"""

from osk.osk_base import _OSKBase

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
    # 🌐（"中"标签）在左下角，Alt 右移；"/" 移入符号层（符号层已有）
    [("中", None), ("Alt", None), ("z", "z"), ("x", "x"),
     ("c", "c"), ("v", "v"), ("b", "b"), ("n", "n"),
     ("m", "m"), (",", ","), (".", "."), ("#+=", None)],
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
    # "中"标签 + Alt 右移；"?" 移入符号层（符号层已有）
    [("中", None), ("Alt", None), ("Z", "Z"), ("X", "X"),
     ("C", "C"), ("V", "V"), ("B", "B"), ("N", "N"),
     ("M", "M"), ("<", "<"), (">", ">"), ("ABC", None)],
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


class OSKEn(_OSKBase):
    """英文键盘 — 布局切换 + 修饰键语义。"""

    language = "en"
    _switch_labels = ("中", "EN")

    def __init__(self, screen_w: int, screen_h: int):
        super().__init__(screen_w, screen_h)
        self.mode = "lower"  # lower / upper / symbols

        # 修饰键
        self.ctrl = False
        self.alt = False
        self.shift_locked = False

    @property
    def current_layout(self) -> list:
        return LAYOUTS[self.mode]

    def on_modifier(self, label: str):
        """修饰键 — 仅瞬时切换布局（不锁定，锁定由 R1 负责）。"""
        if label == "Ctrl":
            pass
        elif label == "Alt":
            pass
        elif label == "⇧":
            self.mode = "upper"
        elif label == "#+=":
            self.mode = "symbols"
        elif label == "ABC":
            self.mode = "lower"
            self.shift_locked = False

    def _apply_modifiers(self, label: str, output: str) -> str:
        """普通字符 — 应用锁定的 Ctrl/Alt 修饰。

        注意：必须用 output（布局定义的实际输出），
        不能是 label（显示标签）——⌫/↵/␣/↑ 等特殊键的
        label 是符号字形（如 U+232B），output 才是控制序列。
        """
        result = output
        if self.ctrl:
            ch = label[0].lower()
            if 'a' <= ch <= 'z':
                result = chr(ord(ch) - ord('a') + 1)
            # Ctrl 锁定保持 — 由 R1 解锁
        elif self.alt:
            result = "\033" + output
            # Alt 锁定保持 — 由 R1 解锁

        # 单次 Shift（非锁定时打完一个自动回小写）
        if self.mode == "upper" and not self.shift_locked:
            self.mode = "lower"
            self.invalidate()

        return result

    # ── 修饰键控制 ────────────────────────────────────

    def on_r1_press(self):
        """R1 按下 → 锁定/解锁当前选中的修饰键（sticky）。

        原版 KEY_OSKTOGGLE 行为：
        - 选中 Ctrl/Alt/⇧ 键时按 R1 → 锁定；再按 → 解锁
        - 普通键忽略
        """
        label, output = self.current_key
        if output is not None:
            return  # 普通键不 sticky

        changed = False
        if label == "Ctrl":
            self.ctrl = not self.ctrl
            changed = True
        elif label == "Alt":
            self.alt = not self.alt
            changed = True
        elif label == "⇧":
            if not self.shift_locked:
                self.mode = "upper"
                self.shift_locked = True
            else:
                self.mode = "lower"
                self.shift_locked = False
            changed = True
        if changed:
            self.invalidate()

    def on_l1_press(self):
        """L1 按下 → 切到 upper 布局（原版按住式 Shift）。"""
        if not self.shift_locked:
            self.mode = "upper"
            self.invalidate()

    def on_l1_release(self):
        """L1 松开 → 回 lower 布局。"""
        if not self.shift_locked:
            self.mode = "lower"
            self.invalidate()

    def _is_locked(self, label: str) -> bool:
        return ((label == "Ctrl" and self.ctrl) or
                (label == "Alt" and self.alt) or
                (label == "⇧" and self.shift_locked))
