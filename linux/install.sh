#!/usr/bin/env bash
# 把构建产物安装到当前用户环境: 程序目录 + 桌面入口 + 图标 (+ 可选开机自启)
set -euo pipefail
cd "$(dirname "$0")/.."

SRC="dist/copyany"
[[ -x "$SRC/copyany" ]] || { echo "未找到 $SRC, 请先运行 bash linux/build.sh"; exit 1; }

DEST="$HOME/.local/share/copyany"
echo "==> 安装到 $DEST"
mkdir -p "$HOME/.local/share"
rm -rf "$DEST"
cp -r "$SRC" "$DEST"

echo "==> 安装图标与桌面入口"
mkdir -p "$HOME/.local/share/icons/hicolor/512x512/apps"
cp build/icon.png "$HOME/.local/share/icons/hicolor/512x512/apps/copyany.png"

# 有便携启动器(捆绑系统库)则优先使用, 目标机器缺 libxcb-cursor0 也能跑
EXEC="$DEST/copyany"
[[ -x "$DEST/CopyAny.sh" ]] && EXEC="$DEST/CopyAny.sh"

APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
sed "s|@EXEC@|$EXEC|g; s|@ICON@|copyany|g" linux/copyany.desktop > "$APPS/copyany.desktop"
chmod +x "$APPS/copyany.desktop"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true

read -r -p "是否设置开机自启动? [y/N] " ans
if [[ "${ans:-N}" =~ ^[yY]$ ]]; then
    mkdir -p "$HOME/.config/autostart"
    cp "$APPS/copyany.desktop" "$HOME/.config/autostart/copyany.desktop"
    echo "已设置开机自启"
fi

cat <<EOF

安装完成! 启动方式:
  - 应用菜单搜索 "CopyAny", 或运行: $DEST/copyany
  - 配置文件: ~/.config/copyany/config.yaml

[!] 关于 Wayland (Ubuntu 24.04 默认会话):
    GNOME Wayland 限制后台应用读取剪贴板与监听全局快捷键(所有同类软件都受影响)。
    两种解决办法:
    1) 推荐: 注销后在登录界面右下角选择 "Ubuntu on Xorg", 功能完整;
    2) 留在 Wayland:
       - 快捷键: 设置 -> 键盘 -> 查看及自定义快捷键 -> 自定义快捷键, 添加:
           名称:   CopyAny
           命令:   $EXEC --show
           快捷键: Ctrl+Q
       - 自动粘贴(可选): sudo apt install ydotool
         未安装 ydotool 时, 双击记录后需手动 Ctrl+V。
EOF
