"""系统托盘: 绿/红/灰状态图标 + 右键菜单。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import icons


class Tray(QSystemTrayIcon):
    showRequested = Signal()
    settingsRequested = Signal()
    quitRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setIcon(icons.tray_icon(None))
        self.setToolTip("CopyAny")

        menu = QMenu()
        act_show = menu.addAction("显示面板")
        act_show.triggered.connect(self.showRequested)
        act_settings = menu.addAction("设置")
        act_settings.triggered.connect(self.settingsRequested)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quitRequested)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.showRequested.emit()

    def set_status(self, online: int, total: int) -> None:
        if total == 0:
            self.setIcon(icons.tray_icon(None))
            self.setToolTip("CopyAny — 未配置对端设备")
        else:
            self.setIcon(icons.tray_icon(online > 0))
            self.setToolTip(f"CopyAny — 已连接 {online}/{total} 台设备")
