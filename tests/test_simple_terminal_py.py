#!/usr/bin/env python3
"""SimpleTerminalPy 测试套件。

运行: python3 tests/test_simple_terminal_py.py
      （或 python3 -m unittest tests.test_simple_terminal_py -v）

覆盖:
  - VT100 解析（基本字符/CSI/SGR/滚动/alt screen/重置）
  - 宽字符（CJK 双列）
  - 按键校准逻辑
  - InputHandler (type, value, device) 解析与设备隔离
  - OSK 渲染缓存与特殊键输出
  - key_map.json 路径（源码/frozen/只读回退）
  - 字符宽度
  - 拼音输入法（pinyin_ime：前缀匹配/频率排序/分页）
  - OSK 拼音模式（🌐 切换/组合/选字/智能退格/翻页/布局锁定）
  - 括号粘贴（DEC 2004：模式位 + 200~/201~ 包裹）
  - 真彩色（38;2;R;G;B）解析与渲染（粗体不亮化）
  - PTY 增量 UTF-8 解码（跨 read 块重组）
  - 渲染器光标恢复（宽字符残影 / 下划线 / 格子矩形 1px 溢出）
"""

import json
import os
import sys
import tempfile
import unittest

# 无头渲染测试需要（必须在 sdl2.SDL_Init 之前设置）
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import sdl2
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from terminal import Term, GLYPH_SET, GLYPH_WIDE_TAIL, MODE_BRACKETPASTE
from vt100 import Vt100
from wcwidth import char_width
from config import KBD_DEVICE, DEFAULT_FG, COLORMAP
from key_calibrate import KeyCalibrator, load_keymap, KEY_GUIDE_ROWS
from main import bracket_paste
from input_handler import InputHandler
from osk import OSK, ROW_PINYIN, LAYOUTS
from pty_handler import PtyHandler
from pinyin_ime import PinyinIME
from renderer import Renderer


# ── VT100 解析 ──────────────────────────────────────────

class TestVt100(unittest.TestCase):
    def setUp(self):
        self.t = Term(80, 24)
        self.vt = Vt100(self.t)
        self.vt.tty_write = lambda s: None

    def test_basic_chars(self):
        for ch in "Hello":
            self.vt.t_putc(ch)
        self.assertEqual([g.c for g in self.t.lines[0][:5]],
                         ['H', 'e', 'l', 'l', 'o'])
        self.assertEqual((self.t.cursor.x, self.t.cursor.y), (5, 0))

    def test_cr_lf(self):
        self.vt.t_putc('\r')
        self.assertEqual(self.t.cursor.x, 0)
        self.vt.t_putc('\n')
        self.assertEqual(self.t.cursor.y, 1)

    def test_csi_clear_screen(self):
        for ch in '\033[2J':
            self.vt.t_putc(ch)
        # ED 2J 只清内容，不动光标
        self.assertEqual((self.t.cursor.x, self.t.cursor.y), (0, 0))

    def test_csi_cursor_position(self):
        for ch in '\033[10;5H':
            self.vt.t_putc(ch)
        self.assertEqual((self.t.cursor.x, self.t.cursor.y), (4, 9))

    def test_sgr_colors(self):
        for ch in '\033[31m':
            self.vt.t_putc(ch)
        self.assertEqual(self.t.cursor.attr.fg, 1)  # red

    def test_sgr_bold(self):
        for ch in '\033[1m':
            self.vt.t_putc(ch)
        self.assertTrue(self.t.cursor.attr.mode & 4)  # ATTR_BOLD

    def test_alt_screen(self):
        for ch in '\033[?1049h':
            self.vt.t_putc(ch)
        self.assertTrue(self.t.mode & 8)  # MODE_ALTSCREEN
        for ch in '\033[?1049l':
            self.vt.t_putc(ch)
        self.assertFalse(self.t.mode & 8)

    def test_scrollback(self):
        for _ in range(30):   # 超过屏幕高度，触发滚动
            self.vt.t_putc('\n')
        self.assertGreater(len(self.t.scrollback), 0)

    def test_t_reset(self):
        """回归测试：TAB_SPACES 未导入曾导致 NameError 崩溃。"""
        self.vt.t_reset()   # 之前这里崩溃

    def test_ris_escape(self):
        """ESC c (RIS) 触发 t_reset。"""
        for ch in '\033c':
            self.vt.t_putc(ch)

    def test_sgr_empty_param_resets(self):
        """ESC[m（无参数 SGR 0）应重置属性。

        回归测试：vim 大量使用 \x1b[m 简写，曾因空参数解析为
        narg=0 而空转，导致白底属性残留（vim 可视选择/status line）。
        """
        for ch in '\033[47m':   # 白背景
            self.vt.t_putc(ch)
        self.vt.t_putc('X')
        self.assertEqual(self.t.lines[0][0].bg, 7)
        for ch in '\033[m':     # SGR 0 简写 → 重置
            self.vt.t_putc(ch)
        self.vt.t_putc('Y')
        self.assertEqual(self.t.lines[0][1].bg, 260)   # 默认背景

    def test_decsgn_gfx_chars(self):
        """DEC Special Graphics (ESC(0) 完整映射。"""
        for ch in '\033(0lqwqk':
            self.vt.t_putc(ch)
        line = ''.join(g.c for g in self.t.lines[0][:5])
        self.assertEqual(line, '┌─┬─┐')


