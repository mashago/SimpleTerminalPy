"""osk_pinyin.py — 拼音键盘。

组合/候选状态委托给 PinyinIME（self.ime，纯状态机）；PinyinEngine
查询实例可与外接键盘拼音共享（字典只加载一次）。布局锁定小写：
无 Esc/Tab/Ctrl/Alt/⇧，+ 在 0 与 ⌫ 之间，− 在 p 与回车之间，
EN 在末行最左（请求切回英文键盘）。
"""

from PIL import ImageDraw

from osk.osk_base import _OSKBase
from pinyin_ime import PinyinEngine, PinyinIME

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
                 engine: PinyinEngine | None = None):
        super().__init__(screen_w, screen_h)
        self.ime = PinyinIME(engine=engine)

    @property
    def current_layout(self) -> list:
        return ROW_PINYIN

    def on_modifier(self, label: str):
        pass   # 拼音布局无修饰键（EN 是语言切换键，由基类处理）

    # ── 按键路由（委托状态机） ─────────────────────────

    def process(self, seq: str | None) -> str | None:
        """按键输出的再处理（委托 PinyinIME；状态变化时刷新缓存）。"""
        out = self.ime.process(seq)
        self.invalidate()
        return out

    def action(self, name: str) -> str | None:
        """动作键语义：b/start 走 IME（智能退格/Enter 兜底）。"""
        if name == "b":
            return self.process("\177")
        if name == "start":
            return self.process("\r")
        return super().action(name)

    def on_l1_press(self):
        """L1 按下 → 候选上一页（类似 −）。"""
        self.ime.page_prev()
        self.invalidate()

    def on_r1_press(self):
        """R1 按下 → 候选下一页（类似 +）。"""
        self.ime.page_next()
        self.invalidate()

    # ── 渲染 ──────────────────────────────────────────

    def draw_extra(self, draw: ImageDraw.ImageDraw, margin: int,
                   offset_x: int):
        """顶部组合区 + 候选区两行（数字键上方）。

        与键盘第一键左对齐（offset_x）；页码右对齐到键盘右缘。
        """
        y0 = margin
        y1 = margin + self.bar_row_h
        buf = self.ime.buf
        cands, total = self.ime.candidates
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
        if not buf:
            self._draw_text(draw, "输入拼音字母，1-9 选字，−/+/L1/R1 翻页",
                            offset_x, ty1, self.COLOR_DIM)
        elif not cands:
            self._draw_text(draw, "无匹配 — Enter 提交原文",
                            offset_x, ty1, self.COLOR_DIM)
        else:
            text = "  ".join(f"{i + 1}{c}" for i, c in enumerate(cands))
            x_end = self._draw_text(draw, text, offset_x, ty1,
                                    self.COLOR_TEXT)
            if total > 1:
                ind = f"第{self.ime.page + 1}/{total}页"
                w = sum(
                    (self._cjk_font if self._needs_cjk(c) else self._font)
                    .getlength(c) for c in ind)
                ix = max(x_end + self.key_w, keys_right - w)
                self._draw_text(draw, ind, ix, ty1, self.COLOR_DIM)
