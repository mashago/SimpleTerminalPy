# SimpleTerminalPy

用 **Python + PySDL2 + PIL** 重写的嵌入式掌机终端模拟器，基于 [SimpleTerminal](https://github.com/haoict/SimpleTerminal)（C/SDL2 版）移植。

- 完整 VT100 转义序列解析（30+ CSI 命令）
- 256 色 + SGR 属性（粗体/下划线/反显/闪烁）
- PTY 交互式 shell（vim / top / htop 等均可运行）
- 屏幕虚拟键盘（OSK）
- Scrollback 历史缓冲（256 行）
- 中文双列宽显示 + CJK 字体回退
- 按键校准向导（自适应任何掌机）

---

## 运行

```bash
# 启动脚本（APPS 目录）
./SimpleTerminalPy.sh

# 直接运行
python3 main.py

# 强制重新校准按键
python3 main.py -reset-keymap

# 命令行参数
python3 main.py [-scale 2.0] [-font font.ttf] [-fontsize 12]
                [-fontshade 0|1|2] [-rotate 0|90|180|270]
                [-term xterm-256color] [-platform rg34xxsp]
                [-r "command"] [-q]
```

---

## 按键校准（首次启动）

首次启动（或 `-reset-keymap`）会进入**按键校准向导**：

```
        KEY SETUP

    Press [UP]  (1/15)
    ...
    Short press = confirm | Hold 3s = abort
```

| 操作 | 行为 |
|------|------|
| **短按**（按下并松开） | 确认当前键 → 记录 → 进入下一个 |
| **长按 3 秒** | 放弃校准，退出程序，不保存任何数据 |
| **按到已分配的键** | 不推进，等待按不同的键 |

校准顺序：`UP → DOWN → LEFT → RIGHT → A → B → X → Y → MENU → SELECT → START → L1 → R1 → L2 → R2`

校准结果保存为 `key_map.json`（与程序同目录）：

```json
{
  "keys": {
    "up":    {"type": "hat", "value": 1, "device": 0},
    "x":     {"type": "key", "value": 307, "device": 1},
    ...
  }
}
```

- `type`: `btn`（手柄按钮）/ `hat`（D-Pad）/ `key`（键盘通道）/ `cbtn`（GameController）
- `device`: 来源设备 ID —— key 通道必须匹配，**避免蓝牙键盘同键码冲突**

---

## 按键功能

> 所有按键在首次启动时由玩家校准定义，以下为逻辑键功能。

### 全局（任何模式下生效）

| 按键 | 功能 |
|------|------|
| **MENU** | 退出程序 |
| **X** | 显示 / 隐藏 OSK |
| **Y** | 切换 OSK 位置（底部 / 顶部） |

### OSK 显示时（虚拟键盘可见）

| 按键 | 功能 |
|------|------|
| **D-Pad (UP/DOWN/LEFT/RIGHT)** | 移动 OSK 光标（长按加速） |
| **A** | 按下 OSK 当前选中的键 |
| **B** | Backspace |
| **L1** | 按住式 Shift（按住=大写，松开=小写） |
| **R1** | Sticky 修饰键（选中 Ctrl/Alt/⇧ 键后按 R1 锁定/解锁） |
| **L2** | 左方向键（直通终端，vim 中可用） |
| **R2** | 右方向键（直通终端，vim 中可用） |
| **START** | Enter |
| **SELECT** | Tab |

### OSK 隐藏时（直通模式，运行 vim/htop/top 等）

| 按键 | 功能 |
|------|------|
| **D-Pad (UP/DOWN/LEFT/RIGHT)** | 方向键 |
| **A** | Enter |
| **B** | Ctrl+C |
| **SELECT** | Tab |
| **L2** | Scrollback 上翻 3 行 |
| **R2** | Scrollback 下翻 3 行 |

### 物理键盘（外接 USB / 蓝牙键盘）

| 按键 | 功能 |
|------|------|
| 字母 / 数字 / 符号 | 正常输入（IME 组合文本经 SDL_TEXTINPUT） |
| 方向键 / Home / End / PageUp / PageDown / F1-F12 | 标准转义序列 |
| Ctrl + 字母 | 控制字符（Ctrl+C / Ctrl+D 等） |
| Tab / Shift+Tab | Tab / 反向 Tab |
| Enter / Alt+Enter | 回车 / ESC+回车 |
| Ctrl+Shift+V | 剪贴板粘贴 |

> 蓝牙键盘与掌机按键隔离：key 通道的设备 ID 不匹配时不会被当作掌机键。

---

## OSK 使用

- **A** 选中并输入高亮键
- **L1** 按住切换大写，松开恢复小写
- **R1** 锁定修饰键（sticky）：把光标移到 `Ctrl`/`Alt`/`⇧` 键上按 R1 锁定，再按字母即可输入组合键（如 Ctrl+A）；再按 R1 解锁
- **R1 锁定 Shift**：大写锁定（L1 不影响锁定的 Shift）
- 符号层通过 OSK 上的 `#+=` 键进入，`ABC` 键返回
- **X** 随时显示/隐藏 OSK

---

## Scrollback

- **L2 / R2**：上下翻 3 行（OSK 隐藏时）
- 屏幕右上角显示 `[N]^` 滚动指示器
- 按任何其他键自动回到屏幕底部

---

## 文件结构

```
SimpleTerminalPy/
├── main.py              # 主循环 + 事件分发 + 启动流程
├── config.py            # 调色板（259 色）+ 默认配置
├── terminal.py          # Glyph / Term / Cursor 数据模型
├── vt100.py             # VT100 状态机（30+ CSI 命令）
├── pty_handler.py       # PTY 创建 + select 读取线程
├── renderer.py          # PIL 脏行增量渲染 + 字形 LRU 缓存
├── osk.py               # 屏幕虚拟键盘
├── input_handler.py     # 事件 (type, value, device) → 逻辑键
├── key_calibrate.py     # 按键校准向导
├── platform_config.py   # 平台预设（保留备用）
├── wcwidth.py           # Unicode East Asian Width
├── key_map.json         # 玩家校准结果（运行时生成）
├── SimpleTerminalPy.sh  # 启动脚本（放 APPS 目录）
└── sync_to_app.sh       # 同步到 SD 卡脚本
```

---

## 同步到掌机

```bash
# 将代码同步到 /mnt/sdcard/Roms/APPS/SimpleTerminalPy
# 自动清理 __pycache__ 和 key_map.json（下次启动重新校准）
bash sync_to_app.sh
```

---

## 已知限制

- 中文显示依赖设备上的 CJK 字体（自动检测常见路径，未找到则显示方框）
- 彩色 Emoji 不支持（嵌入式终端合理取舍）
- 极端全屏刷新（如 vim 首次启动）可能有短暂掉帧

## 许可

MIT License — 基于 [SimpleTerminal](https://github.com/haoict/SimpleTerminal)（MIT）
