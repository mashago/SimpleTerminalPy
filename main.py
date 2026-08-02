#!/usr/bin/env python3
"""SimpleTerminalPy — 用 PySDL2 重写的嵌入式终端模拟器。

启动流程:
  1. 解析命令行参数
  2. SDL 初始化
  3. 检查 key_map.json — 不存在则运行按键校准向导
  4. 创建终端组件 (Term + Vt100 + PtyHandler + Renderer)
  5. 主循环
"""

import argparse
import ctypes
import os
import sys

import sdl2
import sdl2.ext

from config import (
    INITIAL_WIDTH, INITIAL_HEIGHT, DEFAULT_SCALE,
    DEFAULT_SHELL, BUTTON_HELD_DELAY,
)
from terminal import Term
from vt100 import Vt100
from pty_handler import PtyHandler
from renderer import Renderer
from input_handler import InputHandler
from osk import OSK
from key_calibrate import KeyCalibrator, KeyHelpScreen, load_keymap

# ── 全局选项 ────────────────────────────────────────────
opt_scale = DEFAULT_SCALE
opt_rotate = 0
opt_font = None
opt_fontsize = 12
opt_fontshade = 0
opt_cmd: list[str] = []
opt_term = None
opt_platform = "rg34xxsp"

# key_map.json 路径（统一方案：三种模式行为一致）
# - 源码模式: 代码所在目录（__file__）
# - PyInstaller 打包 (onedir/onefile): 可执行文件真实目录（sys.executable），
#   注意 onefile 的 __file__ 指向临时解压目录，写进去退出就丢
# - 目录只读时回退到 ~/.simple_terminal_py
if getattr(sys, "frozen", False):
    _base = os.path.dirname(os.path.realpath(sys.executable))
    if not os.access(_base, os.W_OK):
        _base = os.path.join(os.path.expanduser("~"), ".simple_terminal_py")
        os.makedirs(_base, exist_ok=True)
    KEYMAP_PATH = os.path.join(_base, "key_map.json")
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    KEYMAP_PATH = os.path.join(APP_DIR, "key_map.json")


def parse_args():
    global opt_scale, opt_rotate, opt_font, opt_fontsize, opt_fontshade
    global opt_cmd, opt_term, opt_platform

    p = argparse.ArgumentParser(
        description="SimpleTerminalPy — 嵌入式终端模拟器")
    p.add_argument("-scale", type=float, default=DEFAULT_SCALE)
    p.add_argument("-font", type=str, default=None)
    p.add_argument("-fontsize", type=int, default=12)
    p.add_argument("-fontshade", type=int, default=0)
    p.add_argument("-rotate", type=int, default=0,
                   choices=[0, 90, 180, 270])
    p.add_argument("-term", type=str, default=None)
    p.add_argument("-platform", type=str, default="rg34xxsp",
                   help="平台(仅用于默认布局): rg34xxsp, r36s, rg35xxsp, rgb30, h700, pi")
    p.add_argument("-reset-keymap", action="store_true",
                   help="忽略已有 key_map.json，重新校准")
    p.add_argument("-r", nargs="*", default=[], dest="cmd")
    p.add_argument("-q", action="store_true")
    args = p.parse_args()

    opt_scale = args.scale
    opt_rotate = args.rotate
    opt_font = args.font
    opt_fontsize = args.fontsize
    opt_fontshade = args.fontshade
    opt_cmd = args.cmd or []
    opt_term = args.term
    opt_platform = args.platform
    return args


# ── SDL 应用 ────────────────────────────────────────────

