#!/bin/bash
# 将 SimpleTerminalPy 二进制包同步到 SD 卡 APPS 目录
# 流程: 清理旧的源码/脚本 → 解压 dist 的 tar 包 → 复制启动脚本到 APPS 层
set -e

PROG_DIR="$(cd "$(dirname "$0")" && pwd)"
VERSION=$(python3 -c "from config import VERSION; print(VERSION)")
ARCH=$(uname -m)
TARBALL="${PROG_DIR}/dist/SimpleTerminalPy-v${VERSION}-${ARCH}.tar.gz"

APPS=/mnt/sdcard/Roms/APPS

if [ ! -f "$TARBALL" ]; then
    echo "错误: 找不到 $TARBALL"
    echo "请先运行 build_release.sh 打包"
    exit 1
fi

echo "==> 清理旧的 SimpleTerminalPy"
rm -rf "$APPS/SimpleTerminalPy"
rm -f "$APPS/SimpleTerminalPy.sh"

echo "==> 解压: $TARBALL → $APPS"
tar xzf "$TARBALL" -C "$APPS" --no-same-owner

echo "==> 复制启动脚本: $APPS/SimpleTerminalPy/SimpleTerminalPy.sh → $APPS/"
cp "$APPS/SimpleTerminalPy/SimpleTerminalPy.sh" "$APPS/SimpleTerminalPy.sh"
chmod 755 "$APPS/SimpleTerminalPy.sh"

echo "==> 完成"
echo ""
echo "应用目录:   $APPS/SimpleTerminalPy"
echo "启动脚本:   $APPS/SimpleTerminalPy.sh"
ls -la "$APPS/SimpleTerminalPy.sh"