# ── 宽字符 ──────────────────────────────────────────────

class TestWideChars(unittest.TestCase):
    def test_cjk_double_width(self):
        self.t = Term(80, 24)
        self.vt = Vt100(self.t)
        self.vt.tty_write = lambda s: None
        for ch in '你好':
            self.vt.t_putc(ch)
        line = self.t.lines[0]
        # 你: col0 主字符, col1 WIDE_TAIL
        self.assertEqual(line[0].c, '你')
        self.assertTrue(line[0].state & GLYPH_SET)
        self.assertTrue(line[1].state & GLYPH_WIDE_TAIL)
        # 好: col2 主字符, col3 WIDE_TAIL
        self.assertEqual(line[2].c, '好')
        self.assertTrue(line[3].state & GLYPH_WIDE_TAIL)
        # 光标前进 4 列
        self.assertEqual(self.t.cursor.x, 4)

    def test_wide_char_at_line_end_wraps(self):
        """行尾只剩 1 列时遇到宽字符应换行。"""
        t = Term(5, 3)
        vt = Vt100(t)
        vt.tty_write = lambda s: None
        for ch in 'ABCD':     # 光标到 col4（只剩 1 列）
            vt.t_putc(ch)
        vt.t_putc('中')        # 宽字符 → 换行
        self.assertEqual(t.cursor.y, 1)

    def test_overwrite_wide_tail_clears_flag(self):
        """普通字符覆盖宽字符尾格时必须清除 WIDE_TAIL 标记。

        （tmux 重绘覆盖宽字符区域后文字交替消失的根因——
        残留标记会让 renderer 跳过该格显示为空白）
        """
        t = Term(80, 24)
        vt = Vt100(t)
        vt.tty_write = lambda s: None
        for ch in '你你你你':   # heads 0,2,4,6 / tails 1,3,5,7
            vt.t_putc(ch)
        vt.t_move_to(7, 0)      # 覆盖 col7（'你' 在 6-7 的尾格）
        vt.t_putc('X')
        g = t.lines[0][7]
        self.assertEqual(g.c, 'X')
        self.assertTrue(g.state & GLYPH_SET)
        self.assertFalse(g.state & GLYPH_WIDE_TAIL)


# ── 真彩色（38;2;R;G;B） ────────────────────────────────

class TestTrueColor(unittest.TestCase):
    def setUp(self):
        self.t = Term(80, 24)
        self.vt = Vt100(self.t)
        self.vt.tty_write = lambda s: None

    def _feed(self, s: str):
        for ch in s:
            self.vt.t_putc(ch)

    def test_truecolor_fg(self):
        self._feed("\x1b[38;2;255;0;0m")
        self.assertEqual(self.t.cursor.attr.fg, (255, 0, 0))

    def test_truecolor_bg(self):
        self._feed("\x1b[48;2;0;128;255m")
        self.assertEqual(self.t.cursor.attr.bg, (0, 128, 255))

    def test_truecolor_invalid_component_ignored(self):
        # 任一分量越界则整条忽略，保持原色
        self._feed("\x1b[38;2;300;0;0m")
        self.assertEqual(self.t.cursor.attr.fg, DEFAULT_FG)
        self.assertIsInstance(self.t.cursor.attr.fg, int)

    def test_truecolor_reset_by_sgr0(self):
        self._feed("\x1b[38;2;1;2;3m\x1b[0m")
        self.assertEqual(self.t.cursor.attr.fg, DEFAULT_FG)
        self.assertIsInstance(self.t.cursor.attr.fg, int)

    def test_256color_still_palette_index(self):
        # 38;5 仍走调色板索引，不受影响
        self._feed("\x1b[38;5;196m")
        self.assertEqual(self.t.cursor.attr.fg, 196)
        self.assertIsInstance(self.t.cursor.attr.fg, int)

    def test_truecolor_with_bold(self):
        # 粗体 + 真彩色：fg 保持元组（渲染时不亮化）
        self._feed("\x1b[1;38;2;10;200;30m")
        self.assertEqual(self.t.cursor.attr.fg, (10, 200, 30))
        self.assertTrue(self.t.cursor.attr.mode & 4)   # ATTR_BOLD


# ── 拼音输入法（pinyin_ime.py） ─────────────────────────

# 合成小字典（真实字典由 generate_pinyin_dict.py 生成，测试用临时表）
TEST_PINYIN_DICT = {
    "zhong": [["中", 7000], ["种", 3000], ["重", 2000]],
    "zhi": [["只", 900], ["之", 800], ["直", 700], ["知", 600],
            ["治", 500], ["志", 400]],
    "ni": [["你", 6000], ["尼", 500]],
    "hao": [["好", 5000], ["号", 400]],
}


