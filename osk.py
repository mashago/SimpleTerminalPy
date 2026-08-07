"""SimpleTerminalPy — 虚拟键盘 (On-Screen Keyboard)。

对应 C 版 keyboard.c 的全部 OSK 渲染与导航逻辑。

渲染为 PIL Image，由 renderer.draw_frame() 合成到终端画面上。
"""

import os

from PIL import Image, ImageDraw, ImageFont

from pinyin_ime import PinyinIME

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

# 拼音模式布局：布局锁定小写（lower），末两位换 −/+ 翻页键
ROW_PINYIN = [
    [("Esc", "\033"), ("1", "1"), ("2", "2"), ("3", "3"),
     ("4", "4"), ("5", "5"), ("6", "6"), ("7", "7"),
     ("8", "8"), ("9", "9"), ("0", "0"), ("⌫", "\177")],
    [("Tab", "\t"), ("q", "q"), ("w", "w"), ("e", "e"),
     ("r", "r"), ("t", "t"), ("y", "y"), ("u", "u"),
     ("i", "i"), ("o", "o"), ("p", "p"), ("↵", "\r")],
    [("Ctrl", None), ("a", "a"), ("s", "s"), ("d", "d"),
     ("f", "f"), ("g", "g"), ("h", "h"), ("j", "j"),
     ("k", "k"), ("l", "l"), ("⇧", None), ("␣", " ")],
    # "EN" 标签 + 末尾 −/+ 翻页（拼音模式下 ⇧/#+= 无效）
    [("EN", None), ("Alt", None), ("z", "z"), ("x", "x"),
     ("c", "c"), ("v", "v"), ("b", "b"), ("n", "n"),
     ("m", "m"), (",", ","), (".", "."), ("−", "-"), ("+", "+")],
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
LAYOUTS["pinyin"] = ROW_PINYIN   # 拼音模式布局（锁定 lower 的变体）


class OSK:
    """虚拟键盘 — 渲染为 PIL Image，合成到终端画面上。"""

    def __init__(self, screen_w: int, screen_h: int,
                 dict_path: str | None = None):
        self.screen_w = screen_w
        self.screen_h = screen_h
        self.active = True
        self.location_bottom = True   # True=底部, False=顶部

        # 导航
        self.col = 0         # 当前选中的列
        self.row = 0         # 当前选中的行
        self.mode = "lower"  # lower / upper / symbols（拼音模式锁定 lower）

        # 修饰键
        self.ctrl = False
        self.alt = False
        self.shift_locked = False

        # 拼音输入法状态
        self.pinyin_active = False    # 🌐 切换
        self.pinyin_buf = ""          # 组合区字母
        self.pinyin_page = 0          # 候选区页码
        self.ime = PinyinIME(dict_path)

        # 键盘视觉参数
        self.key_w = 48
        self.key_h = 34
        self.key_gap = 2
        self.margin = 4

        # 颜色（背景不透明 — 半透明 paste 会透出底下内容导致颜色不均，
        # 且残留 alpha 混合值影响关闭后的覆盖）
        self.COLOR_BG = (40, 40, 50, 255)
        self.COLOR_KEY = (60, 60, 75, 255)
        self.COLOR_SEL = (70, 130, 180, 255)
        self.COLOR_LOCKED = (50, 120, 255, 255)
        self.COLOR_TOGGLED = (192, 192, 0, 255)
        self.COLOR_TEXT = (220, 220, 220, 255)
        self.COLOR_DIM = (150, 150, 160, 255)   # 提示文字（拼音栏）

        # 渲染缓存 — 只在状态变化时重建，避免每帧重画整张键盘
        self._cache: Image.Image | None = None
        self._dirty = True

        # 字体只加载一次（不要每次 render 都 truetype）
        self._font = None
        try:
            self._font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        except OSError:
            self._font = ImageFont.load_default()

        # CJK 字体（候选区汉字 + "中"键标签）——DejaVu Sans 无 CJK 字形
        # 回退路径与 renderer._init_fonts 一致
        self._cjk_font = self._font
        _fonts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "fonts")
        for path in (
            os.path.join(_fonts_dir, "DroidSansFallbackFull.ttf"),
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        ):
            try:
                self._cjk_font = ImageFont.truetype(path, 14)
                break
            except OSError:
                continue

    def invalidate(self):
        """状态变化时标记缓存失效。"""
        self._dirty = True
        self._cache = None

    # ── 布局 ──────────────────────────────────────────

    @property
    def current_layout(self) -> list:
        # 拼音模式锁定 lower 布局（变体 ROW_PINYIN：末尾 −/+ 翻页键）
        if self.pinyin_active:
            return ROW_PINYIN
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
        self.invalidate()

    def move_right(self):
        row = self.current_layout[self.row]
        self.col = (self.col + 1) % len(row)
        self.invalidate()

    def move_up(self):
        nrows = len(self.current_layout)
        self.row = (self.row - 1) % nrows
        # 对齐列数
        new_len = len(self.current_layout[self.row])
        if self.col >= new_len:
            self.col = new_len - 1
        self.invalidate()

    def move_down(self):
        nrows = len(self.current_layout)
        self.row = (self.row + 1) % nrows
        new_len = len(self.current_layout[self.row])
        if self.col >= new_len:
            self.col = new_len - 1
        self.invalidate()

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
            if label in ("中", "EN"):
                # 🌐 切换拼音模式（组合区清空，退出后布局复原）
                self.pinyin_active = not self.pinyin_active
                self.pinyin_buf = ""
                self.pinyin_page = 0
                # 进入拼音模式时清 Ctrl/Alt 锁定，避免字母被转成控制字符
                self.ctrl = False
                self.alt = False
            elif label == "Ctrl":
                pass  # 锁定由 R1 负责
            elif label == "Alt":
                pass
            elif label == "⇧":
                if not self.pinyin_active:   # 拼音模式锁定 lower
                    self.mode = "upper"
            elif label == "#+=":
                self.mode = "symbols"
            elif label == "ABC":
                self.mode = "lower"
                self.shift_locked = False
            self.invalidate()
            return None

        # 普通字符 — 应用锁定的 Ctrl/Alt 修饰
        # 注意：必须用 output（布局定义的实际输出），
        # 不能是 label（显示标签）——⌫/↵/␣/↑ 等特殊键的
        # label 是符号字形（如 U+232B），output 才是控制序列。
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

    # ── 拼音输入法按键路由 ────────────────────────────

    def process_pinyin(self, seq: str) -> str | None:
        """拼音模式的按键路由。返回要写入终端的文本，None=已消费。

        - 字母 a-z（大小写均收）→ 进组合区
        - 数字：组合区空 → 透传终端；非空 → 1..n 选字（>n 忽略）
        - \177（⌫/B 键）→ 智能退格：组合区有字删组合，空则透传终端
        - + / − → 候选翻页
        - \r（↵/START）→ 组合区有字提交原文（兜底），空则透传
        - 其余透传（控制字符、Alt 组合等）
        """
        if not self.pinyin_active:
            return seq

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

        return seq

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

    def shift_down(self):
        """L1 按下 → 切到 upper 布局（原版按住式 Shift）。"""
        if not self.shift_locked:
            self.mode = "upper"
            self.invalidate()

    def shift_up(self):
        """L1 松开 → 回 lower 布局。"""
        if not self.shift_locked:
            self.mode = "lower"
            self.invalidate()

    # ── 渲染 ──────────────────────────────────────────

    def render(self) -> Image.Image:
        """把键盘渲染为一张 RGBA PIL Image。

        尺寸 = 屏幕宽度 × 键盘高度。位置由调用方合成时决定。
        使用缓存：状态未变化时直接返回上次结果，
        避免每次主循环都重画整张键盘（CPU 占用大头）。
        """
        if not self._dirty and self._cache is not None:
            return self._cache

        layout = self.current_layout
        nrows = len(layout)

        # 拼音模式：顶部多 2 行（组合区 + 候选区），键盘整体下移
        bar_rows = 2 if self.pinyin_active else 0
        bar_h = bar_rows * (self.key_h + self.key_gap)

        # 计算键盘尺寸
        max_cols = max(len(row) for row in layout)
        kb_w = max_cols * (self.key_w + self.key_gap) + self.margin * 2
        kb_h = nrows * (self.key_h + self.key_gap) + self.margin * 2 + bar_h

        # 创建画布
        img = Image.new("RGBA", (self.screen_w, kb_h),
                        (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 背景
        draw.rectangle(
            (0, 0, self.screen_w - 1, kb_h - 1),
            fill=self.COLOR_BG)

        # 拼音模式：组合区 + 候选区（数字键上方）
        if self.pinyin_active:
            self._draw_pinyin_bar(draw, self.margin)

        # 居中键盘内容（拼音模式整体下移 bar_h）
        offset_x = (self.screen_w - kb_w) // 2 + self.margin
        y0 = self.margin + bar_h

        font = self._font

        for r, row in enumerate(layout):
            for c, (label, output) in enumerate(row):
                x = offset_x + c * (self.key_w + self.key_gap)
                y = y0 + r * (self.key_h + self.key_gap)

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

                # 键标签（居中）——"中"等 CJK 标签用回退字体
                label_font = self._cjk_font \
                    if any(self._needs_cjk(ch) for ch in label) \
                    else font
                bbox = draw.textbbox((0, 0), label, font=label_font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
                tx = x + (self.key_w - tw) // 2
                ty = y + (self.key_h - th) // 2
                draw.text((tx, ty), label,
                          fill=self.COLOR_TEXT, font=label_font)

        self._cache = img
        self._dirty = False
        return img

    # ── 拼音输入法渲染 ────────────────────────────────

    def _draw_pinyin_bar(self, draw: ImageDraw.ImageDraw, margin: int):
        """绘制拼音模式顶部的组合区 + 候选区两行（数字键上方）。"""
        y0 = margin
        y1 = margin + self.key_h + self.key_gap
        buf = self.pinyin_buf

        # 第一行：组合区（拼音字母 + 光标），空时提示
        comp = buf + "|" if buf else "拼音输入中"
        self._draw_text(draw, comp, margin, y0, self.COLOR_TEXT)

        # 第二行：候选区（1-5 选字），右侧页码
        cands, total = self.ime.page(buf, self.pinyin_page)
        if not buf:
            self._draw_text(draw, "输入拼音字母，1-5 选字，−/+ 翻页",
                            margin, y1, self.COLOR_DIM)
        elif not cands:
            self._draw_text(draw, "无匹配 — Enter 提交原文",
                            margin, y1, self.COLOR_DIM)
        else:
            text = "  ".join(f"{i + 1}{c}" for i, c in enumerate(cands))
            x_end = self._draw_text(draw, text, margin, y1, self.COLOR_TEXT)
            if total > 1:
                self._draw_text(
                    draw, f"第{self.pinyin_page + 1}/{total}页",
                    min(x_end + self.key_w, self.screen_w - margin - 60),
                    y1, self.COLOR_DIM)

    def _draw_text(self, draw: ImageDraw.ImageDraw, text: str,
                   x: int, y: int, color: tuple) -> int:
        """混合字体逐字绘制（ASCII 主字体 + CJK 回退），返回结束 x。"""
        for ch in text:
            font = self._cjk_font if self._needs_cjk(ch) else self._font
            draw.text((x, y), ch, fill=color, font=font)
            x += font.getlength(ch)
        return x

    @staticmethod
    def _needs_cjk(ch: str) -> bool:
        """判断字符是否需要 CJK 回退字体（> U+2E80 视为 CJK 区）。"""
        return ord(ch) > 0x2E80
