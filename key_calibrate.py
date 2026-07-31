"""SimpleTerminalPy — 按键校准向导。

玩家第一次启动时，按提示依次按下掌机上的物理按键，
程序记录每个按键对应的 (事件类型, 值)，保存为 key_map.json。
后续启动直接读取，无需再次校准。

交互规则:
  - 短按(松手) = 确认当前键
  - 长按 3 秒 = 放弃校准，退出程序，不保存任何数据
  - 重复按键 = 提示 already set，等待换一个键
"""

import json
import os
import time

import sdl2
from PIL import Image, ImageDraw, ImageFont

# ── 校准顺序 ────────────────────────────────────────────
CALIBRATE_KEYS = [
    "up", "down", "left", "right",
    "a", "b", "x", "y",
    "menu", "select", "start",
    "l1", "r1", "l2", "r2",
]

KEY_LABELS = {
    "up": "UP", "down": "DOWN", "left": "LEFT", "right": "RIGHT",
    "a": "A", "b": "B", "x": "X", "y": "Y",
    "menu": "MENU", "select": "SELECT", "start": "START",
    "l1": "L1", "r1": "R1", "l2": "L2", "r2": "R2",
}

LONG_PRESS_SECONDS = 3.0


class KeyCalibrator:
    """校准向导 — 在 SDL 窗口上渲染提示，等待玩家按键。"""

    def __init__(self, renderer, width: int, height: int,
                 keymap_path: str):
        self.renderer = renderer          # sdl2.SDL_Renderer
        self.width = width
        self.height = height
        self.keymap_path = keymap_path

        # 已收集的按键: {name: (type, value)}
        self.keymap: dict[str, tuple] = {}
        self.current_idx = 0
        self.finished = False
        self.aborted = False

        # 长按检测
        self._pending: tuple | None = None   # 当前被按下的 (type, value)
        self._pending_time = 0.0
        self._confirmed = False              # 已确认（松手后落盘）

        # 确认后的冷却期 — 防止同一物理键的多通道事件
        # （如 menu 同时产生 btn:8 和 key:XXX）立即占用下一个校准项
        self._ignore_until = 0.0

        # 字体
        try:
            self.font_big = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 28)
            self.font_mid = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        except OSError:
            self.font_big = ImageFont.load_default()
            self.font_mid = ImageFont.load_default()

    # ── 主流程 ──────────────────────────────────────────

    def run(self) -> dict | None:
        """执行校准。成功返回 keymap dict，放弃返回 None。"""
        while not self.finished and not self.aborted:
            self._poll_events()
            self._render()
            time.sleep(0.016)

        if self.aborted:
            return None
        return dict(self.keymap)

    # ── 事件处理 ────────────────────────────────────────

    def _poll_events(self):
        event = sdl2.SDL_Event()
        now = time.monotonic()

        while sdl2.SDL_PollEvent(event):
            etype = event.type

            if etype == sdl2.SDL_QUIT:
                self.aborted = True
                return

            elif etype == sdl2.SDL_JOYBUTTONDOWN:
                self._on_press(("btn", event.jbutton.button,
                                event.jbutton.which), now)
            elif etype == sdl2.SDL_JOYBUTTONUP:
                self._on_release(("btn", event.jbutton.button,
                                  event.jbutton.which), now)

            elif etype == sdl2.SDL_JOYHATMOTION:
                val = event.jhat.value
                which = event.jhat.which
                if val != 0:  # 按下方向
                    self._on_press(("hat", val, which), now)
                else:         # 回到中心
                    self._on_release_hat(which, now)

            elif etype == sdl2.SDL_KEYDOWN:
                sym = event.key.keysym.sym
                # 忽略修饰键本身
                if sym in (sdl2.SDLK_LSHIFT, sdl2.SDLK_RSHIFT,
                           sdl2.SDLK_LCTRL, sdl2.SDLK_RCTRL,
                           sdl2.SDLK_LALT, sdl2.SDLK_RALT,
                           sdl2.SDLK_CAPSLOCK):
                    continue
                self._on_press(("key", sym, event.key.which), now)
            elif etype == sdl2.SDL_KEYUP:
                self._on_release(("key", event.key.keysym.sym,
                                  event.key.which), now)

            elif etype == sdl2.SDL_CONTROLLERBUTTONDOWN:
                self._on_press(("cbtn", event.cbutton.button,
                                event.cbutton.which), now)
            elif etype == sdl2.SDL_CONTROLLERBUTTONUP:
                self._on_release(("cbtn", event.cbutton.button,
                                  event.cbutton.which), now)

        # 长按检测
        if self._pending is not None and not self._confirmed:
            if now - self._pending_time >= LONG_PRESS_SECONDS:
                # 长按 3 秒 → 放弃校准
                self.aborted = True

    def _on_press(self, ev: tuple, now: float):
        """按键按下：记录为 pending，等待松手确认或长按放弃。"""
        if now < self._ignore_until:
            # 冷却期内忽略 — 同一物理键的多通道事件
            print(f"[CALIB] ignored (cooldown): {ev}")
            return
        if self._pending is not None:
            return  # 已有 pending，忽略新的
        self._pending = ev
        self._pending_time = now
        self._confirmed = False

    def _on_release(self, ev: tuple, now: float):
        """按键松开：确认当前键（仅当 UP 与 pending 匹配）。"""
        if self._pending is None:
            return

        # UP 事件必须与 pending 是同一个键，否则忽略
        # （防止抖动/重复事件或误触其他键导致跳过校准项）
        if self._pending != ev:
            return

        # 检查是否长按放弃（这里兜底：如果 3 秒后才松手）
        if now - self._pending_time >= LONG_PRESS_SECONDS:
            self.aborted = True
            self._pending = None
            return

        # 确认该键
        self._confirmed = True
        self._pending = None
        self._assign_key(ev, now)

    def _on_release_hat(self, which: int, now: float):
        """Hat 回到中心：确认当前 hat 方向。"""
        if self._pending is None:
            return
        # 只处理 hat 通道的 pending
        if self._pending[0] != "hat" or self._pending[2] != which:
            return

        if now - self._pending_time >= LONG_PRESS_SECONDS:
            self.aborted = True
            self._pending = None
            return

        self._confirmed = True
        ev = self._pending
        self._pending = None
        self._assign_key(ev, now)

    def _assign_key(self, ev: tuple, now: float):
        """把按下的键分配给当前校准项。"""
        current = CALIBRATE_KEYS[self.current_idx]

        # 检查重复
        for name, assigned in self.keymap.items():
            if assigned == ev:
                # 已分配 — 提示 already set，不推进
                print(f"[CALIB] {ev} already set as {name}, "
                      f"press {current} again")
                return

        # 分配
        self.keymap[current] = ev
        print(f"[CALIB] {current} = {ev}")
        self.current_idx += 1

        # 确认后进入冷却期（300ms）— 防止同一物理键的
        # 第二个通道事件（如 menu 的 btn+key 双事件）占用下一项
        self._ignore_until = now + 0.3

        if self.current_idx >= len(CALIBRATE_KEYS):
            self.finished = True
            self._save()

    def _save(self):
        """保存 keymap 到 JSON 文件。"""
        payload = {
            "keys": {name: {"type": t, "value": v, "device": d}
                     for name, (t, v, d) in self.keymap.items()},
        }
        try:
            with open(self.keymap_path, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"[CALIB] Saved keymap → {self.keymap_path}")
        except OSError as e:
            print(f"[CALIB] Failed to save keymap: {e}")

    # ── 渲染 ────────────────────────────────────────────

    def _render(self):
        """渲染校准画面到 SDL。

        全部使用英文文本 — 避免掌机缺少 CJK 字体导致空白。
        """
        img = Image.new("RGBA", (self.width, self.height), (10, 10, 20, 255))
        draw = ImageDraw.Draw(img)

        # 标题
        draw.text((self.width // 2, 40), "KEY SETUP",
                  font=self.font_big, fill=(255, 255, 255, 255),
                  anchor="mm")

        # 当前按键提示
        if self.finished:
            draw.text((self.width // 2, self.height // 2),
                      "DONE!",
                      font=self.font_big, fill=(100, 255, 100, 255),
                      anchor="mm")
        else:
            current = CALIBRATE_KEYS[self.current_idx]
            label = KEY_LABELS.get(current, current)
            progress = f"({self.current_idx + 1}/{len(CALIBRATE_KEYS)})"
            draw.text((self.width // 2, self.height // 2 - 20),
                      f"Press [{label}]  {progress}",
                      font=self.font_big, fill=(255, 255, 100, 255),
                      anchor="mm")

            # 已分配列表（兼容 2/3 元组）
            y = self.height // 2 + 60
            for name, spec in self.keymap.items():
                t = spec[0]
                v = spec[1]
                draw.text((self.width // 2, y),
                          f"{KEY_LABELS.get(name, name)} = {t}:{v}",
                          font=self.font_mid, fill=(150, 150, 150, 255),
                          anchor="mm")
                y += 26

        # 底部提示
        draw.text((self.width // 2, self.height - 30),
                  "Short press = confirm | Hold 3s = abort",
                  font=self.font_mid, fill=(150, 150, 150, 255),
                  anchor="mm")

        # 上传显示
        rgba = img.tobytes()
        texture = sdl2.SDL_CreateTexture(
            self.renderer,
            sdl2.SDL_PIXELFORMAT_RGBA32,
            sdl2.SDL_TEXTUREACCESS_STREAMING,
            self.width, self.height,
        )
        sdl2.SDL_UpdateTexture(texture, None, rgba, self.width * 4)
        sdl2.SDL_RenderClear(self.renderer)
        sdl2.SDL_RenderCopy(self.renderer, texture, None, None)
        sdl2.SDL_RenderPresent(self.renderer)
        sdl2.SDL_DestroyTexture(texture)


# ── 便捷入口 ────────────────────────────────────────────

def load_keymap(path: str) -> dict | None:
    """从 JSON 加载 keymap。文件不存在或损坏返回 None。

    返回 {name: (type, value, device)} — 兼容旧格式（无 device）。
    """
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            payload = json.load(f)
        keys = payload.get("keys", {})
        result = {}
        for name, spec in keys.items():
            t = spec["type"]
            v = spec["value"]
            d = spec.get("device", -1)   # 旧格式没有 device → -1（不匹配任何设备）
            result[name] = (t, v, d)
        return result
    except (OSError, ValueError, KeyError, TypeError):
        return None
