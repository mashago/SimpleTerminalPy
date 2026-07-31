"""SimpleTerminalPy — 渲染引擎（PIL + PySDL2）。

对应 C 版 main.c 的 draw_region(), x_draws(), draw_scrollbar(),
update_render() 以及 font.c 的全部渲染逻辑。

遵循方案文档的设计：PIL 先行，对外只暴露 4 个方法，
内部可切换到 SDL blit 而不影响其他模块。
"""

import ctypes
import os
from collections import OrderedDict

import sdl2
from PIL import Image, ImageDraw, ImageFont

from terminal import (
    Term, Glyph, GLYPH_SET, GLYPH_WIDE_TAIL,
    ATTR_BOLD, ATTR_REVERSE, ATTR_UNDERLINE, ATTR_ITALIC, ATTR_BLINK,
)
from config import COLORMAP, DEFAULT_FG, DEFAULT_BG, DEFAULT_CS, DEFAULT_UCS
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
                 opt_rotate: int = 0,
                 opt_scale: float = 1.0):
        self.term = term
        self.sdl_renderer = renderer
        self.width = width
        self.height = height
        self.char_w = char_w
        self.char_h = char_h
        self.border_px = border_px
        self.opt_rotate = opt_rotate
        self.opt_scale = opt_scale

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
            fallbacks = [
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
        """
        term = self.term

        # 只处理脏行
        for y in range(term.row):
            if not term.dirty[y]:
                continue
            term.dirty[y] = False
            self._draw_dirty_line(y)

        # 光标（仅非滚动状态）
        if term.scroll_offset == 0 and \
           not (term.cursor.state & 1):  # CURSOR_HIDE
            self._draw_cursor()

        # scrollbar 指示器
        if term.scroll_offset > 0:
            self._draw_scroll_indicator()

        # 清空 terminal grid 下方的区域（OSK 旧画面残留）
        term_bottom = self.border_px + term.row * self.char_h
        if term_bottom < self.height:
            self._draw.rectangle(
                (0, term_bottom, self.width, self.height),
                fill=self._color_of(DEFAULT_BG))

        # 合成 OSK（顶部或底部）
        if osk_surface:
            osk_h = osk_surface.height
            if osk_top:
                osk_y = 0
            else:
                osk_y = self.height - osk_h
            self._img.paste(osk_surface, (0, osk_y), osk_surface)

        # 上传纹理
        self._flush()

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
                line = term.lines[y]
        else:
            screen_y = y - term.scroll_offset
            if 0 <= screen_y < term.row:
                line = term.lines[screen_y]
            else:
                return

        # 先清空整行背景（否则残留上一帧的画面）
        px_clear = self.border_px
        py_clear = self.border_px + y * self.char_h
        pw_clear = term.col * self.char_w
        self._draw.rectangle(
            (px_clear, py_clear, px_clear + pw_clear, py_clear + self.char_h),
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

            # 确定宽度
            ch_w = char_width(glyph.c)
            display_w = 1 if ch_w <= 1 else ch_w

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

            # 画背景
            bg_color = self._color_of(base_attr[1])
            px = self.border_px + batch_start * self.char_w
            py = self.border_px + y * self.char_h
            pw = (batch_end - batch_start) * self.char_w

            self._draw.rectangle(
                (px, py, px + pw, py + self.char_h), fill=bg_color)

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

        fg_idx = glyph.fg
        bold = bool(glyph.mode & ATTR_BOLD)
        underline = bool(glyph.mode & ATTR_UNDERLINE)

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

            # 反转色：背景=原前景色，字符用原背景色（否则同色不可见）
            if self._cursor_blink:
                bg_c = self._color_of(g.fg if is_set else DEFAULT_CS)
            else:
                bg_c = self._color_of(DEFAULT_CS)

            self._draw.rectangle(
                (x, y, x + self.char_w * width, y + self.char_h),
                fill=bg_c)

            # 画字符（反转时用原背景色，保证可见）
            if ch != ' ' and ch != '\0':
                char_fg = g.bg if (self._cursor_blink and is_set) else g.fg
                img = self._get_glyph_image(ch, char_fg, False, width)
                if img:
                    self._img.paste(img, (x, y), img)

        self._old_cx, self._old_cy = cur.x, cur.y

    def _restore_cell(self, x: int, y: int):
        """从网格重画指定格子（用于恢复旧光标位置）。"""
        if not (0 <= x < self.term.col and 0 <= y < self.term.row):
            return
        g = self.term.lines[y][x]
        px = self.border_px + x * self.char_w
        py = self.border_px + y * self.char_h

        # 背景
        bg_c = self._color_of(g.bg if g.state & GLYPH_SET else DEFAULT_BG)
        self._draw.rectangle(
            (px, py, px + self.char_w, py + self.char_h), fill=bg_c)

        # 字符（含宽字符）
        if g.state & GLYPH_SET and g.c not in (' ', ''):
            w = max(1, char_width(g.c))
            bold = bool(g.mode & ATTR_BOLD)
            img = self._get_glyph_image(g.c, g.fg, bold, w)
            if img:
                self._img.paste(img, (px, py), img)

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
        fg = self._color_of(DEFAULT_BG)
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

    def _flush(self):
        """PIL 画布 → RGBA bytes → SDL_UpdateTexture → RenderCopy → Present"""
        # 旋转处理
        if self.opt_rotate == 90:
            display = self._img.rotate(90, expand=True)
        elif self.opt_rotate == 270:
            display = self._img.rotate(270, expand=True)
        elif self.opt_rotate == 180:
            display = self._img.rotate(180, expand=False)
        else:
            display = self._img

        dw, dh = display.size
        rgba = display.tobytes()

        # 如果尺寸变化，重建纹理
        if dw != self._tex_w or dh != self._tex_h:
            self._recreate_texture(dw, dh)

        sdl2.SDL_UpdateTexture(self._texture, None, rgba, dw * 4)
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

    def _color_of(self, idx: int) -> tuple:
        """颜色索引 → RGBA tuple。"""
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
