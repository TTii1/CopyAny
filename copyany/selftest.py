"""核心功能自检(不依赖 GUI): 加密 / 存储 / 热键解析 / 双节点加密同步。

运行: python run.py --selftest   或   python -m copyany --selftest
"""
from __future__ import annotations

import socket
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, Qt

from . import crypto, hotkey
from .net import Node
from .store import KIND_IMAGE, KIND_TEXT, Store

_results: list[tuple[str, bool, str]] = []


def _check(name: str, fn) -> None:
    try:
        fn()
        _results.append((name, True, ""))
        print(f"[PASS] {name}")
    except Exception as e:  # noqa: BLE001 - 自检需要捕获一切
        _results.append((name, False, str(e)))
        print(f"[FAIL] {name}: {e}")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait(cond, timeout: float = 8.0, interval: float = 0.05) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return True
        time.sleep(interval)
    return False


def _cfg(port: int, peers: list, key: str = "test-key-123456") -> dict:
    return {
        "group_id": "selftest-group",
        "shared_key": key,
        "listen": {"host": "127.0.0.1", "port": port},
        "peers": peers,
        "history": {"max_items": 100},
        "hotkey": {"key": "ctrl+q"},
    }


# ---------- 单项测试 ----------

def test_crypto() -> None:
    key = crypto.derive_key("my-secret-key", "g1")
    blob = crypto.encrypt(key, b"hello \xe4\xb8\xad\xe6\x96\x87")
    assert crypto.decrypt(key, blob) == b"hello \xe4\xb8\xad\xe6\x96\x87"
    wrong = crypto.derive_key("my-secret-key", "g2")
    try:
        crypto.decrypt(wrong, blob)
        raise AssertionError("错误密钥竟然解密成功")
    except ValueError:
        pass
    assert crypto.hmac_hex(key, b"x") == crypto.hmac_hex(key, b"x")
    assert crypto.hmac_hex(key, b"x") != crypto.hmac_hex(key, b"y")


def test_store() -> None:
    # ignore_cleanup_errors: Windows 上 SQLite 句柄释放与临时目录清理存在竞态
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        st = Store(Path(d) / "t.db", max_items=5)
        h1, new1 = st.add(KIND_TEXT, "你好世界".encode())
        assert new1
        h2, new2 = st.add(KIND_TEXT, "你好世界".encode())
        assert h1 == h2 and not new2, "重复内容应去重"
        png = (b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR"
               + (640).to_bytes(4, "big") + (480).to_bytes(4, "big") + b"\x08\x06\x00\x00\x00")
        h3, _ = st.add(KIND_IMAGE, png)
        assert st.get(h3)["preview"] == "[图片 640x480]"
        assert st.has(h1)
        assert len(st.hashes()) == 2
        assert st.list("你好")[0]["hash"] == h1
        assert st.list("图片")[0]["hash"] == h3
        st.set_pinned(h1, True)
        assert st.list()[0]["hash"] == h1, "置顶应排最前"
        for i in range(10):     # 触发清理: 上限 5, 置顶不受清理
            st.add(KIND_TEXT, f"item-{i}".encode())
        texts = [r for r in st.list(limit=100) if not r["pinned"]]
        assert len(texts) <= 5, f"超出上限: {len(texts)}"
        assert st.get(h1) is not None, "置顶记录不应被清理"
        st.delete(h1)
        assert not st.has(h1)
        # 迁移: 对端偏快时钟产生的"未来"时间戳, 重开库时应被钳到当前时间
        fh, _ = st.add(KIND_TEXT, "未来记录".encode(), created_at=time.time() + 7200)
        st.close()
        st = Store(Path(d) / "t.db", max_items=5)
        assert st.get(fh)["created_at"] <= time.time(), "未来时间戳未被钳制"
        st.close()


