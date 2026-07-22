"""历史面板主窗口: 搜索 + 列表 + 状态栏。默认隐藏, 由全局热键/托盘呼出。"""
from __future__ import annotations

import logging

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from ..hotkey import is_wayland, supported as hotkey_supported
from .widgets import ItemCard

log = logging.getLogger(__name__)

LIST_LIMIT = 100  # 面板一次加载的条数(含图片缩略图, 控制内存)


class _HistoryList(QListWidget):
    enterPressed = Signal()
    deletePressed = Signal()
    escPressed = Signal()

    def keyPressEvent(self, e) -> None:
        key = e.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.enterPressed.emit()
        elif key == Qt.Key.Key_Delete:
            self.deletePressed.emit()
        elif key == Qt.Key.Key_Escape:
            self.escPressed.emit()
        else:
            super().keyPressEvent(e)


class Panel(QWidget):
    pasteRequested = Signal(dict)      # 双击/回车 -> 应用层执行 写剪贴板+模拟粘贴
    settingsRequested = Signal()
    autoReceiveToggled = Signal(bool)  # 底部"同步剪贴板"开关

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._online = 0
        self._total_peers = 0
        self._hotkey_text = "Ctrl+Q"

        self.setWindowTitle("CopyAny")
        self.resize(600, 680)
        self.setMinimumSize(420, 380)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(10)

        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("搜索历史…   ( ↑↓ 选择 · Enter 粘贴 · Esc 关闭 )")
        self.search.installEventFilter(self)
        self.search.setClearButtonEnabled(True)
        root.addWidget(self.search)

        self.empty_label = QLabel("暂无剪贴板历史\n\n复制一段文字或一张图片, 会自动出现在这里")
        self.empty_label.setObjectName("empty")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.empty_label, 1)

        self.list = _HistoryList()
        self.list.setObjectName("history")
        self.list.setSpacing(5)
        self.list.setUniformItemSizes(False)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        root.addWidget(self.list, 1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(2, 0, 2, 0)
        self.status_label = QLabel()
        self.status_label.setObjectName("status")
        bottom.addWidget(self.status_label, 1)
        self.sync_btn = QPushButton()
        self.sync_btn.setObjectName("ghost")
        self.sync_btn.setCheckable(True)
        self.sync_btn.setToolTip("开启后, 其他设备复制的内容会自动写入本机剪贴板,\n"
                                 "无需呼出面板, 直接 Ctrl+V 即可粘贴")
        self.sync_btn.toggled.connect(self.autoReceiveToggled)
        self.set_auto_receive(False)
        bottom.addWidget(self.sync_btn)
        settings_btn = QPushButton("⚙ 设置")
        settings_btn.setObjectName("ghost")
        settings_btn.clicked.connect(self.settingsRequested.emit)
        bottom.addWidget(settings_btn)
        root.addLayout(bottom)

        if is_wayland():
            hint = QLabel("⚠ 当前为 Wayland 会话: 全局热键、后台剪贴板监控与剪贴板自动写入受系统限制, 详见 README")
            hint.setObjectName("hint")
            hint.setWordWrap(True)
            root.addWidget(hint)

        # 信号
        self.search.textChanged.connect(self.reload)
        self.search.returnPressed.connect(self._paste_current)
        # 双击粘贴由卡片(ItemCard.mouseDoubleClickEvent)发出; 若再监听列表的
        # itemDoubleClicked, 双击一次会触发两次粘贴(事件会穿透卡片到达列表)
        self.list.currentItemChanged.connect(self._on_current_changed)
        self.list.enterPressed.connect(self._paste_current)
        self.list.deletePressed.connect(self._delete_current)
        self.list.escPressed.connect(self.hide)

        self.reload()

    # ---------- 数据 ----------

    def reload(self) -> None:
        query = self.search.text().strip()
        keep_hash = None
        cur = self.list.currentItem()
        if cur is not None and cur.data(Qt.ItemDataRole.UserRole):
            keep_hash = cur.data(Qt.ItemDataRole.UserRole)["hash"]

        self.list.blockSignals(True)
        self.list.clear()
        rows = self.store.list(query, LIST_LIMIT)
        restore_row = 0
        for i, row in enumerate(rows):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, {k: row[k] for k in
                         ("hash", "kind", "preview", "pinned", "created_at", "source")})
            card = ItemCard(row)
            card.pasteRequested.connect(self.pasteRequested)
            card.pinToggled.connect(self._on_pin)
            card.deleteRequested.connect(self._on_delete)
            card.clicked.connect(lambda _row, it=item: self.list.setCurrentItem(it))
            item.setSizeHint(card.sizeHint())
            self.list.addItem(item)
            self.list.setItemWidget(item, card)
            if keep_hash and row["hash"] == keep_hash:
                restore_row = i
        if rows:
            self.list.setCurrentRow(restore_row)
        self.list.blockSignals(False)
        self._on_current_changed(self.list.currentItem(), None)

        self.empty_label.setVisible(not rows)
        self.list.setVisible(bool(rows))
        self._update_status()

    def set_peer_status(self, online: int, total: int) -> None:
        self._online, self._total_peers = online, total
        self._update_status()

    def set_hotkey_text(self, text: str, ok: bool) -> None:
        self._hotkey_text = text if ok else f"{text}(未生效)"
        self._update_status()

    def set_auto_receive(self, on: bool) -> None:
        """更新底部"同步剪贴板"开关的显示状态(不触发 autoReceiveToggled)。"""
        self.sync_btn.blockSignals(True)
        self.sync_btn.setChecked(on)
        self.sync_btn.blockSignals(False)
        self.sync_btn.setText(f"⇄ 同步剪贴板: {'开' if on else '关'}")
        self.sync_btn.setProperty("on", "true" if on else "false")
        self.sync_btn.style().unpolish(self.sync_btn)
        self.sync_btn.style().polish(self.sync_btn)

    def _update_status(self) -> None:
        parts = [f"共 {self.store.count()} 条"]
        if self._total_peers:
            parts.append(f"已连接 {self._online}/{self._total_peers} 台设备")
        else:
            parts.append("未配置对端设备")
        if hotkey_supported():
            parts.append(f"{self._hotkey_text} 呼出")
        self.status_label.setText("  ·  ".join(parts))

    # ---------- 行为 ----------

    def show_front(self) -> None:
        """显示并置于前台, 定位到鼠标所在屏幕中央。"""
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
        self.search.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
        self.search.selectAll()
        # 每次呼出都定位到最新一条: 上次关闭前的选中状态没有保留意义,
        # 面板可能隔很久才打开一次, 恢复旧选中只会让人困惑
        if self.list.count():
            self.list.setCurrentRow(0)
            self.list.scrollToTop()

    def toggle(self) -> None:
        if self.isVisible() and self.isActiveWindow():
            self.hide()
        else:
            self.show_front()

    def closeEvent(self, event) -> None:   # 点关闭按钮只隐藏, 退出走托盘
        event.ignore()
        self.hide()

    # ---------- 事件 ----------

    def eventFilter(self, obj, event) -> bool:
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
                self._move_selection(1 if key == Qt.Key.Key_Down else -1)
                return True
            if key == Qt.Key.Key_Escape:
                self.hide()
                return True
        return super().eventFilter(obj, event)

    def _move_selection(self, delta: int) -> None:
        count = self.list.count()
        if not count:
            return
        row = self.list.currentRow()
        row = max(0, min(count - 1, row + delta if row >= 0 or delta > 0 else 0))
        self.list.setCurrentRow(row)

    def _row_of_current(self) -> dict | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _paste_current(self) -> None:
        row = self._row_of_current()
        if row:
            self.pasteRequested.emit(row)

    def _delete_current(self) -> None:
        row = self._row_of_current()
        if row:
            self._on_delete(row["hash"])

    def _on_current_changed(self, current, _previous) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            card = self.list.itemWidget(item)
            if isinstance(card, ItemCard):
                card.set_selected(item is current)

    def _on_pin(self, h: str, pinned: bool) -> None:
        self.store.set_pinned(h, pinned)
        self.reload()

    def _on_delete(self, h: str) -> None:
        self.store.delete(h)
        self.reload()
