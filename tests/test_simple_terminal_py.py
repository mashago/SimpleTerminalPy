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
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from terminal import Term, GLYPH_SET, GLYPH_WIDE_TAIL, MODE_WRAP
from vt100 import Vt100
from wcwidth import char_width
from key_calibrate import KeyCalibrator, load_keymap, KEY_GUIDE_ROWS
from input_handler import InputHandler
from osk import OSK


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
            cal.keymap = {'up': ('hat', 1, 0), 'x': ('key', 307, 1)}
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


if __name__ == '__main__':
    unittest.main(verbosity=2)
