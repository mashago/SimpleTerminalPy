# SimpleTerminalPy

[English](README.md) | [简体中文](README_zh.md)

A terminal emulator for embedded Linux handheld consoles, rewritten in **Python + PySDL2 + PIL**, ported from [SimpleTerminal](https://github.com/haoict/SimpleTerminal) (C/SDL2 version).

- Full VT100 escape sequence parser (30+ CSI commands)
- 256 colors + SGR attributes (bold / underline / reverse / blink)
- Interactive PTY shell (vim, top, htop, and more)
- On-screen keyboard (OSK)
- Scrollback buffer (256 lines)
- CJK double-width rendering (bundled fonts, Apache 2.0)
- **Key calibration wizard** — adapts to any handheld automatically

## Screenshots

<img src="screenshots/screenshot1.jpg" alt="Screenshot 1" width="250"/>
<img src="screenshots/screenshot2.jpg" alt="Screenshot 2" width="250"/>
<img src="screenshots/screenshot3.jpg" alt="Screenshot 3" width="250"/>
<img src="screenshots/screenshot4.jpg" alt="Screenshot 4" width="250"/>

---

## Running

```bash
# Via launcher script (put in APPS dir)
./SimpleTerminalPy.sh

# Directly
python3 main.py

# Force re-calibrate keys
python3 main.py -reset-keymap

# Command line options
python3 main.py [-font font.ttf] [-fontsize 12] [-rotate 0|90|180|270]
                [-term xterm-256color] [-reset-keymap] [-r "command"]
```

**Dependencies**: `python3`, `pysdl2`, `Pillow` (SDL2 system libraries required)

---

## Fonts

Bundled fonts (no system font dependency):

```
fonts/
├── DroidSansMono.ttf          # Monospace Latin (primary)
├── DroidSansFallbackFull.ttf  # CJK (Chinese/Japanese/Korean)
└── LICENSE.txt                # Apache License 2.0
```

Both fonts are from Google's Android Open Source Project, licensed under **Apache 2.0** — safe to redistribute. The renderer falls back to system fonts (DejaVu Sans Mono, device firmware fonts, etc.) if the bundled ones are missing.



## Key Calibration (first launch)

On first launch (or with `-reset-keymap`), the **key calibration wizard** appears:

<img src="screenshots/screenshot5.jpg" alt="Key Calibration" width="400"/>

```
        KEY SETUP

    Press [UP]  (1/15)
    ...
    Short press = confirm | Hold 3s = abort
```

| Action | Behavior |
|--------|----------|
| **Short press** (press & release) | Confirm current key → record → next |
| **Hold 3 seconds** | Abort calibration, exit without saving |
| **Press an already-assigned key** | Ignored, wait for a different key |

Calibration order: `UP → DOWN → LEFT → RIGHT → A → B → X → Y → MENU → SELECT → START → L1 → R1 → L2 → R2`

Results are saved to `key_map.json` (next to the program):

```json
{
  "keys": {
    "up":    {"type": "hat", "value": 1, "device": 0},
    "x":     {"type": "key", "value": 307, "device": 1},
    ...
  }
}
```

- `type`: `btn` (joystick button) / `hat` (D-pad) / `key` (keyboard channel) / `cbtn` (game controller)
- `device`: source device ID — must match for the key channel, **preventing conflicts with Bluetooth keyboards**

---

## Button Functions

> Physical buttons are defined by the player during calibration; the table below lists logical key functions.

### Global (active in any mode)

| Button | Function |
|--------|----------|
| **MENU** | Quit program |
| **X** | Show / hide OSK |
| **Y** | Toggle OSK position (bottom / top) |
| **L1 + R1** | Delete key_map.json (re-calibrate on next start) |

### When OSK is visible

| Button | Function |
|--------|----------|
| **D-Pad (UP/DOWN/LEFT/RIGHT)** | Move OSK cursor (hold to repeat) |
| **A** | Press the selected OSK key |
| **B** | Backspace |
| **L1** | Hold-shift (hold = uppercase, release = lowercase) |
| **R1** | Sticky modifier (select Ctrl/Alt/⇧ key, then press R1 to lock/unlock) |
| **L2** | Left arrow (pass-through to terminal, works in vim) |
| **R2** | Right arrow (pass-through to terminal, works in vim) |
| **START** | Enter |
| **SELECT** | Tab |

### When OSK is hidden (pass-through mode — vim/htop/top, etc.)

| Button | Function |
|--------|----------|
| **D-Pad (UP/DOWN/LEFT/RIGHT)** | Arrow keys |
| **A** | Enter |
| **B** | Ctrl+C |
| **SELECT** | Tab |
| **L2** | Scrollback up 3 lines |
| **R2** | Scrollback down 3 lines |

### Physical keyboard (USB / Bluetooth)

| Key | Function |
|-----|----------|
| Letters / digits / symbols | Normal input (IME composition via SDL_TEXTINPUT) |
| Arrows / Home / End / PageUp / PageDown / F1-F12 | Standard escape sequences |
| Ctrl + letter | Control characters (Ctrl+C, Ctrl+D, etc.) |
| Tab / Shift+Tab | Tab / reverse tab |
| Enter / Alt+Enter | Return / ESC+Return |
| Ctrl+Shift+V | Paste from clipboard |

> Bluetooth keyboards are isolated from handheld buttons: a key channel event only maps to a handheld button when its device ID matches calibration.

---

## Using the OSK

- **A** presses the highlighted key
- **L1** hold for uppercase, release to return to lowercase
- **R1** sticky modifiers: move cursor to `Ctrl` / `Alt` / `⇧` and press R1 to lock, then press letters for combos (e.g. Ctrl+A); press R1 again to unlock
- **R1-locked Shift** acts as Caps Lock (L1 does not affect a locked shift)
- Symbol layer via the `#+=` key on the OSK, `ABC` to return
- **X** shows / hides the OSK anytime

---

## Scrollback

- **L2 / R2**: scroll up / down 3 lines (when OSK is hidden)
- `[N]^` indicator in the top-right corner while scrolled
- Pressing any other key returns to the bottom

---

## File Structure

```
SimpleTerminalPy/
├── main.py              # Main loop + event dispatch + startup flow
├── config.py            # Color palette (259 colors) + defaults
├── terminal.py          # Glyph / Term / Cursor data model
├── vt100.py             # VT100 state machine (30+ CSI commands)
├── pty_handler.py       # PTY creation + select reader thread
├── renderer.py          # PIL dirty-line incremental renderer + glyph LRU cache
├── osk.py               # On-screen keyboard
├── input_handler.py     # Event (type, value, device) → logical key
├── key_calibrate.py     # Key calibration wizard
├── wcwidth.py           # Unicode East Asian Width
├── fonts/               # Bundled fonts (Apache 2.0)
│   ├── DroidSansMono.ttf
│   ├── DroidSansFallbackFull.ttf
│   └── LICENSE.txt
├── key_map.json         # Player calibration result (generated at runtime)
├── SimpleTerminalPy.sh  # Launcher script (put in APPS dir)
└── sync_to_app.sh       # Sync-to-SD-card script
```

---

## Syncing to the Console

```bash
# Sync code to /mnt/sdcard/Roms/APPS/SimpleTerminalPy
# Automatically clears __pycache__ and key_map.json (re-calibrate on next start)
bash sync_to_app.sh
```

---

## Known Limitations

- Color emoji not supported (reasonable trade-off for embedded terminals)
- Possible brief frame drops on extreme full-screen refreshes (e.g. vim initial startup)
- Bold/italic SGR attributes render without glyph variation (bold colors not brightened either)

## License

MIT License — based on [SimpleTerminal](https://github.com/haoict/SimpleTerminal) (MIT)
