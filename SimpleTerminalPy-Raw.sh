#!/bin/bash
# SimpleTerminalPy 启动脚本
progdir="$(cd "$(dirname "$0")" && pwd)"
export PYSDL2_DLL_PATH="/usr/lib"
export PYTHONUNBUFFERED=1
export PYTHONDONTWRITEBYTECODE=1
rm -rf "${progdir}/SimpleTerminalPy/__pycache__"
python3 -uB "${progdir}/SimpleTerminalPy/main.py" > "${progdir}/SimpleTerminalPy/log.txt" 2>&1
