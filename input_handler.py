"""SimpleTerminalPy — 输入处理。

基于玩家校准生成的 key_map.json：
每个逻辑键 = (事件类型, 值) 二元组，例如:
  up   = ("hat", 1)     D-Pad Hat 事件
  a    = ("btn", 0)     Joystick 按钮 0
  x    = ("key", 307)   键盘事件（evdev 码映射）

事件类型:
  btn  → SDL_JOYBUTTONDOWN   value=button id
  hat  → SDL_JOYHATMOTION    value=方向位掩码 (1/2/4/8)
  key  → SDL_KEYDOWN         value=keysym.sym
  cbtn → SDL_CONTROLLERBUTTONDOWN value=button id
"""

import sdl2


class InputHandler:
    """统一处理 SDL 输入事件，根据 OSK 状态分发。

    keymap 条目: name → (type, value, device)
      type: btn / hat / key / cbtn
      value: 事件值
      device: 来源设备 ID（key 通道必须匹配，避免与蓝牙键盘冲突）
    """

    def __init__(self, keymap: dict[str, tuple] | None = None):
        self.keymap: dict[str, tuple] = keymap or {}

        # 反向索引: (type, value) → name（忽略 device，用于同通道查名）
        self._by_event: dict[tuple, str] = {
            (t, v): name for name, (t, v, _d) in self.keymap.items()}

        # 反向索引含 device: (type, value, device) → name
        self._by_event_dev: dict[tuple, str] = {
            (t, v, d): name for name, (t, v, d) in self.keymap.items()}

        # 按钮状态
        self._down: set[tuple] = set()

    # ── 查询 ──────────────────────────────────────────

    def resolve(self, etype: str, value: int,
                device: int = -1) -> str | None:
        """事件 (type, value, device) → 逻辑键名。

        - 非 key 通道（btn/hat/cbtn）：不看 device
        - key 通道：device 必须匹配校准记录（隔离蓝牙键盘）
        """
        if etype == "key":
            return self._by_event_dev.get((etype, value, device))
        return self._by_event.get((etype, value))

    def name_for(self, ev: tuple) -> str | None:
        """按完整事件元组 (type, value[, device]) 查名。"""
        if len(ev) == 3:
            return self._by_event_dev.get(ev)
        return self._by_event.get(ev)

    def spec_for(self, name: str) -> tuple | None:
        return self.keymap.get(name)

    def is_down(self, name: str) -> bool:
        spec = self.keymap.get(name)
        if spec is None:
            return False
        if len(spec) == 3:
            return spec in self._down
        return (spec[0], spec[1]) in self._down

    # ── 事件更新 ──────────────────────────────────────

    def on_event(self, etype: str, value: int,
                 device: int = -1, pressed: bool = True):
        """SDL 事件 → 内部状态。pressed=True 按下，False 松开。"""
        ev = (etype, value, device)
        if pressed:
            self._down.add(ev)
        else:
            self._down.discard(ev)

    # ── 方向键状态 ────────────────────────────────────

    @property
    def dpad_up(self) -> bool:
        return self.is_down("up")

    @property
    def dpad_down(self) -> bool:
        return self.is_down("down")

    @property
    def dpad_left(self) -> bool:
        return self.is_down("left")

    @property
    def dpad_right(self) -> bool:
        return self.is_down("right")

    # ── 退出组合（Start+Select） ──────────────────────

    def check_exit_combo(self) -> bool:
        return self.is_down("start") and self.is_down("select")

    # ── 非打印键映射（物理键盘） ──────────────────────

    NON_PRINTING_KEYS: dict[int, str] = {
        sdl2.SDLK_ESCAPE:  "\033",
        sdl2.SDLK_UP:      "\033[A",
        sdl2.SDLK_DOWN:    "\033[B",
        sdl2.SDLK_LEFT:    "\033[D",
        sdl2.SDLK_RIGHT:   "\033[C",
        sdl2.SDLK_HOME:    "\033[1~",
        sdl2.SDLK_END:     "\033[4~",
        sdl2.SDLK_INSERT:  "\033[2~",
        sdl2.SDLK_DELETE:  "\033[3~",
        sdl2.SDLK_PAGEUP:  "\033[5~",
        sdl2.SDLK_PAGEDOWN: "\033[6~",
        sdl2.SDLK_F1:      "\033OP",
        sdl2.SDLK_F2:      "\033OQ",
        sdl2.SDLK_F3:      "\033OR",
        sdl2.SDLK_F4:      "\033OS",
        sdl2.SDLK_F5:      "\033[15~",
        sdl2.SDLK_F6:      "\033[17~",
        sdl2.SDLK_F7:      "\033[18~",
        sdl2.SDLK_F8:      "\033[19~",
        sdl2.SDLK_F9:      "\033[20~",
        sdl2.SDLK_F10:     "\033[21~",
        sdl2.SDLK_F11:     "\033[23~",
        sdl2.SDLK_F12:     "\033[24~",
    }

    @classmethod
    def lookup_key(cls, sym: int) -> str | None:
        return cls.NON_PRINTING_KEYS.get(sym)
