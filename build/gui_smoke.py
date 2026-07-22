"""GUI 冒烟测试(离屏): 实例化完整应用, 走一遍 入库->刷新->粘贴->设置 的代码路径。
运行: QT_QPA_PLATFORM=offscreen python build/gui_smoke.py

注意: 必须使用隔离的配置目录与空闲端口 —— 直接跑会覆盖本机真实 config.yaml,
并与正在运行的 CopyAny 实例抢占端口导致"测试连接"误判。
"""
import os
import socket
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from copyany import config  # noqa: E402
from copyany.app import CopyAnyApp  # noqa: E402
from copyany.gui.dialogs import SettingsDialog  # noqa: E402

failures = []


def check(name, fn):
    try:
        fn()
        print(f"[PASS] {name}")
    except Exception as e:  # noqa: BLE001
        failures.append(name)
        import traceback
        traceback.print_exc()
        print(f"[FAIL] {name}: {e}")


def main() -> int:
    # 隔离配置目录 + 空闲端口: 不碰本机真实 config.yaml, 也不与正在运行的 CopyAny 抢 9527
    tmp = tempfile.mkdtemp(prefix="copyany-smoke-")
    os.environ["APPDATA"] = tmp          # Windows 配置根目录
    os.environ["XDG_CONFIG_HOME"] = tmp  # Linux 配置根目录
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    config.config_dir().mkdir(parents=True, exist_ok=True)
    config.config_path().write_text(yaml.safe_dump({
        "group_id": "smoke-group",
        "shared_key": "smoke-key-123456",
        "listen": {"host": "127.0.0.1", "port": free_port},
        "peers": [],
        "history": {"max_items": 100},
        "hotkey": {"key": "ctrl+q"},
        "clipboard": {"auto_receive": False},
    }, allow_unicode=True), encoding="utf-8")

    qapp = QApplication([])
    app_holder = {}

    def build_app():
        app_holder["app"] = CopyAnyApp(qapp, first_run=False)

    check("应用装配 (配置/存储/网络/托盘/面板)", build_app)
    app = app_holder["app"]

    def feed_items():
        app._on_local_item("text", "第一段测试文字 hello copyany".encode())
        app._on_local_item("text", "https://example.com/some/link".encode())
        assert app.store.count() >= 2

    check("入库 + 面板刷新", feed_items)

    def search_filter():
        app.panel.search.setText("copyany")
        assert app.panel.list.count() >= 1
        app.panel.search.setText("")
        app.panel.reload()

    check("搜索过滤", search_filter)

    def show_panel():
        app.panel.show_front()
        app.panel.toggle()
        app.panel.toggle()

    check("面板显示/切换", show_panel)

    def paste_flow():
        rows = app.store.list()
        app._paste_row(rows[0])          # 离屏环境 set_content 可能失败, 但不许抛异常
        app._do_paste()

    check("粘贴流程(写剪贴板+模拟按键)", paste_flow)

    def double_click_once():
        # 双击卡片应只触发一次 pasteRequested(回归: 卡片与列表双击信号曾重复触发)
        from PySide6.QtCore import QPointF, Qt as _Qt
        from PySide6.QtGui import QMouseEvent, QPointingDevice
        app.panel.show_front()
        hits = {"n": 0}

        def count_hit(_row):
            hits["n"] += 1

        app.panel.pasteRequested.connect(count_hit)
        try:
            item = app.panel.list.item(0)
            card = app.panel.list.itemWidget(item)
            # 用 postEvent 走完整派发路径: 卡片忽略事件后会透传到列表
            pos = QPointF(card.rect().center())
            ev = QMouseEvent(QMouseEvent.Type.MouseButtonDblClick, pos, pos, pos,
                             _Qt.MouseButton.LeftButton, _Qt.MouseButton.LeftButton,
                             _Qt.KeyboardModifier.NoModifier,
                             QPointingDevice.primaryPointingDevice())
            QApplication.postEvent(card, ev)
            qapp.processEvents()
            assert hits["n"] == 1, f"双击应触发 1 次粘贴, 实际 {hits['n']} 次"
        finally:
            app.panel.pasteRequested.disconnect(count_hit)

    check("双击卡片只粘贴一次(回归)", double_click_once)

    def settings_dialog():
        dlg = SettingsDialog(app.cfg, parent=app.panel)
        dlg.group_edit.setText("smoke-group")
        dlg.key_edit.setText("smoke-key-123")
        dlg.peers_edit.setPlainText("127.0.0.1:19527\n# 注释行\n192.168.1.2")
        saved = {}
        dlg.configSaved.connect(lambda c: saved.update(c))
        dlg._on_save()
        assert saved["peers"] == [{"host": "127.0.0.1", "port": 19527},
                                  {"host": "192.168.1.2", "port": 9527}], saved["peers"]
        assert saved["hotkey"]["key"]
        assert isinstance(saved["clipboard"]["auto_receive"], bool), saved.get("clipboard")
        app._apply_config(saved)         # 网络层热重启

    check("设置对话框解析 + 配置热生效", settings_dialog)

    def settings_test_conn():
        import time
        dlg = SettingsDialog(app.cfg, node=app.node, parent=app.panel)
        dlg.group_edit.setText(app.cfg["group_id"])
        dlg.key_edit.setText(app.cfg["shared_key"])
        dlg.peers_edit.setPlainText(f"127.0.0.1:{app.node.listen_port}")  # 探测本机节点
        dlg._run_test()
        assert dlg.test_out.isVisible() or dlg._testing
        deadline = time.time() + 15
        while dlg._testing and time.time() < deadline:   # 等后台诊断线程回传
            qapp.processEvents()
            time.sleep(0.05)
        qapp.processEvents()
        out = dlg.test_out.toPlainText()
        assert "连接成功" in out, out
        assert "本机" in out and "对端 127.0.0.1" in out, out

    check("设置-测试连接(对本机节点端到端)", settings_test_conn)

    def tray_status():
        app._on_peer_status(1, 2)
        app._on_peer_status(0, 0)

    check("托盘状态切换", tray_status)

    def auto_receive():
        app._on_auto_receive_toggled(False)      # 归一化初态(本机配置文件可能是开)
        assert not app.panel.sync_btn.isChecked()
        app.panel.sync_btn.click()               # 面板底部开关 -> 开
        assert app.cfg["clipboard"]["auto_receive"] is True
        assert app.panel.sync_btn.isChecked()
        app._on_remote_item("text", "对端复制的内容".encode())  # 离屏写剪贴板, 不许抛异常
        app._on_remote_item("image", b"\x89PNG\r\n\x1a\nbroken")  # 坏图片也不许抛异常
        app._on_auto_receive_toggled(False)      # 关
        assert app.cfg["clipboard"]["auto_receive"] is False
        assert not app.panel.sync_btn.isChecked()
        # 设置对话框保存后该配置不丢失
        dlg = SettingsDialog(app.cfg, parent=app.panel)
        saved = {}
        dlg.configSaved.connect(lambda c: saved.update(c))
        dlg._on_save()
        assert saved["clipboard"] == {"auto_receive": False}, saved.get("clipboard")

    check("剪贴板自动接收开关 + 远程内容写入", auto_receive)

    def quit_app():
        app.quit()
        qapp.processEvents()

    check("退出清理", quit_app)

    print(f"\n冒烟测试: {'全部通过' if not failures else f'{len(failures)} 项失败'}")
    print(f"(配置目录: {config.config_dir()})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
