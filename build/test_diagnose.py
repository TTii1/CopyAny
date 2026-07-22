"""diagnose.probe_peer 全场景测试: 成功 / 密钥错 / 群组错 / 端口未开 / 假服务 / 假静默。

运行: .venv/Scripts/python.exe build/test_diagnose.py
"""
import json
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication

from copyany import diagnose
from copyany.net import Node
from copyany.store import Store

GROUP, KEY = "test-group", "key123456"
PORT = 19577

PASS, FAIL = 0, 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}  {detail}")


def make_node(port: int, group: str = GROUP, key: str = KEY) -> Node:
    db = Path(tempfile.mkdtemp()) / "t.db"
    node = Node({"group_id": group, "shared_key": key,
                 "listen": {"host": "127.0.0.1", "port": port}, "peers": []},
                Store(str(db), 100))
    node.start()
    return node


def fake_server(port: int, mode: str) -> threading.Thread:
    """mode='garbage' 发乱数据; mode='silent' 收连接后不说话。"""
    def run():
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", port))
        srv.listen(4)
        srv.settimeout(15)
        try:
            while True:
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    break
                if mode == "garbage":
                    conn.sendall(b"HTTP/1.1 200 OK\r\n\r\nhello")
                conn.settimeout(12)
                try:
                    while conn.recv(1024):  # 静默模式: 一直收到对方断开为止
                        pass
                except OSError:
                    pass
                conn.close()
        finally:
            srv.close()
    t = threading.Thread(target=run, daemon=True)
    t.start()
    time.sleep(0.3)
    return t


def main() -> int:
    app = QCoreApplication(sys.argv)  # Node 是 QObject, 需要事件循环环境
    node = make_node(PORT)
    time.sleep(0.5)

    # 1. 成功
    r = diagnose.probe_peer("127.0.0.1", PORT, GROUP, KEY)
    check("正常连接: 认证通过", r["ok"], str(r))
    check("正常连接: 四步全过", all(s["ok"] for s in r["steps"]), str(r["steps"]))

    # 2. 密钥不一致
    r = diagnose.probe_peer("127.0.0.1", PORT, GROUP, "wrong-key-99")
    check("密钥错误: 失败", not r["ok"])
    check("密钥错误: 停在认证步", r["steps"][3]["ok"] is False, str(r["steps"]))
    check("密钥错误: 指出密钥不一致", "密钥" in r["summary"], r["summary"])
    check("密钥错误: 有建议", bool(r["advice"]))

    # 3. 群组不一致
    r = diagnose.probe_peer("127.0.0.1", PORT, "other-group", KEY)
    check("群组错误: 失败", not r["ok"])
    check("群组错误: 停在握手步", r["steps"][2]["ok"] is False, str(r["steps"]))
    check("群组错误: 指出群组不一致", "群组" in r["summary"], r["summary"])

    # 4. 端口未监听(连接被拒绝)
    r = diagnose.probe_peer("127.0.0.1", 19999, GROUP, KEY, timeout=3)
    check("端口未开: 失败", not r["ok"])
    check("端口未开: 停在 TCP 步", r["steps"][1]["ok"] is False, str(r["steps"]))
    check("端口未开: 指出拒绝/未监听", "拒绝" in r["summary"], r["summary"])
    check("端口未开: 建议提到 CopyAny 未启动", any("启动" in a for a in r["advice"]), str(r["advice"]))

    # 5. 假服务(端口被其他程序占用, 发垃圾数据)
    fake_server(19578, "garbage")
    r = diagnose.probe_peer("127.0.0.1", 19578, GROUP, KEY, timeout=3)
    check("假服务: 失败", not r["ok"])
    check("假服务: 指出不是 CopyAny", "不是 CopyAny" in r["summary"] or "无法识别" in r["summary"],
          r["summary"])

    # 6. 静默服务(收连接但不回应)
    fake_server(19579, "silent")
    r = diagnose.probe_peer("127.0.0.1", 19579, GROUP, KEY, timeout=2)
    check("静默服务: 失败", not r["ok"])
    check("静默服务: 指出不回应", "不回应" in r["summary"], r["summary"])

    # 7. 本机自检
    steps = diagnose.local_checks({"listen": {"port": PORT}, "peers": []}, node)
    by_name = {s["name"]: s for s in steps}
    check("本机自检: 监听正常", by_name["本机监听"]["ok"] is True, str(steps))
    check("本机自检: 提示未配对端", by_name["对端配置"]["ok"] is False, str(steps))
    check("本机自检: 给出本机 IP", by_name["本机 IP"]["ok"] is True, str(steps))

    node.stop()
    print(f"\n结果: {PASS} 通过, {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
