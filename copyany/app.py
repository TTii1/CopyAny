"""应用装配: 配置 -> 存储 -> 网络同步 -> 剪贴板监控 -> 热键 -> 面板/托盘。"""
from __future__ import annotations

import getpass
import logging

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QLocalServer
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from . import config, paster
from .clipmon import ClipboardMonitor
from .gui import theme
from .gui.dialogs import SettingsDialog
from .gui.panel import Panel
from .gui.tray import Tray
from .hotkey import GlobalHotkey, supported as hotkey_supported
from .icons import app_icon
from .net import Node
from .store import Store

log = logging.getLogger(__name__)

PASTE_DELAY_MS = 350  # 隐藏面板后等焦点回到目标窗口再模拟 Ctrl+V


def instance_name() -> str:
    return f"copyany-{getpass.getuser()}"


class CopyAnyApp(QObject):
    def __init__(self, qapp: QApplication, first_run: bool = False):
        super().__init__()
        self.qapp = qapp
        qapp.setQuitOnLastWindowClosed(False)
        qapp.setApplicationName("CopyAny")
        qapp.setWindowIcon(app_icon())
        theme.apply(qapp)

        self.cfg, _created = config.load()
        self.store = Store(config.db_path(), self.cfg["history"]["max_items"])
        self.node = Node(self.cfg, self.store)
        self.monitor = ClipboardMonitor()
        self.panel = Panel(self.store)
        self.tray = Tray()
        self.hotkey = GlobalHotkey()

        # 本机复制 -> 入库 -> 广播
        self.monitor.new_item.connect(self._on_local_item)
        # 收到对端记录 -> 刷新面板
        self.node.itemsChanged.connect(self.panel.reload)
        # 对端实时推送 -> 可选自动写入本机剪贴板
        self.node.remoteItemReceived.connect(self._on_remote_item)
        # 连接状态 -> 托盘 + 面板状态栏
        self.node.peerStatusChanged.connect(self._on_peer_status)
        # 面板/托盘交互
        self.panel.pasteRequested.connect(self._paste_row)
        self.panel.settingsRequested.connect(self.open_settings)
        self.panel.autoReceiveToggled.connect(self._on_auto_receive_toggled)
        self.tray.showRequested.connect(self.panel.toggle)
        self.tray.settingsRequested.connect(self.open_settings)
        self.tray.quitRequested.connect(self.quit)
        self.hotkey.triggered.connect(self.panel.toggle)

        self._start_instance_server()
        self.node.start()
        self._apply_hotkey()
        self._on_peer_status(0, len(self.node.peers))
        self.panel.set_auto_receive(self._auto_receive())
        if self.node.listen_error:
            self.tray.showMessage("CopyAny", f"端口 {self.node.listen_port} 监听失败: "
                                  f"{self.node.listen_error}",
                                  QSystemTrayIcon.MessageIcon.Warning, 5000)

        self.tray.show()
        if first_run:
            log.info("首次运行, 已生成默认配置: %s", config.config_path())
            self.panel.show_front()

    # ---------- 剪贴板 ----------

    def _on_local_item(self, kind: str, content: bytes) -> None:
        h, is_new = self.store.add(kind, content)
        if is_new:
            log.debug("新记录入库并广播: %s", h[:8])
            self.node.broadcast_have(h)
        self.panel.reload()

    def _paste_row(self, row: dict) -> None:
        """双击/回车: 写剪贴板 -> 隐藏面板 -> 模拟 Ctrl+V。"""
        full = self.store.get(row["hash"])
        if not full:
            return
        if not self.monitor.set_content(full["kind"], full["content"]):
            self.tray.showMessage("CopyAny", "写入剪贴板失败(内容可能已损坏)",
                                  QSystemTrayIcon.MessageIcon.Warning, 3000)
            return
        self.panel.hide()
        QTimer.singleShot(PASTE_DELAY_MS, self._do_paste)

    def _do_paste(self) -> None:
        if not paster.simulate_paste():
            self.tray.showMessage("CopyAny", "已写入剪贴板, 请手动 Ctrl+V 粘贴",
                                  QSystemTrayIcon.MessageIcon.Information, 3000)

    # ---------- 状态 / 设置 ----------

    def _auto_receive(self) -> bool:
        return bool((self.cfg.get("clipboard") or {}).get("auto_receive", False))

    def _on_remote_item(self, kind: str, content: bytes) -> None:
        """对端实时推送的新记录: 开关开启时直接写入本机剪贴板。
        set_content 会记录哈希防自激, 不会二次入库/广播; 上线补齐的历史不经过此路径。"""
        if not self._auto_receive():
            return
        if self.monitor.set_content(kind, content):
            log.info("对端复制内容已写入本机剪贴板, 可直接 Ctrl+V 粘贴")
        else:
            log.warning("对端内容写入剪贴板失败(内容可能已损坏)")

    def _on_auto_receive_toggled(self, on: bool) -> None:
        self.cfg.setdefault("clipboard", {})["auto_receive"] = on
        config.save(self.cfg)
        self.panel.set_auto_receive(on)
        log.info("剪贴板自动接收: %s", "开启" if on else "关闭")

    def _on_peer_status(self, online: int, total: int) -> None:
        self.tray.set_status(online, total)
        self.panel.set_peer_status(online, total)

    def _apply_hotkey(self) -> None:
        combo = str(self.cfg["hotkey"]["key"])
        ok = self.hotkey.start(combo)
        self.panel.set_hotkey_text(combo, ok or not hotkey_supported())

    def open_settings(self) -> None:
        dlg = SettingsDialog(self.cfg, node=self.node, parent=self.panel)
        dlg.configSaved.connect(self._apply_config)
        dlg.exec()

    def _apply_config(self, cfg: dict) -> None:
        self.cfg = cfg
        config.save(cfg)
        self.store.max_items = int(cfg["history"]["max_items"])
        self._apply_hotkey()
        # 网络层重启使 群组/密钥/端口/对端 生效
        self.node.stop()
        self.node.deleteLater()
        self.node = Node(cfg, self.store)
        self.node.itemsChanged.connect(self.panel.reload)
        self.node.remoteItemReceived.connect(self._on_remote_item)
        self.node.peerStatusChanged.connect(self._on_peer_status)
        self.node.start()
        self._on_peer_status(0, len(self.node.peers))
        self.panel.set_auto_receive(self._auto_receive())
        log.info("配置已保存并生效")
        self.tray.showMessage("CopyAny", "设置已保存", QSystemTrayIcon.MessageIcon.Information, 2000)

    # ---------- 单实例 ----------

    def _start_instance_server(self) -> None:
        """`copyany --show`(或重复启动)会通过本地套接字通知本进程显示面板。"""
        self._server = QLocalServer(self)
        QLocalServer.removeServer(instance_name())   # 清理异常退出残留
        if self._server.listen(instance_name()):
            self._server.newConnection.connect(self._on_instance_conn)
        else:
            log.warning("单实例监听失败: %s", self._server.errorString())

    def _on_instance_conn(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock:
            sock.disconnectFromServer()
        self.panel.show_front()

    # ---------- 退出 ----------

    def quit(self) -> None:
        log.info("退出 CopyAny")
        self.hotkey.stop()
        self.node.stop()
        self.tray.hide()
        self.qapp.quit()
