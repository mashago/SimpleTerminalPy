"""osk_pinyin.py — 拼音键盘。

组合区/候选区状态、IME 路由（process）、顶部两行渲染。
布局锁定小写：无 Esc/Tab/Ctrl/Alt/⇧，+ 在 0 与 ⌫ 之间，
− 在 p 与回车之间，EN 在末行最左（请求切回英文键盘）。
"""

from PIL import ImageDraw

from osk.osk_base import _OSKBase
from pinyin_ime import PinyinIME

# ── 拼音模式布局 ────────────────────────────────────────
# 每行: [(标签, 发送的字符串), ...]

ROW_PINYIN = [
    [("1", "1"), ("2", "2"), ("3", "3"), ("4", "4"),
     ("5", "5"), ("6", "6"), ("7", "7"), ("8", "8"),
     ("9", "9"), ("0", "0"), ("+", "+"), ("⌫", "\177")],
    [("q", "q"), ("w", "w"), ("e", "e"), ("r", "r"),
     ("t", "t"), ("y", "y"), ("u", "u"), ("i", "i"),
     ("o", "o"), ("p", "p"), ("−", "-"), ("↵", "\r")],
    [("a", "a"), ("s", "s"), ("d", "d"), ("f", "f"),
     ("g", "g"), ("h", "h"), ("j", "j"), ("k", "k"),
     ("l", "l"), ("␣", " ")],
    [("EN", None), ("z", "z"), ("x", "x"), ("c", "c"),
     ("v", "v"), ("b", "b"), ("n", "n"), ("m", "m"),
     (",", ","), (".", ".")],
]


class OSKPinyin(_OSKBase):
    """拼音键盘 — 组合/候选/IME 路由 + 顶部两行渲染。"""

    language = "pinyin"
    _switch_labels = ("EN",)
    extra_bar_rows = 2     # 组合区 + 候选区

    def __init__(self, screen_w: int, screen_h: int,
                 dict_path: str | None = None):
        super().__init__(screen_w, screen_h)
        self.pinyin_buf = ""          # 组合区字母
        self.pinyin_page = 0          # 候选区页码
        self.ime = PinyinIME(dict_path)

    @property
    def current_layout(self) -> list:
        return ROW_PINYIN

    def on_modifier(self, label: str):
        pass   # 拼音布局无修饰键（EN 是语言切换键，由基类处理）

    # ── 按键路由 ──────────────────────────────────────

    def process(self, seq: str | None) -> str | None:
        """按键输出的再处理。返回要写入终端的文本，None=已消费。

        - 字母 a-z（大小写均收）→ 进组合区
        - 数字：组合区空 → 透传终端；非空 → 1..n 选字（>n 忽略）
        - \177（⌫/B 键）→ 智能退格：组合区有字删组合，空则透传终端
        - + / − → 候选翻页
        - \r（↵/START）→ 组合区有字提交原文（兜底），空则透传
        - 组合区有内容时 ␣/,/. 不进终端（否则 ⌫ 只删组合，符号无法删）
        - 其余透传（控制字符、Alt 组合等）
        """
        if seq is None:
            return None

        # 字母 → 组合区
        if len(seq) == 1 and seq.lower() in "abcdefghijklmnopqrstuvwxyz":
            self.pinyin_buf += seq.lower()
            self.pinyin_page = 0
            self.invalidate()
            return None

        # 数字 → 选字 / 透传
        if len(seq) == 1 and seq.isdigit():
            if not self.pinyin_buf:
                return seq          # 组合区空 → 正常输数字
            cands, _ = self.ime.page(self.pinyin_buf, self.pinyin_page)
            idx = int(seq) - 1
            if 0 <= idx < len(cands):
                out = cands[idx]
                self.pinyin_buf = ""
                self.pinyin_page = 0
                self.invalidate()
                return out          # 选中汉字 → 终端
            return None             # 无此候选 → 忽略

        # 智能退格
        if seq == "\177":
            if self.pinyin_buf:
                self.pinyin_buf = self.pinyin_buf[:-1]
                self.pinyin_page = 0
                self.invalidate()
                return None
            return "\177"           # 组合区空 → 透传终端

        # 候选翻页
        if seq in ("+", "-"):
            _, total = self.ime.page(self.pinyin_buf, self.pinyin_page)
            if total <= 1:
                return None
            self.pinyin_page += 1 if seq == "+" else -1
            self.pinyin_page = max(0, min(self.pinyin_page, total - 1))
            self.invalidate()
            return None

        # Enter 兜底：提交原始拼音
        if seq in ("\r", "\n"):
            if self.pinyin_buf:
                out = self.pinyin_buf
                self.pinyin_buf = ""
                self.pinyin_page = 0
                self.invalidate()
                return out
            return "\r"

        # 组合区有内容时，布局上可透传的按键（空格/逗号/句号）不进终端——
        # 否则 backspace 只能删组合区，误输入的符号无法删除
        if self.pinyin_buf and seq in (" ", ",", "."):
            return None

        return seq

    def action(self, name: str) -> str | None:
        """动作键语义：b/start 走 IME（智能退格/Enter 兜底）。"""
        if name == "b":
            return self.process("\177")
        if name == "start":
            return self.process("\r")
        return super().action(name)

    # ── 渲染 ──────────────────────────────────────────

    def draw_extra(self, draw: ImageDraw.ImageDraw, margin: int,
                   offset_x: int):
        """顶部组合区 + 候选区两行（数字键上方）。

        与键盘第一键左对齐（offset_x）；页码右对齐到键盘右缘。
        """
        y0 = margin
        y1 = margin + self.bar_row_h
        buf = self.pinyin_buf
        layout = self.current_layout
        max_cols = max(len(row) for row in layout)
        keys_right = offset_x + (max_cols - 1) * (self.key_w + self.key_gap) \
            + self.key_w

        # 行内垂直居中（矮行放 14px 文字）
        _, descent = self._font.getmetrics()
        text_h = self._font.getmetrics()[0] + descent
        ty0 = y0 + max(0, (self.bar_row_h - text_h) // 2)
        ty1 = y1 + max(0, (self.bar_row_h - text_h) // 2)

        # 第一行：组合区（拼音字母 + 光标），空时提示
        comp = buf + "|" if buf else "拼音输入中"
        self._draw_text(draw, comp, offset_x, ty0, self.COLOR_TEXT)

        # 第二行：候选区（1-9 选字），页码右对齐键盘右缘
        cands, total = self.ime.page(buf, self.pinyin_page)
        if not buf:
            self._draw_text(draw, "输入拼音字母，1-9 选字，−/+ 翻页",
                            offset_x, ty1, self.COLOR_DIM)
        elif not cands:
            self._draw_text(draw, "无匹配 — Enter 提交原文",
                            offset_x, ty1, self.COLOR_DIM)
        else:
            text = "  ".join(f"{i + 1}{c}" for i, c in enumerate(cands))
            x_end = self._draw_text(draw, text, offset_x, ty1,
                                    self.COLOR_TEXT)
            if total > 1:
                ind = f"第{self.pinyin_page + 1}/{total}页"
                w = sum(
                    (self._cjk_font if self._needs_cjk(c) else self._font)
                    .getlength(c) for c in ind)
                ix = max(x_end + self.key_w, keys_right - w)
                self._draw_text(draw, ind, ix, ty1, self.COLOR_DIM)
