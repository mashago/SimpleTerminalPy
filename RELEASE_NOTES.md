# SimpleTerminalPy v1.0.0

A terminal emulator for embedded Linux handheld consoles, rewritten in **Python + PySDL2 + PIL**, ported from [SimpleTerminal](https://github.com/haoict/SimpleTerminal) (C/SDL2 version).

![Screenshot 1](screenshots/screenshot1.jpg)

## Features

- Full VT100 escape sequence parsing (30+ CSI commands)
- 256 colors + SGR attributes (bold / underline / reverse / blink)
- Interactive PTY shell — vim, top, htop all work
- **Key calibration wizard** — maps your physical buttons on first launch, adapts to any handheld automatically
- On-screen keyboard (OSK) with sticky modifier keys (Ctrl+C/D/W combos)
- Scrollback buffer (256 lines)
- CJK double-width rendering with bundled fonts (Apache 2.0) — no firmware font dependency
- Bluetooth keyboard isolation via device ID (no key conflicts)
- Key guide screen + L1+R1 combo to reset keymap

## Downloads

- **Source code** (zip / tar.gz) — run anywhere with `python3` + `pysdl2` + `Pillow`
- **SimpleTerminalPy-v1.0.0-aarch64.tar.gz** — PyInstaller binary for armv8/aarch64 handhelds (built on Ubuntu 22.04, glibc 2.35; requires system SDL2, `PYSDL2_DLL_PATH=/usr/lib`)

## Install (source)

1. Extract to a directory the handheld can run apps from, e.g. `/mnt/sdcard/Roms/APPS/`
2. Copy `SimpleTerminalPy-Raw.sh` to `<that dir>/SimpleTerminalPy.sh`
3. Launch "SimpleTerminalPy" from the Tools menu

## Install (binary)

1. Extract `SimpleTerminalPy-v1.0.0-aarch64.tar.gz` to a runnable directory, e.g. `/mnt/sdcard/Roms/APPS/`
2. Copy `SimpleTerminalPy/SimpleTerminalPy.sh` to the APPS level
3. Launch "SimpleTerminalPy" from the Tools menu

## Usage

- First launch shows a key guide screen, then the calibration wizard — press each button when prompted (short press to confirm, hold 3s to abort)
- X: show / hide on-screen keyboard · Y: move OSK · MENU: quit
- L1+R1: delete keymap and re-calibrate on next start
- Full key table in the [README](README.md)

## Known Limitations

- Color emoji not supported (reasonable trade-off for embedded terminals)
- Bold/italic SGR attributes render without glyph variation
- Brief frame drops possible on extreme full-screen refreshes (e.g. vim initial startup)

## License

MIT License — based on [SimpleTerminal](https://github.com/haoict/SimpleTerminal) (MIT), fonts under Apache 2.0 / Bitstream Vera License.
