"""全局快捷键。

Windows / Linux X11: 使用 pynput 注册系统级热键。
Linux Wayland: 桌面环境不允许应用监听全局按键, start() 返回 False;
  请在 GNOME 设置中绑定自定义快捷键执行 `copyany --show`(README 有详细步骤)。
"""
from __future__ import annotations

import logging
import os
import re
import sys

from PySide6.QtCore import QObject, Signal

log = logging.getLogger(__name__)


def is_wayland() -> bool:
    return sys.platform.startswith("linux") and \
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"


def supported() -> bool:
    return not is_wayland()


_MODS = {
    "ctrl": "<ctrl>", "control": "<ctrl>",
    "alt": "<alt>",
    "shift": "<shift>",
    "cmd": "<cmd>", "win": "<cmd>", "super": "<cmd>", "meta": "<cmd>",
}
_SPECIAL = {
    "space", "enter", "tab", "esc", "backspace", "delete", "insert",
    "home", "end", "pageup", "pagedown", "up", "down", "left", "right",
    "capslock", "numlock", "scrolllock", "printscreen", "pause",
}


def to_pynput(combo: str) -> str:
    """把 'ctrl+shift+q' / 'Ctrl+Q' 形式转换为 pynput 的 '<ctrl>+<shift>+q'。"""
    parts = [p.strip().lower() for p in combo.replace("-", "+").split("+") if p.strip()]
    if not parts:
        raise ValueError("快捷键为空")
    out = []
    for p in parts:
        if p in _MODS:
            out.append(_MODS[p])
        elif len(p) == 1:
            out.append(p)
        elif re.fullmatch(r"f([1-9]|1[0-2])", p):
            out.append(f"<{p}>")
        elif p in _SPECIAL:
            out.append(f"<{p}>")
        else:
            raise ValueError(f"无法识别的按键: {p}")
    return "+".join(out)


class GlobalHotkey(QObject):
    triggered = Signal()

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._hk = None

    def start(self, combo: str) -> bool:
        """注册全局热键, 成功返回 True。"""
        self.stop()
        if not supported():
            log.warning("Wayland 会话不支持应用内全局热键, 请使用桌面环境的自定义快捷键")
            return False
        try:
            from pynput import keyboard
            pattern = to_pynput(combo)
            self._hk = keyboard.GlobalHotKeys({pattern: self._fire})
            self._hk.start()
            log.info("全局热键已注册: %s (%s)", combo, pattern)
            return True
        except Exception:
            log.exception("注册全局热键失败: %s", combo)
            self._hk = None
            return False

    def stop(self) -> None:
        if self._hk is not None:
            try:
                self._hk.stop()
            except Exception:
                pass
            self._hk = None

    def _fire(self) -> None:
        self.triggered.emit()