def test_remote_timestamp_clamp() -> None:
    """对端时钟不准时的时间处理 + 实时/历史判定:
    偏快时钟的历史钳到到达时刻; 旧历史保留原时间; 刚复制的内容即使走
    补齐路径(have 丢失等)也按实时处理, 触发剪贴板写入并按到达时刻排序。"""
    now = time.time()
    # 未来时间戳的历史: 非实时, 钳到 now
    live, ts = Node._classify_arrival(now + 3600, False, now)
    assert not live and ts == now, f"未来时间戳未被钳制: live={live} ts={ts}"
    # 很久以前的历史: 非实时, 保留原时间
    past = now - 3600
    live, ts = Node._classify_arrival(past, False, now)
    assert not live and ts == past, "历史时间戳不应被改动"
    # 刚复制的内容(have 通知在 _live 中): 实时, 记到达时刻
    live, ts = Node._classify_arrival(now - 30, True, now)
    assert live and ts == now, "have 通知的记录应判定为实时"
    # 刚复制但 have 丢失(不在 _live): 内容时间很新, 仍应判定为实时
    live, ts = Node._classify_arrival(now - 30, False, now)
    assert live and ts == now, "内容很新但 have 丢失时应按实时兜底"
    # 对端时钟偏慢的实时复制(有 have): 实时(不受时钟偏差影响)
    live, ts = Node._classify_arrival(now - 3600, True, now)
    assert live and ts == now, "偏慢时钟的 have 推送应判定为实时"


def test_hotkey_parse() -> None:
    assert hotkey.to_pynput("ctrl+q") == "<ctrl>+q"
    assert hotkey.to_pynput("Ctrl+Shift+F5") == "<ctrl>+<shift>+<f5>"
    assert hotkey.to_pynput("alt+space") == "<alt>+<space>"
    try:
        hotkey.to_pynput("ctrl+notakey")
        raise AssertionError("非法按键未报错")
    except ValueError:
        pass