class SDLApp:
    def __init__(self):
        self.window = None
        self.renderer = None
        self.screen_w = 0
        self.screen_h = 0
        self.running = True
        self.needs_redraw = True

        # 终端组件
        self.term: Term | None = None
        self.vt100: Vt100 | None = None
        self.pty: PtyHandler | None = None
        self.term_renderer: Renderer | None = None

        # 输入
        self.input_handler: InputHandler | None = None
        self.osk: OSK | None = None
        self.keymap: dict[str, tuple] = {}

        # 手柄
        self.joystick = None

        # 长按重复 — 基于 (type, value)
        self._repeat_state: dict[tuple, dict] = {}
        self._down_events: set[tuple] = set()

        # 光标 blink
        self._last_blink = 0
        self.BLINK_RATE = 500

        # 帧计数
        self._frame = 0

    # ── 初始化 SDL ────────────────────────────────────

    def init_sdl(self):
        if sdl2.SDL_Init(sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_JOYSTICK) < 0:
            raise RuntimeError(
                f"SDL_Init: {sdl2.SDL_GetError().decode()}")

        dm = sdl2.SDL_DisplayMode()
        if sdl2.SDL_GetCurrentDisplayMode(0, dm) != 0:
            self.screen_w = int(INITIAL_WIDTH * opt_scale)
            self.screen_h = int(INITIAL_HEIGHT * opt_scale)
        else:
            self.screen_w = dm.w
            self.screen_h = dm.h

        print(f"Screen: {self.screen_w}x{self.screen_h} scale={opt_scale}")

        self.window = sdl2.SDL_CreateWindow(
            b"SimpleTerminalPy",
            sdl2.SDL_WINDOWPOS_UNDEFINED,
            sdl2.SDL_WINDOWPOS_UNDEFINED,
            0, 0,
            sdl2.SDL_WINDOW_FULLSCREEN_DESKTOP | sdl2.SDL_WINDOW_SHOWN,
        )
        if not self.window:
            raise RuntimeError(
                f"SDL_CreateWindow: {sdl2.SDL_GetError().decode()}")

        self.renderer = sdl2.SDL_CreateRenderer(
            self.window, -1, sdl2.SDL_RENDERER_ACCELERATED)
        if not self.renderer:
            self.renderer = sdl2.SDL_CreateRenderer(
                self.window, -1, sdl2.SDL_RENDERER_SOFTWARE)
        if not self.renderer:
            raise RuntimeError(
                f"SDL_CreateRenderer: {sdl2.SDL_GetError().decode()}")

        sdl2.SDL_SetHint(sdl2.SDL_HINT_RENDER_SCALE_QUALITY, b"0")

        # 手柄
        if sdl2.SDL_NumJoysticks() > 0:
            self.joystick = sdl2.SDL_JoystickOpen(0)
            if self.joystick:
                name = sdl2.SDL_JoystickName(self.joystick)
                print(f"Joystick: {name.decode() if name else '?'}")
            else:
                print("Warning: joystick open failed")
        else:
            print("No joystick — keyboard only")

    # ── 按键校准 ──────────────────────────────────────

    def ensure_keymap(self) -> bool:
        """确保 key_map.json 存在。返回 False 表示用户放弃了校准。"""
        # 先展示按键功能说明（3 列 16 行表格，按任意键继续）
        help_screen = KeyHelpScreen(
            self.renderer, self.screen_w, self.screen_h)
        help_screen.run()

        if not os.path.exists(KEYMAP_PATH) or \
           "--reset-keymap" in sys.argv:
            print("No key_map.json — starting calibration...")
            calibrator = KeyCalibrator(
                self.renderer, self.screen_w, self.screen_h,
                KEYMAP_PATH)
            result = calibrator.run()
            if result is None:
                print("Calibration aborted by user.")
                return False
            self.keymap = result
            print(f"Keymap calibrated: {self.keymap}")
        else:
            self.keymap = load_keymap(KEYMAP_PATH) or {}
            print(f"Keymap loaded: {len(self.keymap)} keys")

        # 检查完整性
        missing = [k for k in ["up", "down", "left", "right", "a", "b",
                               "menu", "select", "start"]
                   if k not in self.keymap]
        if missing:
            print(f"WARNING: keymap incomplete, missing: {missing}")

        return True

    # ── 初始化终端组件 ────────────────────────────────

    def init_terminal(self):
        font_path = opt_font
        if font_path and font_path in ('1', '2', '3', '4', '5'):
            font_path = None

        char_w, char_h = 8, 16
        cols = max(1, (self.screen_w - 4) // char_w)
        rows = max(1, (self.screen_h - 4) // char_h)

        self.term = Term(cols, rows)
        self.vt100 = Vt100(self.term)
        self.term_renderer = Renderer(
            self.term, self.renderer,
            self.screen_w, self.screen_h,
            char_w=char_w, char_h=char_h,
            border_px=2,
            font_path=font_path,
            font_size=opt_fontsize,
            opt_rotate=opt_rotate,
            opt_scale=opt_scale,
        )

        # PTY
        self.pty = PtyHandler(
            shell_path=DEFAULT_SHELL,
            term_name=opt_term or "xterm-256color",
            cmd_list=opt_cmd,
        )

        def on_pty_data(text: str):
            for ch in text:
                self.vt100.t_putc(ch)
            self.needs_redraw = True

        def on_child_exit():
            self.running = False

        self.pty.on_data = on_pty_data
        self.pty.on_child_exit = on_child_exit
        self.vt100.tty_write = lambda s: self.pty.write(s)

        # 输入
        self.input_handler = InputHandler(keymap=self.keymap)
        self.osk = OSK(self.screen_w, self.screen_h)

        # 启动 PTY
        self.pty.spawn(rows=rows, cols=cols)
        self.pty.start_reader_thread()

        print(f"Terminal: {cols}x{rows} font={font_path or 'default'} "
              f"size={opt_fontsize} rotate={opt_rotate}")

    # ── 主循环 ────────────────────────────────────────

    def run(self):
        print("Entering main loop...")
        self.needs_redraw = True

        while self.running:
            now = sdl2.SDL_GetTicks()

            event = sdl2.SDL_Event()
            while sdl2.SDL_PollEvent(ctypes.byref(event)) != 0:
                self._handle_event(event)

            # 退出检测（Start+Select 或 Menu）
            if self.input_handler and \
               (self.input_handler.is_down("menu") or
                self.input_handler.check_exit_combo()):
                print("Exit requested")
                self.running = False
                continue

            # 光标 blink
            if now - self._last_blink > self.BLINK_RATE:
                if self.term_renderer:
                    self.term_renderer.toggle_blink()
                self._last_blink = now
                self.needs_redraw = True

            # 长按重复（方向键等）
            self._check_button_repeat(now)

            # 渲染
            if self.needs_redraw and self.term_renderer:
                osk_img = (self.osk.render() if self.osk and
                           self.osk.active else None)
                osk_top = (self.osk.location_bottom is False
                           if self.osk else False)
                self.term_renderer.draw_frame(osk_img, osk_top)
                self.needs_redraw = False
                self._frame += 1

            sdl2.SDL_Delay(16)

        self._shutdown()

    # ── 事件分发 ──────────────────────────────────────

    def _handle_event(self, event: sdl2.SDL_Event):
        etype = event.type

        if etype == sdl2.SDL_QUIT:
            self.running = False

        elif etype == sdl2.SDL_KEYDOWN:
            # 检查是否掌机按键（键盘通道，须匹配设备 ID）
            if self._keymap_owns_key(event.key.keysym.sym,
                                     event.key.which):
                self._on_game_event("key", event.key.keysym.sym,
                                    event.key.which, True)
            else:
                self._on_keydown(event.key)

        elif etype == sdl2.SDL_TEXTINPUT:
            text = event.text.text.decode('utf-8', errors='replace')
            if self.pty:
                self.pty.write(text)

        elif etype == sdl2.SDL_JOYBUTTONDOWN:
            self._on_game_event("btn", event.jbutton.button,
                                event.jbutton.which, True)
        elif etype == sdl2.SDL_JOYBUTTONUP:
            self._on_game_event("btn", event.jbutton.button,
                                event.jbutton.which, False)

        elif etype == sdl2.SDL_JOYHATMOTION:
            val = event.jhat.value
            which = event.jhat.which
            if val != 0:
                self._on_game_event("hat", val, which, True)
            else:
                # 释放所有 hat 方向
                for mask in (1, 2, 4, 8):
                    self._on_game_event("hat", mask, which, False)

        elif etype == sdl2.SDL_CONTROLLERBUTTONDOWN:
            self._on_game_event("cbtn", event.cbutton.button,
                                event.cbutton.which, True)
        elif etype == sdl2.SDL_CONTROLLERBUTTONUP:
            self._on_game_event("cbtn", event.cbutton.button,
                                event.cbutton.which, False)

        elif etype == sdl2.SDL_JOYAXISMOTION:
            pass

    def _keymap_owns_key(self, sym: int, device: int) -> bool:
        """判断该键盘事件是否已被校准映射为掌机按键（须匹配设备）。"""
        return self.input_handler is not None and \
            self.input_handler.resolve("key", sym, device) is not None

    def _on_game_event(self, etype: str, value: int,
                       device: int, pressed: bool):
        """统一处理掌机输入事件。"""
        if self.input_handler is None:
            return

        self.input_handler.on_event(etype, value, device, pressed)
        ev = (etype, value, device)

        if pressed:
            self._down_events.add(ev)
            # 记录重复计时
            self._repeat_state[ev] = {
                "press_time": sdl2.SDL_GetTicks(),
                "next_time": sdl2.SDL_GetTicks() + BUTTON_HELD_DELAY,
            }
        else:
            self._down_events.discard(ev)
            self._repeat_state.pop(ev, None)

        # 解析逻辑键名（key 通道匹配 device，其他通道忽略 device）
        name = self.input_handler.resolve(etype, value, device)
        if name is None:
            return

        self._on_named_action(name, pressed)

    def _on_named_action(self, name: str, pressed: bool):
        """按逻辑键名分发动作（pressed=True 按下，False 松开）。"""
        osk = self.osk
        pty = self.pty
        term = self.term
        if osk is None or pty is None:
            return

        sys.stderr.write(f"[KEY] {name} {'↓' if pressed else '↑'}\n")
        sys.stderr.flush()

        # ── L1+R1 组合：删除 keymap 文件（下次启动重新校准） ──
        if name in ("l1", "r1") and pressed:
            other = "r1" if name == "l1" else "l1"
            if self.input_handler.is_down(other):
                self._delete_keymap()
                return

        # ── 全局键（任何模式） ──
        if name == "menu":
            if pressed:
                self.running = False
            return

        if name == "x":
            if pressed:
                osk.active = not osk.active
                # OSK 切换后全屏重绘 — 清除 OSK 覆盖区域的残留
                term.full_dirt()
                self.needs_redraw = True
            return

        # L1: 按住式 Shift（原版 KEY_SHIFT）
        if name == "l1":
            if pressed:
                osk.shift_down()
            else:
                osk.shift_up()
            self.needs_redraw = True
            return

        # R1: sticky 锁定当前选中修饰键（原版 KEY_OSKTOGGLE）
        if name == "r1":
            if pressed:
                osk.toggle_sticky()
                self.needs_redraw = True
            return

        # ── 只处理按下（松开不重复动作） ──
        if not pressed:
            return

        # Y: 切换 OSK 位置（原版 KEY_LOCATION，仅 OSK 活跃）
        if name == "y":
            if osk.active:
                osk.location_bottom = not osk.location_bottom
                # 位置切换后全屏重绘 — 清除被覆盖区域残留
                term.full_dirt()
                self.needs_redraw = True
            return

        # 非 OSK 键也重置滚动
        if term.scroll_offset > 0:
            term.scroll_view_reset()
            self.needs_redraw = True

        if osk.active:
            self._handle_osk_action(name)
        else:
            self._handle_passthrough_action(name)

    def _handle_osk_action(self, name: str):
        """OSK 活跃时的动作。"""
        osk = self.osk
        pty = self.pty
        term = self.term
        if osk is None or pty is None:
            return

        if name in ("up", "down", "left", "right"):
            getattr(osk, f"move_{name}")()
        elif name == "a":
            seq = osk.press_selected()
            if seq:
                pty.write(seq)
        elif name == "b":
            pty.write("\177")   # Backspace
        elif name == "l2":
            # 原版 KEY_ARROW_LEFT — OSK 活跃时直通左方向键
            pty.write("\033[D")
        elif name == "r2":
            # 原版 KEY_ARROW_RIGHT — OSK 活跃时直通右方向键
            pty.write("\033[C")
        elif name == "start":
            pty.write("\r")     # Enter
        elif name == "select":
            pty.write("\t")     # Tab

        self.needs_redraw = True

    def _handle_passthrough_action(self, name: str):
        """OSK 不活跃时的直通模式（vim/htop 等交互应用）。"""
        pty = self.pty
        term = self.term
        if pty is None:
            return

        if name == "up":
            pty.write("\033[A")
        elif name == "down":
            pty.write("\033[B")
        elif name == "left":
            pty.write("\033[D")
        elif name == "right":
            pty.write("\033[C")
        elif name == "a":
            pty.write("\r")       # Enter
        elif name == "b":
            pty.write("\003")     # Ctrl+C
        elif name == "select":
            pty.write("\t")       # Tab
        elif name == "l2":
            term.scroll_view_up(3)
        elif name == "r2":
            term.scroll_view_down(3)

        self.needs_redraw = True

    # ── 长按重复 ──────────────────────────────────────

    def _check_button_repeat(self, now: int):
        """手柄按钮长按重复（方向键/字母键移动）。"""
        ih = self.input_handler
        if ih is None:
            return

        for ev, state in list(self._repeat_state.items()):
            if ev not in self._down_events:
                continue
            if now < state["next_time"]:
                continue

            name = ih.name_for(ev)
            if name in ("up", "down", "left", "right"):
                # OSK 光标重复移动
                if self.osk and self.osk.active:
                    getattr(self.osk, f"move_{name}")()
                    self.needs_redraw = True

            # 加速
            held = now - state["press_time"]
            if held > 1200:
                interval = 50
            elif held > 400:
                interval = 180
            else:
                interval = BUTTON_HELD_DELAY
            state["next_time"] = now + interval

    # ── 物理键盘 ──────────────────────────────────────

    _NON_PRINTING: dict[int, str] = InputHandler.NON_PRINTING_KEYS

    def _on_keydown(self, key):
        sym = key.keysym.sym
        mod = key.keysym.mod
        ctrl = bool(mod & (sdl2.KMOD_LCTRL | sdl2.KMOD_RCTRL))
        shift = bool(mod & (sdl2.KMOD_LSHIFT | sdl2.KMOD_RSHIFT))

        # Ctrl+Shift+V 粘贴
        if ctrl and shift and sym == sdl2.SDLK_v:
            if sdl2.SDL_HasClipboardText():
                text = sdl2.SDL_GetClipboardText()
                if text and self.pty:
                    self.pty.write(text.decode('utf-8', errors='replace'))
                sdl2.SDL_free(text)
            return

        # 非打印键
        seq = self._NON_PRINTING.get(sym)
        if seq is not None:
            if self.pty:
                self.pty.write(seq)
            return

        # Tab
        if sym == sdl2.SDLK_TAB:
            if self.pty:
                self.pty.write("\033[Z" if shift else "\t")
            return

        # Enter
        if sym in (sdl2.SDLK_RETURN, sdl2.SDLK_KP_ENTER):
            if mod & (sdl2.KMOD_LALT | sdl2.KMOD_RALT):
                if self.pty:
                    self.pty.write("\033\r")
            else:
                if self.pty:
                    self.pty.write("\r")
            return

        # Backspace
        if sym == sdl2.SDLK_BACKSPACE:
            if self.pty:
                self.pty.write("\177")
            return

        # Ctrl+字母
        if ctrl and not (mod & sdl2.KMOD_ALT):
            if sdl2.SDLK_a <= sym <= sdl2.SDLK_z:
                if self.pty:
                    self.pty.write(chr(sym - sdl2.SDLK_a + 1))
                return

    # ── 清理 ──────────────────────────────────────────

    def _shutdown(self):
        print("Shutting down...")
        if self.pty:
            self.pty.shutdown()
        if self.term_renderer:
            self.term_renderer.shutdown()
        if self.renderer:
            sdl2.SDL_DestroyRenderer(self.renderer)
        if self.window:
            sdl2.SDL_DestroyWindow(self.window)
        if self.joystick:
            sdl2.SDL_JoystickClose(self.joystick)
        sdl2.SDL_Quit()
        print(f"Goodbye! ({self._frame} frames)")

    # ── L1+R1 组合：删除 keymap ───────────────────────

    def _delete_keymap(self):
        """删除 key_map.json — 下次启动重新校准（不退出，退出按 MENU）。"""
        try:
            os.remove(KEYMAP_PATH)
            print(f"[KEYMAP] Deleted {KEYMAP_PATH} — "
                  f"will re-calibrate on next start")
        except OSError as e:
            print(f"[KEYMAP] Failed to delete {KEYMAP_PATH}: {e}")


# ── 入口 ─────────────────────────────────────────────────

def main():
    args = parse_args()

    app = SDLApp()
    try:
        app.init_sdl()
        if not app.ensure_keymap():
            app._shutdown()
            sys.exit(0)
        app.init_terminal()
        app.run()
    except Exception as exc:
        print(f"Fatal: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        try:
            app._shutdown()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
