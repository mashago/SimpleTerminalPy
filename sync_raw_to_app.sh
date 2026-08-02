#!/bin/bash
# 将 SimpleTerminalPy 从 workspace 同步到 SD 卡 APPS 目录
set -e

TARGET=/mnt/sdcard/Roms/APPS/SimpleTerminalPy
SOURCE=/root/workspace/my_terminal/SimpleTerminalPy

echo "==> 删除旧目录: $TARGET"
rm -rf "$TARGET"

echo "==> 复制: $SOURCE → $TARGET"
mkdir -p "$TARGET"
(
  cd "$SOURCE"
  find . -type d -name '.git'       -prune -o \
          -type d -name '__pycache__' -prune -o \
          -type d -name 'build'      -prune -o \
          -type d -name 'dist'       -prune -o \
          -type f -name '*.pyc'       -prune -o \
          -type f -name '*.spec'      -prune -o \
          -type f -name '*.swp'       -prune -o \
          -type f -name '*.swo'       -prune -o \
          -type f -name '*~'          -prune -o \
          -type f -name '*.sh'        -prune -o \
          -type d -exec mkdir -p "$TARGET/{}" \; \
                   -exec chmod 755 "$TARGET/{}" \; \
          -o \
          -type f -exec cp "{}" "$TARGET/{}" \; \
                   -exec chmod 755 "$TARGET/{}" \;
)

echo "==> 清理 __pycache__ / key_map.json"
rm -rf "$TARGET/__pycache__"
rm -f "$TARGET/key_map.json"

echo "==> 复制启动脚本: $SOURCE/SimpleTerminalPy-Raw.sh → /mnt/sdcard/Roms/APPS/SimpleTerminalPy.sh"
cp "$SOURCE/SimpleTerminalPy-Raw.sh" /mnt/sdcard/Roms/APPS/SimpleTerminalPy.sh
chmod 755 /mnt/sdcard/Roms/APPS/SimpleTerminalPy.sh

echo "==> 完成"
echo ""
echo "应用目录:   $TARGET"
echo "启动脚本:   /mnt/sdcard/Roms/APPS/SimpleTerminalPy.sh"
echo ""
echo "已同步文件:"
find "$TARGET" -maxdepth 1 -type f | sort
