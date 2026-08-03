"""SimpleTerminalPy — 配置表（对应 config.h）。"""

# ── 版本 ────────────────────────────────────────────────
VERSION = "1.0.1"

# ── 窗口默认值 ──────────────────────────────────────────
DEFAULT_ROTATE = 0

# ── 终端设置 ────────────────────────────────────────────
DEFAULT_SHELL = "/bin/bash"
TERM_NAME = "linux"            # TERM 环境变量值，可被 -term 覆盖
SCROLLBACK_LINES = 256
TAB_SPACES = 4
BORDER_PX = 2

# ── 按键长按延迟（毫秒）─────────────────────────────────
BUTTON_HELD_DELAY = 150

# ── key 通道（键盘事件）的固定设备 ID ───────────────────
# SDL2 的 SDL_KeyboardEvent 没有 which/deviceID 字段（SDL3 才有），
# 无法区分外接键盘和掌机按键。用固定负数标记 key 通道，
# 避开真实设备 ID（SDL 从 0 开始）。
KBD_DEVICE = -2

# ── 默认色值索引 ───────────────────────────────────────
# 默认前景/背景使用独立颜色（Monokai mintty 的 Foreground/Background），
# 不引用 ANSI 7/0 号色
DEFAULT_FG = 259            # (208,208,208) mintty Foreground
DEFAULT_BG = 260            # (19,19,19) mintty Background
DEFAULT_CS = 256            # 光标色
DEFAULT_UCS = 257           # 未聚焦光标色

# ── 基础 16 色（Monokai，对应 minttyrc）──────────────────
_BASE_COLORS = [
    # 00-07: 普通
    (39, 40, 34),      # Black      #272822
    (249, 38, 114),    # Red        #F92672
    (166, 226, 46),    # Green      #A6E22E
    (244, 191, 117),   # Yellow     #F4BF75
    (102, 217, 239),   # Blue       #66D9EF
    (174, 129, 255),   # Magenta    #AE81FF
    (161, 239, 228),   # Cyan       #A1EFE4
    (248, 248, 242),   # White      #F8F8F2
    # 08-15: Bold（mintty 的 Bold 色）
    (117, 113, 94),    # BoldBlack  #75715E
    (204, 6, 78),      # BoldRed    #CC064E
    (122, 172, 24),    # BoldGreen  #7AAC18
    (240, 169, 69),    # BoldYellow #F0A945
    (33, 199, 233),    # BoldBlue   #21C7E9
    (126, 51, 255),    # BoldMagenta #7E33FF
    (95, 227, 210),    # BoldCyan   #5FE3D2
    (249, 248, 245),   # BoldWhite  #F9F8F5
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
        (204, 204, 204),   # 256: gray80 (光标)
        (51, 51, 51),      # 257: gray20 (未聚焦光标)
        (16, 16, 16),      # 258: gray6
        (208, 208, 208),   # 259: 默认前景（mintty Foreground #D0D0D0）
        (19, 19, 19),      # 260: 默认背景（mintty Background #131313）
    ])
    return cmap


COLORMAP = _build_colormap()
