"""SimpleTerminalPy — 配置表（对应 config.h）。"""

# ── 窗口默认值 ──────────────────────────────────────────
INITIAL_WIDTH = 320
INITIAL_HEIGHT = 240
DEFAULT_SCALE = 2.0
DEFAULT_ROTATE = 0

# ── 终端设置 ────────────────────────────────────────────
DEFAULT_SHELL = "/bin/bash"
TERM_NAME = "linux"            # TERM 环境变量值，可被 -term 覆盖
SCROLLBACK_LINES = 256
TAB_SPACES = 4
BORDER_PX = 2

# ── 按键长按延迟（毫秒）─────────────────────────────────
BUTTON_HELD_DELAY = 150

# ── 默认色值索引 ───────────────────────────────────────
DEFAULT_FG = 7
DEFAULT_BG = 0
DEFAULT_CS = 256            # 光标色
DEFAULT_UCS = 257           # 未聚焦光标色

# ── 基础 16 色 ──────────────────────────────────────────
_BASE_COLORS = [
    # 00-07: 普通
    (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
    (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
    # 08-15: 高亮
    (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
    (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
]


def _build_colormap():
    """生成 256 色调色板（与 xterm 一致）"""
    cmap = list(_BASE_COLORS)                          # 0-15
    # 216 色立方 (16-231)
    for r in range(6):
        for g in range(6):
            for b in range(6):
                cmap.append((
                    0 if r == 0 else 0x37 + 0x28 * r,
                    0 if g == 0 else 0x37 + 0x28 * g,
                    0 if b == 0 else 0x37 + 0x28 * b,
                ))
    # 24 级灰度 (232-255)
    for i in range(24):
        v = 0x08 + 0x0A * i
        cmap.append((v, v, v))
    # 额外：256=光标灰, 257=未聚焦光标灰, 258=黑
    cmap.extend([
        (204, 204, 204),   # 256: gray80
        (51, 51, 51),      # 257: gray20
        (16, 16, 16),      # 258: gray6
    ])
    return cmap


COLORMAP = _build_colormap()
