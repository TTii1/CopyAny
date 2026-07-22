"""设置对话框: 修改全部配置, 保存后即时生效; 内置连接测试(逐步诊断失败原因)。"""
from __future__ import annotations

import threading

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout,
                               QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox,
                               QVBoxLayout)

from .. import diagnose


class SettingsDialog(QDialog):
    configSaved = Signal(dict)
    _testDone = Signal(object)  # 诊断线程 -> GUI 线程

    def __init__(self, cfg: dict, node=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("CopyAny 设置")
        self.setMinimumWidth(460)
        self._node = node
        self._testing = False
        self._device_id = str(cfg.get("device_id") or "")   # 设备标识随配置保存, 不能丢

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)
        root.addLayout(form)

        self.group_edit = QLineEdit(str(cfg.get("group_id", "my-group")))
        form.addRow("群组 ID", self.group_edit)

        key_row = QVBoxLayout()
        self.key_edit = QLineEdit(str(cfg.get("shared_key", "")))
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("至少 8 位, 同群组所有设备必须一致")
        key_row.addWidget(self.key_edit)
        self.show_key = QCheckBox("显示密钥")
        self.show_key.toggled.connect(
            lambda on: self.key_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        key_row.addWidget(self.show_key)
        form.addRow("共享密钥", key_row)

        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(int((cfg.get("listen") or {}).get("port", 9527)))
        form.addRow("监听端口", self.port_spin)

        self.peers_edit = QPlainTextEdit()
        self.peers_edit.setPlaceholderText("每行一个对端, 格式: IP:端口\n例如:\n192.168.1.100:9527\n192.168.1.101")
        lines = [f"{p['host']}:{p['port']}" for p in cfg.get("peers") or []]
        self.peers_edit.setPlainText("\n".join(lines))
        self.peers_edit.setFixedHeight(96)
        form.addRow("对端设备", self.peers_edit)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(10, 100000)
        self.max_spin.setValue(int((cfg.get("history") or {}).get("max_items", 1000)))
        form.addRow("历史上限", self.max_spin)

        self.hotkey_edit = QKeySequenceEdit()
        hotkey = str((cfg.get("hotkey") or {}).get("key", "ctrl+q"))
        self.hotkey_edit.setKeySequence(QKeySequence(hotkey))
        form.addRow("全局快捷键", self.hotkey_edit)

        self.auto_receive = QCheckBox("对端复制的内容自动写入本机剪贴板(直接 Ctrl+V)")
        self.auto_receive.setToolTip("与面板底部的\"同步剪贴板\"开关是同一个设置")
        self.auto_receive.setChecked(bool((cfg.get("clipboard") or {}).get("auto_receive", False)))
        form.addRow("剪贴板同步", self.auto_receive)

        # ---- 连接测试 ----
        test_row = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setObjectName("ghost")
        self.test_btn.setToolTip("用当前填写的配置(无需先保存)逐个探测对端,\n"
                                 "失败时给出具体原因: 防火墙未放行 / 对方未启动 / 密钥不一致等")
        self.test_btn.clicked.connect(self._run_test)
        test_row.addWidget(self.test_btn)
        test_hint = QLabel("两台电脑连不上时点这里, 会逐项指出原因")
        test_hint.setStyleSheet("color: #888;")
        test_row.addWidget(test_hint, 1)
        form.addRow("连接测试", test_row)

        self.test_out = QPlainTextEdit()
        self.test_out.setReadOnly(True)
        self.test_out.setPlaceholderText("测试结果会显示在这里")
        self.test_out.setVisible(False)
        self.test_out.setFixedHeight(190)
        root.addWidget(self.test_out)
        self._testDone.connect(self._render_test)

        buttons = QDialogButtonBox()
        save_btn = buttons.addButton("保存", QDialogButtonBox.ButtonRole.AcceptRole)
        save_btn.setObjectName("primary")
        cancel_btn = buttons.addButton("取消", QDialogButtonBox.ButtonRole.RejectRole)
        cancel_btn.setObjectName("ghost")
        buttons.accepted.connect(self._on_save)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _collect(self) -> dict | None:
        """读取当前表单内容并校验; 非法时弹窗提示并返回 None。"""
        group_id = self.group_edit.text().strip()
        shared_key = self.key_edit.text()
        if not group_id:
            QMessageBox.warning(self, "CopyAny", "群组 ID 不能为空")
            return None
        if len(shared_key) < 8:
            QMessageBox.warning(self, "CopyAny", "共享密钥至少 8 位")
            return None
        peers = []
        for line in self.peers_edit.toPlainText().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            host, _, port = line.partition(":")
            host = host.strip()
            if not host:
                continue
            try:
                peers.append({"host": host, "port": int(port) if port else 9527})
            except ValueError:
                QMessageBox.warning(self, "CopyAny", f"对端格式错误: {line}\n应为 IP:端口, 如 192.168.1.100:9527")
                return None
        hotkey = self.hotkey_edit.keySequence().toString(QKeySequence.SequenceFormat.NativeText)
        cfg = {
            "group_id": group_id,
            "shared_key": shared_key,
            "listen": {"host": "0.0.0.0", "port": self.port_spin.value()},
            "peers": peers,
            "history": {"max_items": self.max_spin.value()},
            "hotkey": {"key": hotkey.lower() or "ctrl+q"},
            "clipboard": {"auto_receive": self.auto_receive.isChecked()},
        }
        if self._device_id:
            cfg["device_id"] = self._device_id
        return cfg

    def _on_save(self) -> None:
        cfg = self._collect()
        if cfg is None:
            return
        self.configSaved.emit(cfg)
        self.accept()

    # ---------- 连接测试 ----------

    def _run_test(self) -> None:
        if self._testing:
            return
        cfg = self._collect()
        if cfg is None:
            return
        if not cfg["peers"]:
            self.test_out.setVisible(True)
            self.test_out.setPlainText(
                "未填写任何对端设备。\n\n至少一方需要把对方的 IP:端口 填进\"对端设备\"; "
                "两端互填最稳妥。\n本机 IP: " + (", ".join(diagnose.local_ips()) or "未获取"))
            return
        self._testing = True
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中…")
        self.test_out.setVisible(True)
        self.test_out.setPlainText("正在逐项探测, 请稍候…")
        self.adjustSize()
        node = self._node
        t = threading.Thread(target=self._test_worker, args=(cfg, node),
                             name="copyany-test", daemon=True)
        t.start()

    def _test_worker(self, cfg: dict, node) -> None:
        """后台线程: 本机自检 + 逐个探测对端。"""
        report: dict = {"local": diagnose.local_checks(cfg, node), "peers": []}
        for p in cfg["peers"]:
            report["peers"].append(diagnose.probe_peer(
                p["host"], p["port"], cfg["group_id"], cfg["shared_key"]))
        self._testDone.emit(report)

    @staticmethod
    def _mark(ok: bool | None) -> str:
        return "✔" if ok else ("✖" if ok is False else "•")

    def _render_test(self, report: dict) -> None:
        self._testing = False
        self.test_btn.setEnabled(True)
        self.test_btn.setText("测试连接")
        lines: list[str] = []
        lines.append("━━ 本机 ━━")
        for s in report.get("local", []):
            lines.append(f"{self._mark(s['ok'])} {s['name']}"
                         + (f": {s['detail']}" if s.get("detail") else ""))
        for r in report.get("peers", []):
            lines.append("")
            lines.append(f"━━ 对端 {r['peer']} ━━")
            for s in r["steps"]:
                if s["ok"] is None:
                    continue
                lines.append(f"{self._mark(s['ok'])} {s['name']}"
                             + (f"  {s['detail']}" if s.get("detail") else ""))
            if r["ok"]:
                lines.append(f"✔ {r['summary']}")
            else:
                lines.append(f"✖ 结论: {r['summary']}")
                lines.append("  建议:")
                for a in r.get("advice", []):
                    lines.append(f"    · {a}")
        self.test_out.setPlainText("\n".join(lines))
        self.adjustSize()
