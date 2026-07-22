"""历史记录卡片控件与辅助函数。"""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QToolButton, QVBoxLayout

from .. import icons
from ..store import KIND_IMAGE


def fmt_time(ts: float) -> str:
    diff = time.time() - ts
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff // 3600)} 小时前"
    if diff < 7 * 86400:
        return f"{int(diff // 86400)} 天前"
    return time.strftime("%m-%d %H:%M", time.localtime(ts))


def fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


class ItemCard(QFrame):
    """单条历史记录: 缩略图 + 预览 + 元信息 + 置顶/删除按钮。"""

    pasteRequested = Signal(dict)
    pinToggled = Signal(str, bool)
    deleteRequested = Signal(str)
    clicked = Signal(dict)

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.row = row
        self.setObjectName("card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 8, 8)
        layout.setSpacing(12)

        # 左侧: 缩略图 / 文本图标
        thumb = QLabel()
        thumb.setFixedSize(56, 56)
        if row["kind"] == KIND_IMAGE:
            thumb.setPixmap(icons.rounded_image(bytes(row["content"]), 56))
        else:
            thumb.setPixmap(icons.badge_pixmap("文", 56))
        layout.addWidget(thumb)

        # 中间: 预览 + 元信息
        mid = QVBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(4)
        preview = row["preview"] or ("[图片]" if row["kind"] == KIND_IMAGE else "")
        if row["kind"] == KIND_IMAGE:
            preview = f"{preview} · {fmt_size(len(row['content']))}"
        self.preview_label = QLabel(preview[:120] + ("…" if len(preview) > 120 else ""))
        self.preview_label.setObjectName("preview")
        if row["kind"] != KIND_IMAGE:
            full = row["content"].decode("utf-8", "replace")
            self.preview_label.setToolTip(full[:2000])
        else:
            self.preview_label.setToolTip("双击粘贴这张图片")
        mid.addWidget(self.preview_label)

        meta_parts = ["图片" if row["kind"] == KIND_IMAGE else "文本", fmt_time(row["created_at"])]
        if row.get("source"):
            meta_parts.append(f"来自 {row['source']}")
        meta = QLabel(" · ".join(meta_parts))
        meta.setObjectName("meta")
        mid.addWidget(meta)
        layout.addLayout(mid, 1)

        # 右侧: 置顶 / 删除
        self.pin_btn = QToolButton()
        self.pin_btn.setObjectName("pinBtn")
        self.pin_btn.setProperty("class", "cardBtn")
        self.pin_btn.setText("★")
        self.pin_btn.setToolTip("置顶 / 取消置顶")
        self._set_pin_visual(bool(row["pinned"]))
        self.pin_btn.clicked.connect(self._on_pin)
        layout.addWidget(self.pin_btn, 0, Qt.AlignmentFlag.AlignVCenter)

        del_btn = QToolButton()
        del_btn.setObjectName("delBtn")
        del_btn.setProperty("class", "cardBtn")
        del_btn.setText("✕")
        del_btn.setToolTip("删除这条记录")
        del_btn.clicked.connect(lambda: self.deleteRequested.emit(self.row["hash"]))
        layout.addWidget(del_btn, 0, Qt.AlignmentFlag.AlignVCenter)

    def _set_pin_visual(self, pinned: bool) -> None:
        self.pin_btn.setProperty("on", "true" if pinned else "false")
        self.pin_btn.style().unpolish(self.pin_btn)
        self.pin_btn.style().polish(self.pin_btn)

    def _on_pin(self) -> None:
        self.pinToggled.emit(self.row["hash"], not bool(self.row["pinned"]))

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.row)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pasteRequested.emit(self.row)
        super().mouseDoubleClickEvent(event)