def test_sync() -> None:
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        sa = Store(Path(d) / "a.db")
        sb = Store(Path(d) / "b.db")
        pa, pb = _free_port(), _free_port()
        na = Node(_cfg(pa, [{"host": "127.0.0.1", "port": pb}]), sa)
        nb = Node(_cfg(pb, [{"host": "127.0.0.1", "port": pa}]), sb)
        na.start()
        nb.start()
        try:
            assert _wait(lambda: na.connected_count() == 1 and nb.connected_count() == 1), \
                f"互填对端应认证并去重为单台设备, 实际 {na.connected_count()}/{nb.connected_count()}"
            # 去重后应保持稳定: 被弃方向收到 dup 通知后停止重拨, 不会形成重连风暴
            stable = True
            deadline = time.time() + 7
            while time.time() < deadline:
                if na.connected_count() != 1 or nb.connected_count() != 1:
                    stable = False
                    break
                time.sleep(0.2)
            assert stable, "去重后连接不稳定(被弃方向仍在反复重连)"
            # 网络线程里用 DirectConnection 捕获 remoteItemReceived(无主线程事件循环)
            got_b: list[tuple[str, bytes]] = []
            nb.remoteItemReceived.connect(lambda k, c: got_b.append((k, c)),
                                          Qt.ConnectionType.DirectConnection)
            # A -> B 实时通知
            ha, _ = sa.add(KIND_TEXT, "从A同步到B".encode())
            na.broadcast_have(ha)
            assert _wait(lambda: sb.has(ha)), "A 的记录未同步到 B"
            assert _wait(lambda: bool(got_b)), "实时推送未触发 remoteItemReceived"
            assert got_b[0] == (KIND_TEXT, "从A同步到B".encode()), got_b
            # B -> A 实时通知(图片)
            hb, _ = sb.add(KIND_IMAGE, b"\x89PNG\r\n\x1a\nfakepng")
            nb.broadcast_have(hb)
            assert _wait(lambda: sa.has(hb)), "B 的记录未同步到 A"
            # 对端时钟不准: 实时推送的记录按本机到达时间计(不采用对端时间戳),
            # 保证面板顺序与剪贴板内容一致; 实时推送仍触发剪贴板写入
            got_b.clear()
            h_old, _ = sa.add(KIND_TEXT, "对端时钟偏慢的记录".encode(),
                              created_at=time.time() - 3600)
            na.broadcast_have(h_old)
            assert _wait(lambda: sb.has(h_old)), "偏慢时钟的记录未同步到 B"
            assert _wait(lambda: bool(got_b)), "实时推送未触发 remoteItemReceived"
            ts = sb.get(h_old)["created_at"]
            assert abs(ts - time.time()) < 10, f"实时记录应记为到达时刻, 实际 {ts}"
            # 补齐的历史: 旧时间保留(维持原有先后), 未来时间钳到到达时刻
            t_past = time.time() - 7200
            h_past, _ = sb.add(KIND_TEXT, "很久以前的历史".encode(), created_at=t_past)
            h_ff, _ = sb.add(KIND_TEXT, "偏快时钟的历史".encode(),
                             created_at=time.time() + 7200)
            h_fresh, _ = sb.add(KIND_TEXT, "对端刚复制的内容".encode())  # 新鲜, 无 have
            # 增量补齐: C 上线前 B 已有历史, C 只配置连 B
            sc = Store(Path(d) / "c.db")
            pc = _free_port()
            nc = Node(_cfg(pc, [{"host": "127.0.0.1", "port": pb}]), sc)
            got_c: list[tuple[str, bytes]] = []
            nc.remoteItemReceived.connect(lambda k, c: got_c.append((k, c)),
                                          Qt.ConnectionType.DirectConnection)
            nc.start()
            try:
                assert _wait(lambda: sc.has(hb)), "新设备上线未补齐历史"
                assert _wait(lambda: sc.has(h_past) and sc.has(h_ff)), "历史补齐不完整"
                got_past = sc.get(h_past)["created_at"]
                assert abs(got_past - t_past) < 2, f"补齐的旧记录应保留原时间, 实际 {got_past}"
                assert sc.get(h_ff)["created_at"] <= time.time(), "未来时间未被钳制"
                time.sleep(0.5)
                # 旧历史(含未来时间戳)补齐不碰剪贴板; 但对端"刚复制"的内容
                # 即使走补齐路径也按实时兜底(测试中多条记录都是刚产生的)
                assert (KIND_TEXT, "对端刚复制的内容".encode()) in got_c, \
                    f"新鲜记录走补齐路径也应触发 remoteItemReceived, 实际 {got_c}"
                stale = ("很久以前的历史".encode(), "偏快时钟的历史".encode())
                assert all(c not in stale for _k, c in got_c), \
                    f"旧历史不应触发 remoteItemReceived, 实际 {got_c}"
            finally:
                nc.stop()
                sc.close()
            # 密钥不一致: 不能通过认证
            sd = Store(Path(d) / "d.db")
            pd = _free_port()
            nd = Node(_cfg(pd, [{"host": "127.0.0.1", "port": pb}], key="wrong-key-999"), sd)
            nd.start()
            try:
                time.sleep(2)
                assert nd.connected_count() == 0, "错误密钥竟然通过认证"
                assert not sd.has(ha), "错误密钥竟然收到数据"
            finally:
                nd.stop()
                sd.close()
        finally:
            na.stop()
            nb.stop()
            sa.close()
            sb.close()


def run() -> int:
    print(f"CopyAny 自检 (Python {sys.version.split()[0]})")
    QCoreApplication(sys.argv[:1])   # Node 的 Qt 信号依赖应用对象
    _check("加密: AES-256-GCM 往返 / 错密钥拒绝 / HMAC", test_crypto)
    _check("存储: 入库 / 去重 / 搜索 / 置顶 / 上限清理", test_store)
    _check("热键: 组合键解析", test_hotkey_parse)
    _check("时间戳: 对端未来时间按到达时刻钳制", test_remote_timestamp_clamp)
    _check("同步: 双向实时同步 / 增量补齐 / 错误密钥拒绝", test_sync)
    failed = [r for r in _results if not r[1]]
    print(f"\n结果: {len(_results) - len(failed)}/{len(_results)} 通过")
    return 1 if failed else 0
