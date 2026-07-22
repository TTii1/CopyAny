#!/usr/bin/env bash
# CopyAny Linux 构建脚本 (Ubuntu 24.04 桌面版)
# 用法: bash linux/build.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> 检查依赖"
MISSING=()
command -v python3 >/dev/null || MISSING+=(python3)
python3 -c "import venv, ensurepip" 2>/dev/null || MISSING+=(python3-venv)
# pynput 依赖的 evdev 需要本地编译: gcc + Python 头文件
command -v gcc >/dev/null || MISSING+=(gcc)
python3 -c "import sysconfig, os; raise SystemExit(0 if os.path.exists(os.path.join(sysconfig.get_path('include'), 'Python.h')) else 1)" \
    || MISSING+=(python3-dev)
# PySide6 (Qt6) xcb 平台插件需要的系统库
for p in libgl1 libegl1 libxkbcommon0 libxkbcommon-x11-0 libxcb-cursor0 \
         libxcb-icccm4 libxcb-keysyms1 libfontconfig1 libdbus-1-3; do
    dpkg -s "$p" >/dev/null 2>&1 || MISSING+=("$p")
done
if ((${#MISSING[@]})); then
    echo "缺少依赖, 请先执行: sudo apt install -y ${MISSING[*]}"
    exit 1
fi

# Ubuntu 24.04 启用了 PEP 668, 不能直接 pip install 到系统环境, 这里使用 venv
if [[ ! -d .venv ]]; then
    echo "==> 创建虚拟环境 .venv"
    python3 -m venv .venv
fi
PIP=./.venv/bin/pip
PY=./.venv/bin/python

$PIP install -q --upgrade pip
$PIP install -q -r requirements.txt pyinstaller pillow

echo "==> 生成图标"
$PY build/make_icon.py

echo "==> 运行自检"
$PY run.py --selftest

echo "==> 打包 (PyInstaller onedir)"
$PY -m PyInstaller --noconfirm --clean --windowed --onedir --name copyany \
    --icon build/icon.png --workpath build/work-linux run.py
rm -rf build/work-linux copyany.spec

echo
echo "构建完成: dist/copyany/copyany"
echo "接下来可执行: bash linux/install.sh   (安装到 ~/.local 并创建桌面入口)"
