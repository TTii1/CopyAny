"""剪贴板监控: 基于 Qt QClipboard (Windows / Linux X11 均可靠)。

注意: GNOME Wayland 会话下系统不允许后台窗口读取剪贴板, 监控会受限 ——
这是桌面环境的强制限制, 任何应用都一样, 建议改用 "Ubuntu on Xorg" 登录(见 README)。
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, Signal
from PySide6.QtGui import QGuiApplication, QImage

from . import store as store_mod

log = logging.getLogger(__name__)

MAX_TEXT_CHARS = 1_000_000          # 单条文本上限
MAX_IMAGE_BYTES = 30 * 1024 * 1024  # 单张图片 PNG 编码后上限


class ClipboardMonitor(QObject):
    """监听系统剪贴板变化, 发出 (kind, content) 信号; content 为 utf-8 文本或 PNG 字节。"""

    new_item = Signal(str, bytes)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._clip = QGuiApplication.clipboard()
        self._last_hash: str | None = None   # 防自激: 我们自己写入的内容不再收录
        self._clip.dataChanged.connect(self._on_change)

    # ---- 面板点选后写回系统剪贴板 ----
    def set_content(self, kind: str, content: bytes) -> bool:
        self._last_hash = store_mod.digest(content)
        if kind == store_mod.KIND_TEXT:
            self._clip.setText(content.decode("utf-8", "replace"))
            return True
        img = QImage()
        img.loadFromData(content, "PNG")
        if img.isNull():
            return False
        self._clip.setImage(img)
        return True

    # ---- 内部 ----
    def _on_change(self) -> None:
        try:
            md = self._clip.mimeData()
            if md.hasImage():
                img = self._clip.image()
                if img.isNull():
                    return
                ba = QByteArray()
                buf = QBuffer(ba)
                buf.open(QIODevice.OpenModeFlag.WriteOnly)
                if not img.save(buf, "PNG"):
                    return
                buf.close()
                data = bytes(ba)
                if not data or len(data) > MAX_IMAGE_BYTES:
                    return
                self._emit(store_mod.KIND_IMAGE, data)
            elif md.hasText():
                text = self._clip.text()
                if not text or not text.strip():
                    return
                if len(text) > MAX_TEXT_CHARS:
                    text = text[:MAX_TEXT_CHARS]
                self._emit(store_mod.KIND_TEXT, text.encode("utf-8"))
        except Exception:
            log.exception("读取剪贴板失败")

    def _emit(self, kind: str, data: bytes) -> None:
        h = store_mod.digest(data)
        if h == self._last_hash:      # 与上次内容相同(含我们自己写入的)则跳过
            return
        self._last_hash = h
        self.new_item.emit(kind, data)
