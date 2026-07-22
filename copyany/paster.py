"""模拟 Ctrl+V 自动粘贴。

返回 True  表示已发送按键; False 表示当前环境不支持(内容已写入剪贴板, 需用户手动粘贴)。
  Windows / Linux X11: pynput
  Linux Wayland      : 尝试 ydotool (需 sudo apt install ydotool)
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from .hotkey import is_wayland

log = logging.getLogger(__name__)


def simulate_paste() -> bool:
    try:
        if sys.platform.startswith("linux") and is_wayland():
            if shutil.which("ydotool"):
                # 29=LeftCtrl, 47=V: 按下 ctrl -> 按下 v -> 抬起 v -> 抬起 ctrl
                subprocess.Popen(
                    ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            log.info("Wayland 下未安装 ydotool, 跳过自动粘贴")
            return False
        from pynput.keyboard import Controller, Key
        kb = Controller()
        with kb.pressed(Key.ctrl):
            kb.press("v")
            kb.release("v")
        return True
    except Exception:
        log.exception("模拟粘贴失败")
        return False