class TestPinyinIme(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(TEST_PINYIN_DICT, tmp, ensure_ascii=False)
        tmp.close()
        self._path = tmp.name
        self.ime = PinyinIME(self._path)

    def tearDown(self):
        os.unlink(self._path)

    def test_lazy_load(self):
        self.assertFalse(self.ime.loaded)
        self.ime.candidates("zh")     # 查询时懒加载
        self.assertTrue(self.ime.loaded)

    def test_prefix_match_and_ordering(self):
        # "zh" 前缀命中 zhong + zhi 全部条目，按频率降序
        self.assertEqual(
            self.ime.candidates("zh"),
            ["中", "种", "重", "只", "之", "直", "知", "治", "志"])

    def test_exact_pinyin_ordering(self):
        self.assertEqual(self.ime.candidates("ni"), ["你", "尼"])

    def test_paging(self):
        # 9 个候选 → 2 页（5+4）
        page0, total = self.ime.page("zh", 0)
        self.assertEqual(total, 2)
        self.assertEqual(page0, ["中", "种", "重", "只", "之"])
        page1, _ = self.ime.page("zh", 1)
        self.assertEqual(page1, ["直", "知", "治", "志"])

    def test_page_clamping(self):
        _, total = self.ime.page("zh", 0)
        page_hi, total_hi = self.ime.page("zh", 99)   # 越界夹到最后一页
        self.assertEqual(total_hi, total)
        self.assertEqual(page_hi, ["直", "知", "治", "志"])
        page_lo, _ = self.ime.page("zh", -5)
        self.assertEqual(page_lo, ["中", "种", "重", "只", "之"])

    def test_empty_and_no_match(self):
        self.assertEqual(self.ime.candidates(""), [])
        self.assertEqual(self.ime.candidates("nihao"), [])
        self.assertEqual(self.ime.candidates("x"), [])   # 无 x 前缀

    def test_missing_dict_file(self):
        ime = PinyinIME("/nonexistent/pinyin_dict.json")
        self.assertEqual(ime.candidates("zh"), [])


# ── OSK 拼音输入模式 ───────────────────────────────────

class TestOSKPinyin(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(TEST_PINYIN_DICT, tmp, ensure_ascii=False)
        tmp.close()
        self._path = tmp.name
        self.osk = OSK(720, 480, dict_path=self._path)

    def tearDown(self):
        os.unlink(self._path)

    def _toggle_pinyin(self):
        """光标移到 🌐（ROW_LOWER 第 4 行第 1 列）并按 A。"""
        self.osk.row, self.osk.col = 3, 0
        self.osk.press_selected()

    def test_toggle_and_layout_lock(self):
        self.assertFalse(self.osk.pinyin_active)
        self._toggle_pinyin()
        self.assertTrue(self.osk.pinyin_active)
        self.assertEqual(self.osk.current_layout, ROW_PINYIN)
        # 拼音模式下切 symbols 无效（锁定 lower 变体）
        self.osk.mode = "symbols"
        self.assertEqual(self.osk.current_layout, ROW_PINYIN)
        self._toggle_pinyin()   # "EN" 键 → 退出
        self.assertFalse(self.osk.pinyin_active)
        self.assertEqual(self.osk.current_layout, LAYOUTS["symbols"])  # 复原

    def test_toggle_clears_modifier_locks(self):
        self.osk.ctrl = True
        self._toggle_pinyin()
        self.assertFalse(self.osk.ctrl)

    def test_letter_composition(self):
        self.osk.pinyin_active = True
        self.assertIsNone(self.osk.process_pinyin("z"))
        self.assertIsNone(self.osk.process_pinyin("h"))
        self.assertEqual(self.osk.pinyin_buf, "zh")

    def _compose(self, letters: str):
        """逐键输入字母（模拟逐键路由）。"""
        for ch in letters:
            self.assertIsNone(self.osk.process_pinyin(ch))

    def test_select_candidate(self):
        self.osk.pinyin_active = True
        self._compose("zh")
        out = self.osk.process_pinyin("1")
        self.assertEqual(out, "中")     # zh 前缀频率最高
        self.assertEqual(self.osk.pinyin_buf, "")   # 选中后清空

    def test_digit_passthrough_when_empty(self):
        self.osk.pinyin_active = True
        self.assertEqual(self.osk.process_pinyin("5"), "5")   # 空→透传
        self.assertEqual(self.osk.process_pinyin("0"), "0")

    def test_digit_ignored_beyond_candidates(self):
        self.osk.pinyin_active = True
        self._compose("zh")             # 9 个候选（1-9 都可选）
        self.assertIsNone(self.osk.process_pinyin("0"))   # 第 10 个 → 忽略

    def test_smart_backspace(self):
        self.osk.pinyin_active = True
        self._compose("zh")
        self.assertIsNone(self.osk.process_pinyin("\177"))
        self.assertEqual(self.osk.pinyin_buf, "z")
        self.assertIsNone(self.osk.process_pinyin("\177"))
        self.assertEqual(self.osk.pinyin_buf, "")
        self.assertEqual(self.osk.process_pinyin("\177"), "\177")  # 空→透传

    def test_paging(self):
        self.osk.pinyin_active = True
        self._compose("zh")             # 9 候选 → 2 页
        self.assertIsNone(self.osk.process_pinyin("+"))
        self.assertEqual(self.osk.pinyin_page, 1)
        self.assertEqual(self.osk.process_pinyin("1"), "直")
        self.assertIsNone(self.osk.process_pinyin("-"))
        self.assertEqual(self.osk.pinyin_page, 0)

    def test_enter_commits_raw(self):
        self.osk.pinyin_active = True
        self._compose("nihao")          # 无匹配
        self.assertEqual(self.osk.process_pinyin("\r"), "nihao")
        self.assertEqual(self.osk.pinyin_buf, "")
        self.assertEqual(self.osk.process_pinyin("\r"), "\r")  # 空→透传

    def test_pass_through_control(self):
        self.osk.pinyin_active = True
        self.assertEqual(self.osk.process_pinyin("\x03"), "\x03")  # Ctrl+C

    def test_render_bar_height(self):
        h0 = self.osk.render().height
        self.osk.pinyin_active = True
        self.osk.invalidate()
        h1 = self.osk.render().height
        self.assertEqual(h1 - h0, 2 * (self.osk.key_h + self.osk.key_gap))


# ── 括号粘贴（DEC 2004） ───────────────────────────────

class TestBracketedPaste(unittest.TestCase):
    def setUp(self):
        self.t = Term(80, 24)
        self.vt = Vt100(self.t)
        self.vt.tty_write = lambda s: None

    def _feed(self, s: str):
        for ch in s:
            self.vt.t_putc(ch)

    def test_mode_set_and_clear(self):
        self.assertFalse(self.t.mode & MODE_BRACKETPASTE)
        self._feed("\x1b[?2004h")
        self.assertTrue(self.t.mode & MODE_BRACKETPASTE)
        self._feed("\x1b[?2004l")
        self.assertFalse(self.t.mode & MODE_BRACKETPASTE)

    def test_wrap_when_enabled(self):
        # vim/bash 开启 2004 时，粘贴内容用 200~/201~ 包裹
        self.assertEqual(
            bracket_paste("line1\n    line2", True),
            "\x1b[200~line1\n    line2\x1b[201~")

    def test_raw_when_disabled(self):
        # 未开启 2004 时原样写入
        self.assertEqual(bracket_paste("line1\nline2", False),
                         "line1\nline2")


# ── 按键校准 ────────────────────────────────────────────

class TestKeyCalibrate(unittest.TestCase):
    def _make_cal(self):
        cal = KeyCalibrator.__new__(KeyCalibrator)
        cal.keymap = {}
        cal.current_idx = 0
        cal.finished = False
        cal.aborted = False
        cal._pending = None
        cal._pending_time = 0.0
        cal._confirmed = False
        cal._ignore_until = 0.0
        # _assign_key 完成时会 _save()，给个临时路径
        fd, cal.keymap_path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(cal.keymap_path) and
                        os.remove(cal.keymap_path))
        return cal

    def test_assign_sequence(self):
        cal = self._make_cal()
        seq = [('hat', 1, 0), ('hat', 4, 0), ('hat', 8, 0), ('hat', 2, 0),
               ('btn', 0, 0), ('btn', 1, 0), ('key', 307, 1), ('btn', 3, 0),
               ('btn', 8, 0), ('btn', 13, 0), ('btn', 7, 0), ('btn', 6, 0),
               ('btn', 4, 0), ('btn', 14, 0), ('btn', 15, 0)]
        for ev in seq:
            cal._assign_key(ev, 1.0)
        self.assertTrue(cal.finished)
        self.assertEqual(len(cal.keymap), 15)
        self.assertEqual(cal.keymap['x'], ('key', 307, 1))

    def test_duplicate_rejected(self):
        cal = self._make_cal()
        cal._assign_key(('hat', 1, 0), 1.0)   # up
        idx = cal.current_idx
        cal._assign_key(('hat', 1, 0), 1.0)   # 重复 → 不推进
        self.assertEqual(cal.current_idx, idx)

    def test_release_must_match_pending(self):
        cal = self._make_cal()
        cal._on_press(('btn', 13, 0), 2.0)        # select down
        cal._on_release(('btn', 8, 0), 2.1)       # menu up（不匹配）→ 忽略
        self.assertEqual(cal.current_idx, 0)
        cal._on_release(('btn', 13, 0), 2.2)      # select up（匹配）→ 确认
        self.assertEqual(cal.current_idx, 1)

    def test_cooldown_blocks_dual_channel(self):
        """menu 双通道事件（btn+key）不应占用下一项。"""
        cal = self._make_cal()
        cal.current_idx = 8   # 从 menu 开始
        now = 100.0
        cal._on_press(('btn', 8, 0), now)
        cal._on_release(('btn', 8, 0), now + 0.05)   # menu 确认
        self.assertEqual(cal.current_idx, 9)
        # menu 第二通道在冷却期内 → 忽略
        cal._on_press(('key', 312, 1), now + 0.10)
        cal._on_release(('key', 312, 1), now + 0.15)
        self.assertEqual(cal.current_idx, 9)
        # 冷却后 select 正常
        cal._on_press(('btn', 13, 0), now + 1.0)
        cal._on_release(('btn', 13, 0), now + 1.05)
        self.assertEqual(cal.current_idx, 10)
        self.assertEqual(cal.keymap['select'], ('btn', 13, 0))

    def test_long_press_aborts(self):
        cal = self._make_cal()
        cal._on_press(('btn', 0, 0), 1.0)
        cal._on_release(('btn', 0, 0), 5.0)   # 按住 4 秒 → 放弃
        self.assertTrue(cal.aborted)

    def test_save_load_roundtrip(self):
        cal = self._make_cal()
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            cal.keymap_path = path
            cal.keymap = {'up': ('hat', 1, 0),
                          'x': ('key', 307, KBD_DEVICE)}
            cal._save()
            loaded = load_keymap(path)
            self.assertEqual(loaded, cal.keymap)
        finally:
            os.remove(path)

    def test_load_old_format(self):
        """旧格式（无 device）→ device 默认 -1。"""
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            with open(path, 'w') as f:
                json.dump({'keys': {'up': {'type': 'hat', 'value': 1}}}, f)
            self.assertEqual(load_keymap(path), {'up': ('hat', 1, -1)})
        finally:
            os.remove(path)

    def test_key_guide_rows(self):
        """KeyHelpScreen 表格：15 键 + 1 组合 = 16 行。"""
        self.assertEqual(len(KEY_GUIDE_ROWS), 16)
        self.assertEqual(KEY_GUIDE_ROWS[-1],
                         ('L1+R1', 'delete keymap', 'delete keymap'))


# ── InputHandler ────────────────────────────────────────

class TestInputHandler(unittest.TestCase):
    def setUp(self):
        self.keymap = {
            'up': ('hat', 1, 0), 'down': ('hat', 4, 0),
            'a': ('btn', 0, 0), 'x': ('key', 307, 1),
            'l1': ('btn', 6, 0), 'r1': ('btn', 4, 0),
        }
        self.ih = InputHandler(self.keymap)

    def test_resolve_non_key_ignores_device(self):
        self.assertEqual(self.ih.resolve('hat', 1, 0), 'up')
        self.assertEqual(self.ih.resolve('hat', 1, 999), 'up')
        self.assertEqual(self.ih.resolve('btn', 0, 0), 'a')

    def test_resolve_key_requires_device(self):
        self.assertEqual(self.ih.resolve('key', 307, 1), 'x')
        self.assertIsNone(self.ih.resolve('key', 307, 2))   # 蓝牙键盘隔离

    def test_is_down(self):
        self.ih.on_event('btn', 0, 0, True)
        self.assertTrue(self.ih.is_down('a'))
        self.ih.on_event('btn', 0, 0, False)
        self.assertFalse(self.ih.is_down('a'))

    def test_exit_combo(self):
        self.ih.on_event('btn', 6, 0, True)   # l1
        self.ih.on_event('btn', 4, 0, True)   # r1
        self.assertTrue(self.ih.is_down('l1'))
        self.assertTrue(self.ih.is_down('r1'))


# ── OSK ─────────────────────────────────────────────────

class TestOSK(unittest.TestCase):
    def setUp(self):
        self.osk = OSK(640, 480)

    def test_render_cache(self):
        img1 = self.osk.render()
        img2 = self.osk.render()
        self.assertIs(img1, img2)              # 静态命中缓存

    def test_cache_invalidated_on_move(self):
        img1 = self.osk.render()
        self.osk.move_right()
        img2 = self.osk.render()
        self.assertIsNot(img1, img2)

    def test_special_keys_output(self):
        """⌫/↵/␣ 应输出控制序列而非显示符号（曾输出方框）。"""
        cases = [
            (0, 11, '\x7f'),   # ⌫ Backspace
            (1, 11, '\r'),     # ↵ Enter
            (2, 11, ' '),      # ␣ Space
        ]
        for row, col, expected in cases:
            self.osk.row, self.osk.col = row, col
            self.assertEqual(self.osk.press_selected(), expected)

    def test_arrow_output(self):
        self.osk.mode = 'symbols'
        self.osk.row, self.osk.col = 2, 0      # ↑
        self.assertEqual(self.osk.press_selected(), '\x1b[A')

    def test_shift_down_up(self):
        img_lower = self.osk.render()
        self.osk.shift_down()                   # L1 按下
        self.assertEqual(self.osk.mode, 'upper')
        img_upper = self.osk.render()
        self.assertIsNot(img_lower, img_upper)  # 缓存失效
        self.osk.shift_up()
        self.assertEqual(self.osk.mode, 'lower')


# ── 键盘 Ctrl 组合键（_on_keydown） ──────────────────────

class TestCtrlKeys(unittest.TestCase):
    """覆盖 _on_keydown 的 Ctrl 组合路径。

    防回归：曾因漏写 self. 前缀导致 Ctrl+\\ 触发 NameError 崩溃
    （pyflakes 能查到，但测试也应覆盖）。
    """

    class _FakePty:
        def __init__(self):
            self.written = []
        def write(self, s):
            self.written.append(s)

    def _make_app(self):
        import main as main_mod
        app = main_mod.SDLApp.__new__(main_mod.SDLApp)
        app.pty = self._FakePty()
        return app

    @staticmethod
    def _make_key(sym, mod):
        """构造模拟 SDL_KeyboardEvent.key。"""
        class KS:
            def __init__(self, s, m):
                self.sym = s
                self.mod = m
        class K:
            def __init__(self, s, m):
                self.keysym = KS(s, m)
        return K(sym, mod)

    def test_ctrl_backslash(self):
        """tmux prefix: Ctrl+\\ → \\x1c。曾 NameError 崩溃。"""
        app = self._make_app()
        app._on_keydown(self._make_key(sdl2.SDLK_BACKSLASH,
                                       sdl2.KMOD_LCTRL))
        self.assertEqual(app.pty.written, ['\x1c'])

    def test_ctrl_bracket(self):
        app = self._make_app()
        app._on_keydown(self._make_key(sdl2.SDLK_LEFTBRACKET,
                                       sdl2.KMOD_LCTRL))
        self.assertEqual(app.pty.written, ['\x1b'])

    def test_ctrl_space(self):
        app = self._make_app()
        app._on_keydown(self._make_key(sdl2.SDLK_SPACE,
                                       sdl2.KMOD_LCTRL))
        self.assertEqual(app.pty.written, ['\x00'])

    def test_ctrl_c(self):
        """Ctrl+C → \\x03。"""
        app = self._make_app()
        app._on_keydown(self._make_key(sdl2.SDLK_c,
                                       sdl2.KMOD_LCTRL))
        self.assertEqual(app.pty.written, ['\x03'])

    def test_plain_c_no_ctrl(self):
        """无 Ctrl 的普通键：KEYDOWN 路径不发送（走 TEXTINPUT）。"""
        app = self._make_app()
        app._on_keydown(self._make_key(sdl2.SDLK_c, 0))
        self.assertEqual(app.pty.written, [])

    def test_all_ctrl_symbol_map(self):
        """映射表所有条目都能正常处理（防漏 self. 类属性错误）。"""
        import main as main_mod
        app = self._make_app()
        for sym in main_mod.SDLApp._CTRL_SYMBOL_MAP:
            app.pty.written.clear()
            app._on_keydown(self._make_key(sym, sdl2.KMOD_LCTRL))
            self.assertEqual(len(app.pty.written), 1,
                             f'sym={sym} 未发送')


# ── key_map.json 路径 ───────────────────────────────────

class TestKeymapPath(unittest.TestCase):
    def test_source_mode(self):
        import main
        # 源码模式: 程序目录
        self.assertIn('SimpleTerminalPy/key_map.json', main.KEYMAP_PATH)

    def test_frozen_writable(self):
        """frozen + 可写目录 → 可执行文件旁。"""
        import subprocess
        script = '''
import sys, os
os.makedirs('/tmp/stp_test_bin', exist_ok=True)
sys.frozen = True
sys.executable = '/tmp/stp_test_bin/SimpleTerminalPy'
sys.path.insert(0, '/root/workspace/my_terminal/SimpleTerminalPy')
import main
assert main.KEYMAP_PATH == '/tmp/stp_test_bin/key_map.json', main.KEYMAP_PATH
print('OK')
'''
        r = subprocess.run([sys.executable, '-c', script],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        os.system('rm -rf /tmp/stp_test_bin')

    def test_frozen_readonly_fallback(self):
        """frozen + 只读目录 → 回退 ~/.simple_terminal_py。"""
        import subprocess
        script = '''
import sys, os
sys.frozen = True
sys.executable = '/proc/fake/SimpleTerminalPy'
sys.path.insert(0, '/root/workspace/my_terminal/SimpleTerminalPy')
import main
assert main.KEYMAP_PATH.startswith(os.path.expanduser('~/.simple_terminal_py')), main.KEYMAP_PATH
print('OK')
'''
        r = subprocess.run([sys.executable, '-c', script],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)


# ── 字符宽度 ────────────────────────────────────────────

class TestWcwidth(unittest.TestCase):
    def test_widths(self):
        cases = [
            ('A', 1), ('1', 1), (' ', 1),
            ('\0', 0), ('\n', 0), ('\t', 0),
            ('中', 2), ('文', 2), ('語', 2),
            ('ａ', 2), ('０', 2),          # 全角
            ('┌', 1), ('─', 1),           # box-drawing ambiguous
            ('🎉', 2),                     # emoji wide
        ]
        for ch, expected in cases:
            self.assertEqual(char_width(ch), expected, f'{ch!r}')


# ── PTY 增量 UTF-8 解码（跨 read 块重组） ──

class TestPtyHandlerUtf8(unittest.TestCase):
    """增量 UTF-8 解码：跨 4096 字节 read 块的多字节字符必须完整重组
    （对应 C 版 tty_read 的 static buf + memmove 残字节方案）。"""

    def _feed(self, p: PtyHandler, chunks: list[bytes]) -> str:
        return ''.join(p._decode(c) for c in chunks)

    def test_split_3byte_char_across_chunks(self):
        # '你' = E4 BD A0 — 逐字节喂入（模拟极端跨块）
        p = PtyHandler()
        self.assertEqual(self._feed(p, [b'\xe4', b'\xbd', b'\xa0']), '你')

    def test_split_at_4096_boundary(self):
        # 4095 个 ASCII 后跟半个汉字，下一块接上剩余字节
        p = PtyHandler()
        h = '好'.encode('utf-8')
        out = self._feed(p, [b'a' * 4095 + h[:1], h[1:]])
        self.assertEqual(out, 'a' * 4095 + '好')

    def test_split_4byte_char(self):
        # emoji '🎉' = F0 9F 8E 89 — 拆成 3 块
        p = PtyHandler()
        h = '🎉'.encode('utf-8')
        self.assertEqual(self._feed(p, [h[:1], h[1:3], h[3:]]), '🎉')

    def test_mixed_valid_and_split(self):
        # 有效字符 + 跨块字符 + 有效字符
        p = PtyHandler()
        h = '你'.encode('utf-8')
        out = self._feed(p, [b'ab', h[:2], h[2:], b'cd'])
        self.assertEqual(out, 'ab你cd')

    def test_invalid_byte_replaced(self):
        p = PtyHandler()
        self.assertEqual(p._decode(b'\xff'), '�')
        # 无效字节不污染解码器状态
        self.assertEqual(p._decode('中'.encode('utf-8')), '中')


# ── 渲染器（SDL dummy 无头渲染，逐像素对比） ──

W, H = 320, 160
CW, CH = 8, 16
BORDER = 2

CJK_LINE = "你好世界 abcd\n"   # 宽字符 4 个 + 空格 + abcd，光标终点 (13, 0)


class _RendererTestBase(unittest.TestCase):
    """SDL dummy 无头渲染测试基类（窗口/renderer 生命周期 + 快照）。"""

    def _assert_cell_has_pixel(self, img: bytes, col: int, row: int,
                               color: tuple) -> None:
        """断言格子 (col, row) 区域内存在指定 RGBA 像素。"""
        canvas = Image.frombytes("RGBA", (W, H), img)
        x0 = BORDER + col * CW
        y0 = BORDER + row * CH
        for y in range(y0, y0 + CH):
            for x in range(x0, x0 + CW):
                if canvas.getpixel((x, y)) == color:
                    return
        self.fail(f"cell({col},{row}) 中未找到像素 {color}")

    def setUp(self):
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO) < 0:
            self.fail(f"SDL_Init: {sdl2.SDL_GetError()}")
        self._win = sdl2.SDL_CreateWindow(b"t", 0, 0, W, H, 0)
        self._ren = sdl2.SDL_CreateRenderer(
            self._win, -1, sdl2.SDL_RENDERER_SOFTWARE)

    def tearDown(self):
        if self._ren:
            sdl2.SDL_DestroyRenderer(self._ren)
        if self._win:
            sdl2.SDL_DestroyWindow(self._win)
        sdl2.SDL_Quit()

    def _snapshot(self, content: str, path: list) -> bytes:
        """在全新 renderer 上按光标路径绘制，返回画布字节。"""
        term = Term(40, 10)
        vt = Vt100(term)
        vt.tty_write = lambda s: None
        r = Renderer(term, self._ren, W, H, char_w=CW, char_h=CH,
                     border_px=BORDER, font_size=12)
        try:
            for ch in content:
                vt.t_putc(ch)
            for x, y in path:
                vt.t_move_to(x, y)
                r.draw_frame()
            return r._img.tobytes()
        finally:
            r.shutdown()


class TestRendererCursorRestore(_RendererTestBase):
    """光标移走后，画面必须与"光标从未在该位置停留"的参考画面一致。

    方法：同一内容在两个独立 renderer 上绘制——参考画面光标直接
    移到最终位置；场景画面光标先在中间格停留再移过去。两者逐像素
    比较，不一致说明留下了残影/抹除了内容。
    """

    def _assert_restore_clean(self, content: str, stops: list,
                              final: tuple, label: str):
        ref = self._snapshot(content, [final])
        img = self._snapshot(content, list(stops) + [final])
        if ref == img:
            return
        # 失败时输出差异摘要（避免 unittest 打印整个画布字节）
        a = Image.frombytes("RGBA", (W, H), img)
        b = Image.frombytes("RGBA", (W, H), ref)
        diff = Image.new("L", (W, H))
        n = 0
        for y in range(H):
            for x in range(W):
                if a.getpixel((x, y)) != b.getpixel((x, y)):
                    diff.putpixel((x, y), 255)
                    n += 1
        self.fail(f"{label}: {n} px 与参考不一致, "
                  f"差异区域 {diff.getbbox()}")

    def test_wide_char_head_no_residue(self):
        # 光标在中文头格停留后移开 —— 残影主 bug
        self._assert_restore_clean(
            CJK_LINE, [(2, 0)], (13, 0), "宽字符头格光标恢复")

    def test_wide_char_tail_no_erase(self):
        # 光标停在宽字符尾格后移开 —— 头尾两格完整恢复，
        # 不得用默认背景抹掉字形右半边
        self._assert_restore_clean(
            CJK_LINE, [(3, 0)], (13, 0), "宽字符尾格光标恢复")

    def test_underline_preserved(self):
        # 光标经过下划线（SGR 4）字符后，下划线必须完整保留。
        # 同时覆盖：格子矩形不得溢出 1px 到相邻格——恢复矩形
        # 溢出的那一格会被 'd' 的左边缘墨迹暴露（左对齐字符最
        # 左像素列有墨，CJK 居中无墨所以宽字符场景看不到）
        self._assert_restore_clean(
            "ab\x1b[4mcd\x1b[0m ef\n", [(2, 0)], (7, 0), "下划线恢复")


class TestRendererTrueColor(_RendererTestBase):
    """真彩色渲染像素级验证：38;2;R;G;B 精确着色，粗体不亮化。"""

    def test_truecolor_fg_pixel(self):
        img = self._snapshot("\x1b[38;2;10;200;30m█\x1b[0m", [(1, 0)])
        self._assert_cell_has_pixel(img, 0, 0, (10, 200, 30, 255))

    def test_truecolor_bold_not_brightened(self):
        # 粗体真彩色不得亮化（调色板索引 16-195 的亮化会把颜色 +36 偏移）
        img = self._snapshot("\x1b[1;38;2;10;200;30m█\x1b[0m", [(1, 0)])
        self._assert_cell_has_pixel(img, 0, 0, (10, 200, 30, 255))

    def test_truecolor_bg_pixel(self):
        img = self._snapshot("\x1b[48;2;255;0;0m \x1b[0m", [(1, 0)])
        canvas = Image.frombytes("RGBA", (W, H), img)
        # 空格格角落像素（非墨迹区）应为真彩色背景
        self.assertEqual(
            canvas.getpixel((BORDER + 1, BORDER + 1)), (255, 0, 0, 255))

    def test_256color_palette_pixel(self):
        # 38;5 仍走调色板：断言像素等于 COLORMAP[196]
        img = self._snapshot("\x1b[38;5;196m█\x1b[0m", [(1, 0)])
        r, g, b = COLORMAP[196]
        self._assert_cell_has_pixel(img, 0, 0, (r, g, b, 255))


class TestRendererWideOverwrite(_RendererTestBase):
    """宽字符尾格被普通字符覆盖后必须正常渲染
    （残留 WIDE_TAIL 标记会被 renderer 跳过 → 显示空白）。"""

    def test_overwritten_tail_renders(self):
        term = Term(40, 10)
        vt = Vt100(term)
        vt.tty_write = lambda s: None
        r = Renderer(term, self._ren, W, H, char_w=CW, char_h=CH,
                     border_px=BORDER, font_size=12)
        try:
            for ch in "你你你你":   # heads 0,2,4,6 / tails 1,3,5,7
                vt.t_putc(ch)
            # tmux 重绘场景：ASCII 覆盖宽字符的头格+尾格
            vt.t_move_to(6, 0)
            vt.t_putc('X')
            vt.t_move_to(7, 0)
            vt.t_putc('Y')
            vt.t_move_to(8, 0)
            r.draw_frame()
            img = r._img
        finally:
            r.shutdown()
        # 修复前：col7 残留 WIDE_TAIL → renderer 跳过 → 'Y' 显示空白
        self.assertFalse(term.lines[0][7].state & GLYPH_WIDE_TAIL)
        r2, g2, b2 = COLORMAP[DEFAULT_FG]
        self._assert_cell_has_pixel(img.tobytes(), 6, 0, (r2, g2, b2, 255))
        self._assert_cell_has_pixel(img.tobytes(), 7, 0, (r2, g2, b2, 255))


if __name__ == '__main__':
    unittest.main(verbosity=2)
