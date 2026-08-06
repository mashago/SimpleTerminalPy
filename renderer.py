"""SimpleTerminalPy — 渲染引擎（PIL + PySDL2）。

对应 C 版 main.c 的 draw_region(), x_draws(), draw_scrollbar(),
update_render() 以及 font.c 的全部渲染逻辑。

遵循方案文档的设计：PIL 先行，对外只暴露 4 个方法，
内部可切换到 SDL blit 而不影响其他模块。
"""

import os
from collections import OrderedDict

import sdl2
from PIL import Image, ImageDraw, ImageFont

from terminal import (
    Term, Glyph, GLYPH_SET, GLYPH_WIDE_TAIL,
    ATTR_BOLD, ATTR_UNDERLINE, ATTR_REVERSE,
)
from config import COLORMAP, DEFAULT_FG, DEFAULT_BG, DEFAULT_CS
from wcwidth import char_width


class Renderer:
    """终端渲染引擎。

    对外 API:
      __init__(term, width, height, char_w, char_h, ...)
      draw_frame(osk_surface=None) → None
      resize(width, height) → None
      shutdown() → None
    """

    def __init__(self, term: Term,
                 renderer,          # sdl2.SDL_Renderer
                 width: int, height: int,
                 char_w: int = 8, char_h: int = 16,
                 border_px: int = 2,
                 font_path: str | None = None,
                 font_size: int = 12,
                 opt_rotate: int = 0):
        self.term = term
        self.sdl_renderer = renderer
        self.width = width
        self.height = height
        self.char_w = char_w
        self.char_h = char_h
        self.border_px = border_px
        self.opt_rotate = opt_rotate

        # PIL 画布
        self._img = Image.new("RGBA", (width, height), color=(0, 0, 0, 255))
        self._draw = ImageDraw.Draw(self._img)

        # SDL 纹理
        self._texture = None
        self._tex_w = 0
        self._tex_h = 0
        self._recreate_texture(width, height)

        # 字体
        self.font_path = font_path
        self.font_size = font_size
        self._pil_font = None
        self._pil_font_bold = None
        self._init_fonts()

        # 字形图集 — LRU 缓存
        # key = (char, fg_index, bold)
        self._glyph_cache: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._glyph_cache_max = 1000
        self._glyph_cache_hits = 0
        self._glyph_cache_misses = 0

        # 光标 blink
        self._cursor_blink = True
        self._cursor_reverse = False  # 用于显示闪烁

        # 旧光标位置 — 画新光标前先恢复（C 版的 static oldx/oldy）
        self._old_cx = 0
        self._old_cy = 0

    # ══════════════════════════════════════════════════════
    # 初始化
    # ══════════════════════════════════════════════════════

    def _recreate_texture(self, w: int, h: int):
        if self._texture:
            sdl2.SDL_DestroyTexture(self._texture)
        self._texture = sdl2.SDL_CreateTexture(
            self.sdl_renderer,
            sdl2.SDL_PIXELFORMAT_RGBA32,
            sdl2.SDL_TEXTUREACCESS_STREAMING,
            w, h,
        )
        self._tex_w = w
        self._tex_h = h

    def _init_fonts(self):
        """加载 PIL 字体。优先指定 font_path，然后尝试 CJK 回退。"""
        # 主字体
        if self.font_path and self.font_path not in \
           ('1', '2', '3', '4', '5'):
            try:
                self._pil_font = ImageFont.truetype(
                    self.font_path, self.font_size)
                self._pil_font_bold = self._pil_font
            except OSError:
                pass

        # 项目自带字体目录（fonts/，Apache 2.0，来源明确）
        _fonts_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "fonts")

        if self._pil_font is None:
            # 优先项目自带等宽字体，再尝试系统字体
            # DejaVu Sans Mono 符号覆盖最全（─│❯▝▲●■→✓ 等），
            # Droid Sans Mono 仅覆盖基础 Latin。
            fallbacks = [
                os.path.join(_fonts_dir, "DejaVuSansMono.ttf"),
                os.path.join(_fonts_dir, "DroidSansMono.ttf"),
                "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
                "/mnt/vendor/bin/default.ttf",
            ]
            for path in fallbacks:
                try:
                    self._pil_font = ImageFont.truetype(
                        path, self.font_size)
                    self._pil_font_bold = self._pil_font
                    self.font_path = path
                    break
                except OSError:
                    continue

        if self._pil_font is None:
            self._pil_font = ImageFont.load_default()
            self._pil_font_bold = self._pil_font

        # CJK 回退字体（用于主字体不含的汉字）
        self._cjk_font = None
        cjk_fallbacks = [
            # 项目自带 CJK 字体（Apache 2.0，来源明确）
            os.path.join(_fonts_dir, "DroidSansFallbackFull.ttf"),
            # 掌机固件自带（Anbernic 等，RgMenu 验证可用）
            "/mnt/vendor/bin/default.ttf",
            # 项目本地字体（用户可放入）
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "font.ttf"),
            # Noto Sans CJK
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansSC-Regular.otf",
            "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ]
        for path in cjk_fallbacks:
            try:
                self._cjk_font = ImageFont.truetype(path, self.font_size)
                print(f"Renderer: CJK font {path} ({self.font_size}px)")
                break
            except OSError:
                continue

        if self._cjk_font is None and self._pil_font:
            self._cjk_font = self._pil_font  # 回退到主字体

        print(f"Renderer: using font {self.font_path or 'default'}"
              f" ({self.font_size}px)"
              f" cjk={self._cjk_font is not None}")

    # ══════════════════════════════════════════════════════
    # draw_frame — 主渲染入口
    # ══════════════════════════════════════════════════════

    def draw_frame(self, osk_surface: Image.Image | None = None,
                   osk_top: bool = False):
        """遍历脏行，增量渲染，合成 OSK，上传纹理。

        osk_top: OSK 固定在顶部（True）还是底部（False）。
        画布在帧间保持，不清除。只重绘变动的行。
        上传时只更新变化的像素区域（局部上传），大幅降低 CPU 开销。
        """
        term = self.term

        # 脏行范围（像素区域）
        dirty_top = term.row      # 终端行号范围
        dirty_bot = -1

        # 只处理脏行
        for y in range(term.row):
            if not term.dirty[y]:
                continue
            term.dirty[y] = False
            dirty_top = min(dirty_top, y)
            dirty_bot = max(dirty_bot, y)
            self._draw_dirty_line(y)

        # 光标（仅非滚动状态）—— 旧/新位置都算入更新区域
        if term.scroll_offset == 0 and \
           not (term.cursor.state & 1):  # CURSOR_HIDE
            dirty_top = min(dirty_top, self._old_cy, term.cursor.y)
            dirty_bot = max(dirty_bot, self._old_cy, term.cursor.y)
            self._draw_cursor()

        # scrollbar 指示器（第一行区域）
        if term.scroll_offset > 0:
            dirty_top = min(dirty_top, 0)
            dirty_bot = max(dirty_bot, 0)
            self._draw_scroll_indicator()

        # 清空 terminal grid 下方的区域（OSK 旧画面残留）
        # 注意：绘制后必须纳入 dirty 范围，否则局部上传不会更新这段区域
        term_bottom = self.border_px + term.row * self.char_h
        if term_bottom < self.height:
            self._draw.rectangle(
                (0, term_bottom, self.width, self.height),
                fill=self._color_of(DEFAULT_BG))
            dirty_bot = max(dirty_bot, term.row)   # 覆盖 grid 外区域到底部

        # 合成 OSK（顶部或底部）
        if osk_surface:
            osk_h = osk_surface.height
            if osk_top:
                osk_y = 0
            else:
                osk_y = self.height - osk_h
            self._img.paste(osk_surface, (0, osk_y), osk_surface)
            # OSK 区域纳入更新
            dirty_top = min(dirty_top, (osk_y - self.border_px) // self.char_h)
            dirty_bot = max(dirty_bot, (osk_y + osk_h - 1 - self.border_px) // self.char_h)

        # 上传纹理（局部区域）
        self._flush(dirty_top, dirty_bot)

    # ══════════════════════════════════════════════════════
    # 脏行绘制
    # ══════════════════════════════════════════════════════

    def _draw_dirty_line(self, y: int):
        """绘制一行。从 scrollback 或当前网格读取。"""
        term = self.term

        # 决定从哪读行数据
        if term.scroll_offset > 0 and y < term.scroll_offset:
            sb_idx = len(term.scrollback) - term.scroll_offset + y
            if 0 <= sb_idx < len(term.scrollback):
                line = term.scrollback[sb_idx]
            else:
                return  # scrollback 历史不足 — 显示空行（背景已清）
        else:
            screen_y = y - term.scroll_offset
            if 0 <= screen_y < term.row:
                line = term.lines[screen_y]
            else:
                return

        # 先清空整行背景（否则残留上一帧的画面）
        # 全宽清除（含左右 border）— OSK 等全宽合成物可能覆盖 border 区域
        py_clear = self.border_px + y * self.char_h
        self._draw.rectangle(
            (0, py_clear, self.width, py_clear + self.char_h - 1),
            fill=self._color_of(DEFAULT_BG))

        # 合并同属性相邻格，批量绘制
        x = 0
        while x < term.col:
            glyph = line[x]

            # 跳过 WIDE_TAIL 格（已在前一个宽字符时绘制）
            if glyph.state & GLYPH_WIDE_TAIL:
                x += 1
                continue

            if not glyph.state & GLYPH_SET:
                x += 1
                continue

            base_attr = (glyph.fg, glyph.bg, glyph.mode)
            batch_start = x

            while x < term.col:
                g = line[x]
                if g.state & GLYPH_WIDE_TAIL:
                    x += 1
                    continue
                if not (g.state & GLYPH_SET):
                    break
                if (g.fg, g.bg, g.mode) != base_attr:
                    break
                x += 1

            batch_end = x

            # 画背景（reverse 时前景/背景交换：背景画 fg 色）
            bg_color = self._color_of(
                base_attr[0] if base_attr[2] & ATTR_REVERSE
                else base_attr[1])
            px = self.border_px + batch_start * self.char_w
            py = self.border_px + y * self.char_h
            pw = (batch_end - batch_start) * self.char_w

            self._draw.rectangle(
                (px, py, px + pw - 1, py + self.char_h - 1),
                fill=bg_color)

            # 画每个字符
            i = batch_start
            while i < batch_end:
                g = line[i]
                if g.state & GLYPH_WIDE_TAIL:
                    i += 1
                    continue
                ch_w = char_width(g.c)
                w = 1 if ch_w <= 1 else ch_w
                self._draw_glyph_at(i, y, g, width=w)
                i += w

    def _draw_glyph_at(self, x: int, y: int, glyph: Glyph,
                       width: int = 1):
        """在位置 (x, y) 绘制单个 glyph（支持双列宽）。"""
        c = glyph.c
        if not c or c == ' ':
            return

        # reverse 时交换前景/背景（vim 可视选择等）
        reverse = bool(glyph.mode & ATTR_REVERSE)
        fg_idx = glyph.bg if reverse else glyph.fg
        bold = bool(glyph.mode & ATTR_BOLD)
        underline = bool(glyph.mode & ATTR_UNDERLINE)

        # 粗体颜色亮化（C 版 x_draws 行为，对齐 mintty 的 Bold 色）：
        # bold 时 0-7 基本色 → +8 亮色，256 色立方 → +36，灰度 → +4
        # 真彩色 (R,G,B) 元组不做亮化 — 真实终端行为，主题粗体颜色不漂移
        if bold and isinstance(fg_idx, int):
            if 0 <= fg_idx <= 7:
                fg_idx += 8
            elif 16 <= fg_idx <= 195:
                fg_idx += 36
            elif 232 <= fg_idx <= 251:
                fg_idx += 4

        px = self.border_px + x * self.char_w
        py = self.border_px + y * self.char_h

        # 从缓存取 glyph 图像（width 参数控制渲染宽度）
        img = self._get_glyph_image(c, fg_idx, bold, width)
        if img is not None:
            self._img.paste(img, (px, py), img)

        # 下划线（画在基线下方 1px，不是格子底边）
        if underline:
            ul_w = self.char_w * width
            font = self._pil_font_bold if bold else self._pil_font
            if font is not None:
                _, descent = font.getmetrics()
                ul_y = py + self.char_h - descent + 1
            else:
                ul_y = py + self.char_h - 2
            self._draw.line(
                (px, ul_y, px + ul_w - 1, ul_y),
                fill=self._color_of(fg_idx), width=1)

    # ══════════════════════════════════════════════════════
    # 字形缓存
    # ══════════════════════════════════════════════════════

    def _get_glyph_image(self, ch: str, fg_idx: int,
                         bold: bool, width: int = 1) -> Image.Image | None:
        """获取或渲染一个字形的 PIL Image。

        key = (ch, fg_idx, bold, width)
        缓存上限 1000，LRU 淘汰。
        """
        if ch in (' ', '\0', ''):
            return None

        key = (ch, fg_idx, bold, width)
        if key in self._glyph_cache:
            self._glyph_cache.move_to_end(key)
            return self._glyph_cache[key]

        self._glyph_cache_misses += 1

        img = self._render_glyph(ch, fg_idx, bold, width)
        if img is None:
            return None

        while len(self._glyph_cache) >= self._glyph_cache_max:
            self._glyph_cache.popitem(last=False)

        self._glyph_cache[key] = img
        return img

    def _render_glyph(self, ch: str, fg_idx: int,
                      bold: bool, width: int = 1) -> Image.Image | None:
        """PIL 渲染单个字符为 RGBA 图像。

        width=1: 正常 1 列字符
        width=2: CJK 双列宽字符
        """
        # CJK 字符使用 CJK 回退字体
        if width == 2 and self._cjk_font:
            font = self._cjk_font
        else:
            font = self._pil_font_bold if bold else self._pil_font
        if font is None:
            return None

        fg = self._color_of(fg_idx)
        img_w = self.char_w * width
        img_h = self.char_h

        img = Image.new("RGBA", (img_w, img_h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        bbox = draw.textbbox((0, 0), ch, font=font)
        text_w = bbox[2] - bbox[0]

        if width == 1:
            # 等宽字符：左对齐绘制，字形起点固定
            # （居中会导致窄字符 i 与宽字符 m 在格子里位置不同，
            #   单词看起来左右参差 = 歪歪扭扭）
            x_off = -bbox[0]
        else:
            # 宽字符（中文等方块字）：居中
            x_off = (img_w - text_w) // 2 - bbox[0]

        # 基线对齐（不垂直居中！）：
        # PIL 的 draw.text((x, y)) 中基线 = y + ascent（与字符无关）。
        # 固定基线在格子底部上方 descent 处（标准终端行为），
        # 让 t/m/p/P 等不同高度的字符基线一致，不会高低错位。
        # 注意：绝不能减 bbox[1]——每个字符 bbox 偏移不同，
        # 减了会导致各字符基线错位（koook 中 o 偏上）。
        ascent, descent = font.getmetrics()
        y_off = img_h - (ascent + descent)

        draw.text((x_off, y_off), ch, fill=fg, font=font)
        return img

    # ══════════════════════════════════════════════════════
    # 光标
    # ══════════════════════════════════════════════════════

    def _draw_cursor(self):
        """根据 blink 状态切换光标显隐。

        画新光标前先恢复旧光标位置（从网格重画该格），
        否则光标移动后旧位置的色块残留（C 版的 oldx/oldy）。
        """
        cur = self.term.cursor

        # 恢复旧光标位置
        if self._old_cx != cur.x or self._old_cy != cur.y:
            self._restore_cell(self._old_cx, self._old_cy)

        # 画新光标（未隐藏时）
        if not (cur.state & 1):   # CURSOR_HIDE
            x = self.border_px + cur.x * self.char_w
            y = self.border_px + cur.y * self.char_h

            # 取当前光标位置的 glyph
            g = self.term.lines[cur.y][cur.x]
            is_set = bool(g.state & GLYPH_SET)
            ch = g.c if is_set else ' '

            # 宽字符光标：按字符实际宽度绘制
            ch_w = char_width(ch)
            width = max(1, ch_w) if is_set else 1

            # reverse 感知：光标块颜色用"当前显示色"（交换后的前景）
            # 而非原始 fg——否则光标在 vim 高亮行上颜色错乱
            reverse = bool(g.mode & ATTR_REVERSE)
            disp_fg = g.bg if reverse else g.fg
            disp_bg = g.fg if reverse else g.bg

            # 反转色：背景=显示前景色，字符用显示背景色（否则同色不可见）
            if self._cursor_blink:
                bg_c = self._color_of(disp_fg if is_set else DEFAULT_CS)
            else:
                bg_c = self._color_of(DEFAULT_CS)

            self._draw.rectangle(
                (x, y, x + self.char_w * width - 1,
                 y + self.char_h - 1),
                fill=bg_c)

            # 画字符（反转时用显示背景色，保证可见）
            if ch != ' ' and ch != '\0':
                char_fg = disp_bg if (self._cursor_blink and is_set) \
                    else disp_fg
                img = self._get_glyph_image(ch, char_fg, False, width)
                if img:
                    self._img.paste(img, (x, y), img)

        self._old_cx, self._old_cy = cur.x, cur.y

    def _restore_cell(self, x: int, y: int):
        """从网格重画指定格子（用于恢复旧光标位置）。

        宽字符感知：光标块在宽字符上占 2 列（含尾格），恢复区域必须
        同样宽，否则右半列残留光标块色块（残影）。
        """
        if not (0 <= x < self.term.col and 0 <= y < self.term.row):
            return
        g = self.term.lines[y][x]
        is_tail = bool(g.state & GLYPH_WIDE_TAIL)

        # 光标在宽字符尾格时，回退到头格一并恢复
        if is_tail and x > 0:
            x -= 1
            g = self.term.lines[y][x]

        is_set = bool(g.state & GLYPH_SET)
        w = max(1, char_width(g.c)) if is_set else 1    # 字形宽度
        span_w = 2 if is_tail else w                    # 背景宽度（对齐光标块）
        px = self.border_px + x * self.char_w
        py = self.border_px + y * self.char_h

        # 背景（reverse 时交换：背景画 fg 色）——
        # 必须与 _draw_dirty_line 一致，否则光标恢复和绘制不同色
        reverse = bool(g.mode & ATTR_REVERSE)
        bg_idx = (g.fg if reverse else g.bg) if is_set else DEFAULT_BG
        bg_c = self._color_of(bg_idx)
        self._draw.rectangle(
            (px, py, px + self.char_w * span_w - 1,
             py + self.char_h - 1), fill=bg_c)

        # 字符（含宽字符）——reverse + bold 亮化与 _draw_glyph_at 一致
        # （真彩色元组不做亮化，与 _draw_glyph_at 的 isinstance 守卫一致）
        bold = bool(g.mode & ATTR_BOLD)
        fg_idx = g.bg if reverse else g.fg
        if bold and isinstance(fg_idx, int):
            if 0 <= fg_idx <= 7:
                fg_idx += 8
            elif 16 <= fg_idx <= 195:
                fg_idx += 36
            elif 232 <= fg_idx <= 251:
                fg_idx += 4

        if is_set and g.c not in (' ', ''):
            img = self._get_glyph_image(g.c, fg_idx, bold, w)
            if img:
                self._img.paste(img, (px, py), img)

        # 下划线（基线下方 1px）——与 _draw_glyph_at 一致；
        # 原版 x_draws 恢复旧光标时同样画下划线
        if is_set and g.c not in (' ', '') and (g.mode & ATTR_UNDERLINE):
            ul_w = self.char_w * w
            font = self._pil_font_bold if bold else self._pil_font
            if font is not None:
                _, descent = font.getmetrics()
                ul_y = py + self.char_h - descent + 1
            else:
                ul_y = py + self.char_h - 2
            self._draw.line(
                (px, ul_y, px + ul_w - 1, ul_y),
                fill=self._color_of(fg_idx), width=1)

    def toggle_blink(self):
        """切换 blink 状态。调用方应每 500ms 调用一次。"""
        self._cursor_blink = not self._cursor_blink

    # ══════════════════════════════════════════════════════
    # Scroll 指示器
    # ══════════════════════════════════════════════════════

    def _draw_scroll_indicator(self):
        """在右上角绘制 [N]^ 滚动指示器。"""
        text = f"[{self.term.scroll_offset}]^"
        px = self.width - self.border_px - len(text) * self.char_w - 4
        py = self.border_px

        # 背景
        bg = self._color_of(DEFAULT_CS)
        self._draw.rectangle(
            (px - 2, py - 1,
             px + len(text) * self.char_w + 4,
             py + self.char_h + 2),
            fill=bg)

        # 逐个字符渲染
        for i, ch in enumerate(text):
            img = self._get_glyph_image(ch, DEFAULT_BG, False)
            if img:
                self._img.paste(img, (px + i * self.char_w, py), img)

    # ══════════════════════════════════════════════════════
    # 上传纹理
    # ══════════════════════════════════════════════════════

    def _flush(self, dirty_row_top: int = 0, dirty_row_bot: int = -1):
        """PIL 画布 → RGBA bytes → SDL_UpdateTexture → RenderCopy → Present

        dirty_row_top/bot: 终端行号范围，只更新该像素区域。
        无脏行（只有光标 blink）时区域很小，大幅降低上传开销。
        """
        # 旋转时区域变换复杂，回退全屏上传
        rotated = self.opt_rotate != 0
        if rotated:
            dirty_row_top, dirty_row_bot = 0, -1

        # 计算像素区域
        if dirty_row_bot >= dirty_row_top:
            y0 = self.border_px + max(0, dirty_row_top) * self.char_h
            y1 = min(self.height, self.border_px +
                     (dirty_row_bot + 1) * self.char_h)
            y0 = max(0, y0)
        else:
            y0, y1 = 0, self.height

        if rotated:
            if self.opt_rotate == 90:
                display = self._img.rotate(90, expand=True)
            elif self.opt_rotate == 270:
                display = self._img.rotate(270, expand=True)
            else:
                display = self._img.rotate(180, expand=False)
            dw, dh = display.size
            rgba = display.tobytes()
            if dw != self._tex_w or dh != self._tex_h:
                self._recreate_texture(dw, dh)
            sdl2.SDL_UpdateTexture(self._texture, None, rgba, dw * 4)
        else:
            # 局部区域上传：只转脏区域的像素
            dw, dh = self.width, self.height
            if dw != self._tex_w or dh != self._tex_h:
                self._recreate_texture(dw, dh)
            if y1 > y0:
                crop = self._img.crop((0, y0, dw, y1))
                rgba = crop.tobytes()
                rect = sdl2.SDL_Rect(0, y0, dw, y1 - y0)
                sdl2.SDL_UpdateTexture(self._texture, rect, rgba, dw * 4)

        sdl2.SDL_RenderClear(self.sdl_renderer)
        sdl2.SDL_RenderCopy(self.sdl_renderer, self._texture, None, None)
        sdl2.SDL_RenderPresent(self.sdl_renderer)

    # ══════════════════════════════════════════════════════
    # resize / shutdown
    # ══════════════════════════════════════════════════════

    def resize(self, width: int, height: int):
        """窗口尺寸变化时重建资源。"""
        self.width = width
        self.height = height
        self._img = Image.new("RGBA", (width, height), color=(0, 0, 0, 255))
        self._draw = ImageDraw.Draw(self._img)
        self._recreate_texture(width, height)

    def shutdown(self):
        """清理纹理。"""
        if self._texture:
            sdl2.SDL_DestroyTexture(self._texture)
            self._texture = None
        self._glyph_cache.clear()

    # ══════════════════════════════════════════════════════
    # 辅助
    # ══════════════════════════════════════════════════════

    def _color_of(self, idx) -> tuple:
        """颜色（调色板索引 int 或真彩色 (R,G,B) 元组）→ RGBA tuple。"""
        if isinstance(idx, tuple):
            # 真彩色 — 直接使用，不经过 COLORMAP
            r, g, b = idx
            return (r, g, b, 255)
        if idx < 0 or idx >= len(COLORMAP):
            idx = DEFAULT_FG
        r, g, b = COLORMAP[idx]
        return (r, g, b, 255)

    @property
    def stats(self) -> dict:
        """缓存统计（调试用）。"""
        return {
            "cache_size": len(self._glyph_cache),
            "cache_max": self._glyph_cache_max,
            "hits": self._glyph_cache_hits,
            "misses": self._glyph_cache_misses,
        }
