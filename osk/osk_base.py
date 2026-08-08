"""osk_base.py — OSK 公共 UI 内核（语言键盘的基类）。

包含全部语言无关的部分：光标导航、键网格渲染、缓存、字体/颜色、
混合字体绘制工具。语言相关的差异通过子类钩子注入：

  - current_layout       布局（子类实现）
  - _switch_labels       语言切换键标签（如 "中"/"EN"）
  - on_modifier(label)   修饰键按下（英文切换布局）
  - _apply_modifiers     普通键的修饰应用（英文 Ctrl/Alt/Shift）
  - process(seq)         按键输出再处理（拼音路由；英文透传）
  - action(name)         动作键语义（b/start/select/l2/r2）
  - on_l1_press/release、on_r1_press  掌机按键回调（英文/拼音各自实现）
  - _is_locked(label)    键锁定高亮（英文 Ctrl/Alt/⇧）
  - extra_bar_rows / draw_extra()  顶部扩展渲染（拼音组合/候选区）
"""

import os

from PIL import Image, ImageDraw, ImageFont


class _OSKBase:
    """语言键盘基类 — 导航 + 渲染 + 缓存。"""

    language = "base"          # 子类覆盖（"en"/"pinyin"...）
    _switch_labels = ()        # 子类定义语言切换键标签
    extra_bar_rows = 0         # 顶部扩展行数（拼音=2）

    def __init__(self, screen_w: int, screen_h: int):
        self.screen_w = screen_w
        self.screen_h = screen_h

        # 导航
        self.col = 0         # 当前选中的列
        self.row = 0         # 当前选中的行

        # 语言切换请求 — press_selected 里按下切换键时置位，
        # 由 OSKManager 消费（切换后清除）
        self.switch_requested = False

        # 键盘视觉参数
        self.key_w = 48
        self.key_h = 34
        self.key_gap = 2
        self.margin = 4
        self.bar_row_h = 22   # 拼音组合区/候选区行高（比按键矮）

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
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "fonts")
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
        """当前布局（每行: [(标签, 输出), ...]）— 子类实现。"""
        raise NotImplementedError

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

        修饰键（output 为 None）分两类：
        - 语言切换键（_switch_labels）→ 置 switch_requested，由 manager 切换
        - 其他修饰键 → on_modifier(label) 钩子（英文切布局，拼音无）
        """
        label, output = self.current_key

        if output is None:
            if label in self._switch_labels:
                self.switch_requested = True
            else:
                self.on_modifier(label)
            self.invalidate()
            return None

        return self._apply_modifiers(label, output)

    def on_modifier(self, label: str):
        """修饰键按下（子类实现；拼音键盘无修饰键）。"""

    def _apply_modifiers(self, label: str, output: str) -> str:
        """普通键的修饰应用（子类覆盖；基类无修饰直接返回）。"""
        return output

    def process(self, seq: str | None) -> str | None:
        """按键输出的再处理（子类覆盖；英文透传，拼音走 IME 路由）。"""
        return seq

    def action(self, name: str) -> str | None:
        """动作键语义（b/start/select/l2/r2）— 语言通用部分。"""
        if name == "b":
            return "\177"        # Backspace
        if name == "start":
            return "\r"          # Enter
        if name == "select":
            return "\t"          # Tab
        if name == "l2":
            return "\033[D"      # 左方向键（直通）
        if name == "r2":
            return "\033[C"      # 右方向键（直通）
        return None

    # ── 掌机按键回调（子类实现各自语义，基类空操作） ────

    def on_l1_press(self):
        """L1 按下（子类实现：英文切 upper，拼音候选上一页）。"""

    def on_l1_release(self):
        """L1 松开（子类实现：英文回 lower）。"""

    def on_r1_press(self):
        """R1 按下（子类实现：英文 sticky 锁定，拼音候选下一页）。"""

    def _is_locked(self, label: str) -> bool:
        """键锁定高亮判断（子类覆盖）。"""
        return False

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

        # 顶部扩展（拼音组合区/候选区），键盘整体下移
        bar_h = self.extra_bar_rows * self.bar_row_h

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

        # 居中键盘内容（顶部扩展时整体下移 bar_h）
        offset_x = (self.screen_w - kb_w) // 2 + self.margin
        y0 = self.margin + bar_h

        # 子类扩展渲染（拼音组合区/候选区，与第一键左对齐）
        if self.extra_bar_rows:
            self.draw_extra(draw, self.margin, offset_x)

        font = self._font

        for r, row in enumerate(layout):
            for c, (label, output) in enumerate(row):
                x = offset_x + c * (self.key_w + self.key_gap)
                y = y0 + r * (self.key_h + self.key_gap)

                # 键背景色
                is_mod = output is None
                is_sel = (c == self.col and r == self.row)
                is_locked = is_mod and self._is_locked(label)

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

    def draw_extra(self, draw: ImageDraw.ImageDraw, margin: int,
                   offset_x: int):
        """顶部扩展渲染（子类覆盖；拼音组合区/候选区）。"""

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
