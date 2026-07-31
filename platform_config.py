"""SimpleTerminalPy — 平台按键映射。

对应 C 版 keyboard.h 中各平台的 #ifdef 手柄按键定义。

添加新平台：复制已有条目，修改按钮编号。按钮编号 = -1 表示"不使用"。
"""

PLATFORMS: dict[str, dict] = {
    # ── RG34XXSP (实测) ────────────────────────────────
    # D-Pad: Hat 事件（SDL_JOYHATMOTION），值 1/4/8/2 = 上下左右
    # 按钮 (SDL_JOYBUTTONDOWN):
    "rg34xxsp": {
        "A": 0, "B": 1, "X": 2, "Y": 3,
        "L1": 6, "R1": -1, "L2": -1, "R2": -1,
        "UP": -1, "DOWN": -1, "LEFT": -1, "RIGHT": -1,
        "SELECT": 13, "START": 7,
        "L3": -1, "R3": -1, "MENU": 8,
    },

    # ── R36S / dArkOS ──────────────────────────────────
    "r36s": {
        "A": 0, "B": 1, "X": 2, "Y": 3,
        "L1": 6, "R1": -1, "L2": -1, "R2": -1,
        "UP": -1, "DOWN": -1, "LEFT": -1, "RIGHT": -1,
        "SELECT": -1, "START": 13,
        "L3": -1, "R3": -1, "MENU": 16,
    },

    # ── RG35XXSP ───────────────────────────────────────
    "rg35xxsp": {
        "A": 3, "B": 4, "X": 6, "Y": 5,
        "L1": 7, "R1": 8, "L2": 12, "R2": 13,
        "UP": -1, "DOWN": -1, "LEFT": -1, "RIGHT": -1,
        "SELECT": 9, "START": 10,
        "L3": 2, "R3": 1, "MENU": 11,
    },

    # ── RGB30 ──────────────────────────────────────────
    "rgb30": {
        "A": 0, "B": 1, "X": 2, "Y": 3,
        "L1": 4, "R1": 5, "L2": 6, "R2": 7,
        "UP": 13, "DOWN": 14, "LEFT": 15, "RIGHT": 16,
        "SELECT": 8, "START": 9,
        "L3": 11, "R3": 12, "MENU": 10,
    },

    # ── H700 ───────────────────────────────────────────
    "h700": {
        "A": 0, "B": 1, "X": 2, "Y": 3,
        "L1": 4, "R1": 5, "L2": 6, "R2": 7,
        "UP": 13, "DOWN": 14, "LEFT": 15, "RIGHT": 16,
        "SELECT": 8, "START": 9,
        "L3": 11, "R3": 12, "MENU": 10,
    },

    # ── Raspberry Pi (generic controller) ──────────────
    "pi": {
        "A": 0, "B": 1, "X": 2, "Y": 3,
        "L1": 4, "R1": 5, "L2": 6, "R2": 7,
        "UP": 13, "DOWN": 14, "LEFT": 15, "RIGHT": 16,
        "SELECT": 8, "START": 9,
        "L3": 11, "R3": 12, "MENU": 10,
    },
}

# 逻辑动作 → 手柄按钮的映射
DEFAULT_BINDINGS = {
    "scroll_up":   "L2",
    "scroll_down": "R2",
    "osk_activate": "X",
    "osk_location": "Y",
    "osk_toggle":  "R1",
    "shift":       "L1",
    "enter":       "START",
    "tab":         "SELECT",
    "quit":        "MENU",
}
