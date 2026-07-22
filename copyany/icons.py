"""运行时用 QPainter 生成应用图标与托盘状态图标, 无需打包图片资源。
设计: 蓝色圆角方块 + 白色剪贴板图形; 托盘图标右下角叠加绿/灰/红状态点。
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ACCENT = "#4f8cff"
GREEN = "#3fb950"
RED = "#f85149"
GRAY = "#8a919e"


def app_pixmap(size: int = 64) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    m = size * 0.06
    path = QPainterPath()
    path.addRoundedRect(QRectF(m, m, size - 2 * m, size - 2 * m), size * 0.22, size * 0.22)
    p.fillPath(path, QBrush(QColor(ACCENT)))
    # 剪贴板白板
    w, h = size * 0.42, size * 0.50
    x, y = (size - w) / 2, size * 0.30
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("white"))
    p.drawRoundedRect(QRectF(x, y, w, h), size * 0.04, size * 0.04)
    # 顶部夹子
    cw = size * 0.20
    p.drawRoundedRect(QRectF((size - cw) / 2, y - size * 0.05, cw, size * 0.10),
                      size * 0.03, size * 0.03)
    # 板上两行"文字"
    p.setBrush(QColor(ACCENT))
    lw, lh = w * 0.62, max(2.0, size * 0.035)
    lx = x + (w - lw) / 2
    p.drawRoundedRect(QRectF(lx, y + h * 0.30, lw, lh), lh / 2, lh / 2)
    p.drawRoundedRect(QRectF(lx, y + h * 0.52, lw * 0.7, lh), lh / 2, lh / 2)
    p.end()
    return pm


def app_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_pixmap(s))
    return icon


def tray_icon(status: bool | None) -> QIcon:
    """status: True=已连接(绿) False=配置了但对端离线(红) None=未配置对端(灰)"""
    size = 48
    pm = app_pixmap(size)
    color = GREEN if status is True else (RED if status is False else GRAY)
    d = 17
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#16181d"), 3))
    p.setBrush(QColor(color))
    p.drawEllipse(size - d - 1, size - d - 1, d, d)
    p.end()
    return QIcon(pm)


def badge_pixmap(text: str, size: int = 56, bg: str = "#3a4152", fg: str = "#cdd3dd") -> QPixmap:
    """文本记录的占位图标: 圆角方块 + 居中单字。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.18, size * 0.18)
    p.fillPath(path, QBrush(QColor(bg)))
    p.setPen(QPen(QColor(fg)))
    font = p.font()
    font.setPixelSize(int(size * 0.44))
    font.setBold(True)
    p.setFont(font)
    p.drawText(QRectF(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, text)
    p.end()
    return pm


def rounded_image(data: bytes, size: int = 56) -> QPixmap:
    """PNG 字节 -> 居中裁剪的正方形圆角缩略图。"""
    src = QPixmap()
    src.loadFromData(data, "PNG")
    if src.isNull():
        return badge_pixmap("图", size)
    src = src.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                     Qt.TransformationMode.SmoothTransformation)
    x = max(0, (src.width() - size) // 2)
    y = max(0, (src.height() - size) // 2)
    crop = src.copy(x, y, min(size, src.width()), min(size, src.height()))
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), size * 0.14, size * 0.14)
    p.setClipPath(path)
    p.drawPixmap(0, 0, crop)
    p.end()
    return out
