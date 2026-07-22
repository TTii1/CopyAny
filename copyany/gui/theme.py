"""全局暗色主题。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

QSS = """
* { font-family: "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", "Noto Sans", sans-serif; }
QWidget { background: #16181d; color: #e6e8eb; font-size: 14px; }

/* 搜索框 */
QLineEdit#search {
    background: #1f2229; border: 1px solid #2e323c; border-radius: 10px;
    padding: 10px 14px; font-size: 15px;
}
QLineEdit#search:focus { border-color: #4f8cff; }

/* 历史列表 */
QListWidget#history { background: transparent; border: none; outline: none; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #343945; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #454c5c; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

/* 记录卡片 */
QFrame#card { background: #1f2229; border: 1px solid #262a33; border-radius: 10px; }
QFrame#card:hover { background: #262a33; border-color: #333947; }
QFrame#card[selected="true"] { border-color: #4f8cff; }
QLabel#preview { color: #e6e8eb; font-size: 14px; background: transparent; }
QLabel#meta { color: #7d8590; font-size: 12px; background: transparent; }
QToolButton.cardBtn {
    background: transparent; border: none; border-radius: 6px;
    color: #8a919e; font-size: 15px; padding: 4px 7px;
}
QToolButton.cardBtn:hover { background: #333947; color: #e6e8eb; }
QToolButton#pinBtn[on="true"] { color: #f0b429; }
QToolButton#delBtn:hover { background: #433; color: #f85149; }

/* 按钮 */
QPushButton#primary {
    background: #4f8cff; border: none; border-radius: 8px; padding: 8px 20px; color: white;
}
QPushButton#primary:hover { background: #5f99ff; }
QPushButton#primary:pressed { background: #3f7aee; }
QPushButton#ghost {
    background: transparent; border: 1px solid #333947; border-radius: 8px;
    padding: 8px 20px; color: #c9cdd4;
}
QPushButton#ghost:hover { background: #262a33; }
QPushButton#ghost[on="true"] { color: #7ee787; border-color: #2f6f3e; }

QLabel#status { color: #7d8590; font-size: 12px; }
QLabel#empty { color: #5b626e; font-size: 14px; }
QLabel#hint { color: #b98a2f; font-size: 12px; }
QLabel#fieldLabel { color: #aeb4bf; }

/* 设置对话框控件 */
QDialog { background: #16181d; }
QLineEdit, QSpinBox, QPlainTextEdit, QKeySequenceEdit {
    background: #1f2229; border: 1px solid #2e323c; border-radius: 8px;
    padding: 7px 10px; selection-background-color: #4f8cff;
}
QLineEdit:focus, QSpinBox:focus, QPlainTextEdit:focus, QKeySequenceEdit:focus {
    border-color: #4f8cff;
}
QSpinBox::up-button, QSpinBox::down-button { width: 18px; border: none; }
QCheckBox { spacing: 6px; }
QCheckBox::indicator { width: 16px; height: 16px; }

/* 托盘菜单 / 提示 */
QMenu { background: #1f2229; border: 1px solid #2e323c; padding: 6px; }
QMenu::item { padding: 7px 26px; border-radius: 6px; }
QMenu::item:selected { background: #4f8cff; color: white; }
QMenu::separator { height: 1px; background: #2e323c; margin: 5px 10px; }
QToolTip { background: #262a33; color: #e6e8eb; border: 1px solid #333947; padding: 5px 9px; }
QMessageBox QPushButton { min-width: 76px; }
"""


def apply(app: QApplication) -> None:
    app.setStyleSheet(QSS)
