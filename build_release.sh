#!/bin/bash
# 打包 SimpleTerminalPy — PyInstaller onedir 模式
#
# 产物: dist/SimpleTerminalPy-v<VERSION>-arm64.tar.gz
# 说明: 不打包 SDL2（运行时用系统库，PYSDL2_DLL_PATH=/usr/lib）
#       适用于 armv8/aarch64 Linux 掌机，固件 glibc >= 构建环境
set -e

PROG_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROG_DIR"

VERSION=$(python3 -c "from config import VERSION; print(VERSION)")
ARCH=$(uname -m)
echo "==> 打包 SimpleTerminalPy v$VERSION ($ARCH)"

# 1. 安装 PyInstaller（如缺失）
if ! python3 -m PyInstaller --version > /dev/null 2>&1; then
    echo "==> 安装 PyInstaller..."
    python3 -m pip install pyinstaller
fi

# 2. 清理旧产物
rm -rf build dist SimpleTerminalPy.spec

# 3. 构建 onedir 包
#    --add-data "fonts:fonts"  把字体打进包（运行时 __file__ 相对路径可解析）
#    不收集 libSDL2.so —— 运行时通过 PYSDL2_DLL_PATH 加载系统 SDL2
echo "==> PyInstaller 构建中..."
python3 -m PyInstaller \
    --onedir \
    --name SimpleTerminalPy \
    --add-data "fonts:fonts" \
    --clean \
    main.py

# 4. 复制二进制版启动脚本进包（与二进制同目录，重命名为 SimpleTerminalPy.sh）
#    用户解压后自行将脚本复制到 APPS 目录运行
echo "==> 复制启动脚本..."
cp "$PROG_DIR/SimpleTerminalPy-Bin.sh" dist/SimpleTerminalPy/SimpleTerminalPy.sh
chmod 755 dist/SimpleTerminalPy/SimpleTerminalPy.sh

# 5. 压缩成单个 tar.gz 便于分发
echo "==> 压缩..."
cd dist
OUT="SimpleTerminalPy-v${VERSION}-${ARCH}.tar.gz"
tar czf "$OUT" SimpleTerminalPy

echo ""
echo "==> 完成: dist/$OUT"
ls -lh "$OUT"
echo ""
echo "分发说明:"
echo "  解压后运行 dist/SimpleTerminalPy/SimpleTerminalPy"
echo "  需系统 SDL2: export PYSDL2_DLL_PATH=/usr/lib"
echo "  构建环境: $(uname -srm), glibc $(ldd --version | head -1 | awk '{print $NF}')"
