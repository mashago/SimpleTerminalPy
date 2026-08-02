#!/bin/bash
# SimpleTerminalPy 二进制版启动脚本（PyInstaller onedir 包）
# 部署: 解压 tar 包到 APPS → APPS/SimpleTerminalPy/ 内含二进制可执行文件
#       APPS/SimpleTerminalPy.sh 直接执行二进制
progdir="$(cd "$(dirname "$0")" && pwd)"
BIN_DIR="${progdir}/SimpleTerminalPy"

export PYSDL2_DLL_PATH="/usr/lib"
export PYTHONUNBUFFERED=1

# key_map.json 生成在可执行文件旁边（sys.executable 目录）
"${BIN_DIR}/SimpleTerminalPy" > "${BIN_DIR}/log.txt" 2>&1
