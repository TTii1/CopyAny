"""设备间同步: TCP 直连, 4 字节长度前缀 + JSON 消息体。

握手流程(双向挑战-应答, 明文):
  1) 双方互发 hello:  {type: hello, group: 群组ID, nonce: 随机数}
  2) 双方互发 auth:   {type: auth, hmac: HMAC(key, 对方nonce)}
     群组不一致或 HMAC 校验失败即断开; 密钥错误永远无法通过。
  3) 之后所有消息经 AES-256-GCM 加密传输。

同步策略("轻量通知 + 按需拉取"):
  - 连接建立后互发 sync(本地全部哈希清单), 对端用 want 批量拉取缺失记录;
  - 本机有新复制内容时只广播 have(约百字节的哈希), 对端没有就拉取;
  - 两台互填 IP 会产生双向双连接, 握手交换 device_id 后按对称规则去重只留一条,
    被弃连接收到 dup 通知, 在保留连接存续期间不再重拨(老版本对端则两条都保留,
    仅状态显示去重, 避免老版本被断开后反复重连)。
"""
from __future__ import annotations

import base64
import hmac as std_hmac
import json
import logging
import os
import socket
import struct
import threading
import time

from PySide6.QtCore import QObject, Signal

from . import crypto
from .store import KIND_IMAGE, KIND_TEXT, digest

log = logging.getLogger(__name__)

MAX_FRAME = 64 * 1024 * 1024       # 单帧上限(图片 BLOB base64 后)
MAX_ITEM_BYTES = 48 * 1024 * 1024  # 单条内容上限
PING_INTERVAL = 25                 # 心跳秒数
SYNC_BATCH = 200                   # want 批量拉取大小
HANDSHAKE_TIMEOUT = 10
LIVE_WINDOW = 60                   # 秒: 内容 created_at 在此窗口内视为"刚复制"(实时)


class ProtocolError(ConnectionError):
    """对端数据不符合帧格式(通常意味着该端口上运行的不是 CopyAny)。"""


# ---------- 帧编解码 ----------

def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("连接已关闭")
        buf.extend(chunk)
    return bytes(buf)


def send_frame(sock: socket.socket, data: bytes) -> None:
    sock.sendall(struct.pack("!I", len(data)) + data)


def recv_frame(sock: socket.socket) -> bytes:
    (n,) = struct.unpack("!I", _recv_exact(sock, 4))
    if n <= 0 or n > MAX_FRAME:
        raise ProtocolError(f"非法帧长度: {n}")
    return _recv_exact(sock, n)


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)


class _Conn:
    """一条对端连接(可能尚未完成认证)。"""
    def __init__(self, node: "Node", sock: socket.socket, addr, outbound: bool = False):
        self.node = node
        self.sock = sock
        self.addr = addr
        self.outbound = outbound       # 本机主动拨出(True) / 对方拨入(False)
        self.peer_id: str | None = None  # 握手时从 hello 获得; 老版本对端为 None
        self.send_lock = threading.Lock()

    def send_plain(self, obj: dict) -> None:
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        with self.send_lock:
            send_frame(self.sock, data)

    def send(self, obj: dict) -> None:
        """AES-GCM 加密后发送。"""
        data = crypto.encrypt(self.node.key, json.dumps(obj, separators=(",", ":")).encode("utf-8"))
        with self.send_lock:
            send_frame(self.sock, data)

    def recv_plain(self) -> dict:
        return json.loads(recv_frame(self.sock))

    def recv(self) -> dict:
        return json.loads(crypto.decrypt(self.node.key, recv_frame(self.sock)))

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class Node(QObject):
    """同步节点: 内置 TCP 服务端 + 对每个配置对端的重连客户端。"""

    peerStatusChanged = Signal(int, int)  # (已认证连接数, 配置的对端数)
    itemsChanged = Signal()               # 收到新的远程记录(已入库)
    remoteItemReceived = Signal(str, bytes)  # 对端实时推送的新记录(kind, content);
    # have 通知拉取或内容本身刚复制(LIVE_WINDOW 内)时发出; 上线补齐的旧历史不发,
    # 避免覆盖本机剪贴板

    def __init__(self, cfg: dict, store):
        super().__init__()
        self.group = str(cfg.get("group_id", "my-group"))
        self.key = crypto.derive_key(str(cfg.get("shared_key", "")), self.group)
        self.device_id = str(cfg.get("device_id") or os.urandom(16).hex())
        self.store = store
        listen = cfg.get("listen") or {}
        self.listen_host = str(listen.get("host", "0.0.0.0"))
        self.listen_port = int(listen.get("port", 9527))
        self.peers: list[tuple[str, int]] = []
        for p in cfg.get("peers") or []:
            try:
                self.peers.append((str(p["host"]), int(p.get("port", 9527))))
            except (KeyError, TypeError, ValueError):
                log.warning("忽略非法对端配置: %r", p)
        self._conns: list[_Conn] = []
        self._conns_lock = threading.Lock()
        self._passive: dict[tuple[str, int], str] = {}  # 被对端判定多余的对端 -> 其设备ID
        self._live: set[str] = set()   # 经 have 通知、正在拉取中的哈希(实时推送)
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._server: socket.socket | None = None
        self.listen_error: str | None = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        self._stop.clear()
        self._spawn(self._accept_loop, "accept")
        for host, port in self.peers:
            self._spawn(self._connect_loop, f"dial-{host}:{port}", host, port)
        self._spawn(self._ping_loop, "ping")

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            try:
                self._server.close()
            except OSError:
                pass
        with self._conns_lock:
            conns = list(self._conns)
        for c in conns:
            c.close()
        for t in self._threads:
            if t.is_alive():
                t.join(timeout=2)
        self._threads.clear()

    def _spawn(self, fn, name: str, *args) -> None:
        t = threading.Thread(target=fn, args=args, name=f"copyany-{name}", daemon=True)
        t.start()
        self._threads.append(t)

    # ---------- 服务端 / 客户端 ----------

    def _accept_loop(self) -> None:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((self.listen_host, self.listen_port))
            srv.listen(16)
            srv.settimeout(1.0)
        except OSError as e:
            self.listen_error = str(e)
            log.error("监听 %s:%s 失败: %s", self.listen_host, self.listen_port, e)
            srv.close()
            return
        self._server = srv
        log.info("已监听 %s:%s", self.listen_host, self.listen_port)
        while not self._stop.is_set():
            try:
                sock, addr = srv.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            self._spawn(self._handle, f"conn-{addr[0]}:{addr[1]}", sock, addr, False)

    def _connect_loop(self, host: str, port: int) -> None:
        backoff = 3
        while not self._stop.is_set():
            # 对端已告知"连接多余"(同设备已有更优连接): 该连接存续期间不再重拨,
            # 否则被关闭的一方会每 3 秒重连一次, 形成永久重连风暴
            pid = self._passive.get((host, port))
            if pid is not None:
                if self._has_peer(pid):
                    self._stop.wait(2)
                    continue
                self._passive.pop((host, port), None)   # 更优连接已断, 恢复重拨
            try:
                log.debug("连接对端 %s:%s ...", host, port)
                sock = socket.create_connection((host, port), timeout=8)
                self._handle(sock, (host, port), True)   # 阻塞直到连接断开
                backoff = 3
            except OSError as e:
                log.debug("连接 %s:%s 失败: %s", host, port, e)
            except Exception:
                log.exception("对端 %s:%s 连接异常", host, port)
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30)

    def _has_peer(self, peer_id: str) -> bool:
        with self._conns_lock:
            return any(c.peer_id == peer_id for c in self._conns)

    # ---------- 单连接处理 ----------

    def _handle(self, sock: socket.socket, addr, outbound: bool = False) -> None:
        conn = _Conn(self, sock, addr, outbound)
        try:
            self._handshake(conn)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            with self._conns_lock:
                dup = next((c for c in self._conns if self._same_peer(c, conn)), None)
                drop_old = drop_new = False
                if dup is not None and conn.peer_id is not None:
                    # 双方都是新版本: 按对称规则只留一条, 被弃的一条通知对端停止重拨
                    if self._keep_new(conn, dup):
                        self._conns.remove(dup)
                        drop_old = True
                    else:
                        drop_new = True
                # 对端是老版本(无法配合去重): 两条连接都保留, 仅状态显示去重,
                # 避免老版本被断开后每 3 秒重连一次形成重连风暴
                if not drop_new:
                    self._conns.append(conn)
            if drop_new:
                log.info("对端 %s:%s 与本机已有更优连接(互填对端 IP), 关闭本条重复连接",
                         addr[0], addr[1])
                self._notify_dup(conn)
                conn.close()
                return
            if drop_old:
                log.info("对端 %s:%s 出现重复连接(互填对端 IP), 已保留更优的一条",
                         addr[0], addr[1])
                self._notify_dup(dup)
                dup.close()
            self._emit_status()
            log.info("对端 %s:%s 认证通过", addr[0], addr[1])
            # 增量同步: 互换哈希清单, 对端按需拉取
            conn.send({"type": "sync", "hashes": self.store.hashes()})
            while not self._stop.is_set():
                self._on_message(conn, conn.recv())
        except PermissionError as e:
            log.warning("对端 %s:%s 认证失败: %s", addr[0], addr[1], e)
        except (ConnectionError, OSError, ValueError, json.JSONDecodeError) as e:
            log.debug("与 %s:%s 的连接结束: %s", addr[0], addr[1], e)
        except Exception:
            log.exception("连接处理异常 %s:%s", addr[0], addr[1])
        finally:
            with self._conns_lock:
                if conn in self._conns:
                    self._conns.remove(conn)
            conn.close()
            self._emit_status()

    def _same_peer(self, a: _Conn, b: _Conn) -> bool:
        """两条连接是否来自同一台设备。device_id 都在时按 ID 判断;
        对端是老版本(无 ID)时退化为按来源 IP 判断(仅新版本侧做决策, 不会双向误杀)。"""
        if a.peer_id and b.peer_id:
            return a.peer_id == b.peer_id
        return a.addr[0] == b.addr[0]

    def _keep_new(self, new: _Conn, old: _Conn) -> bool:
        """同一设备出现两条连接(互填 IP)时只留一条, 规则两端对称:
        设备 ID 较小的一端保留自己主动拨出的连接, 较大端保留对方拨入的 ——
        两端留下的其实是同一条物理连接(仅在新版本对端间使用, peer_id 必存在)。"""
        if new.outbound != old.outbound:
            prefer_outbound = self.device_id < str(new.peer_id)
            return new.outbound == prefer_outbound
        return True   # 同向(如配置的 IP 变了, 旧连接未断): 留新弃旧

    @staticmethod
    def _notify_dup(conn: _Conn) -> None:
        """关闭重复连接前通知对端"本条多余", 对端收到后在被保留的连接存续期间不再重拨;
        老版本忽略该消息, 断开后的重连行为与旧版一致。"""
        try:
            conn.send({"type": "dup"})
        except OSError:
            pass

    def _handshake(self, conn: _Conn) -> None:
        """双向挑战认证。失败前尽量发 bye 帧告知对方原因(对方旧版本收不到时会直接断开)。"""
        our_nonce = os.urandom(16)
        conn.send_plain({"type": "hello", "group": self.group, "nonce": _b64e(our_nonce),
                         "device": self.device_id})
        conn.sock.settimeout(HANDSHAKE_TIMEOUT)
        try:
            hello = conn.recv_plain()
            if hello.get("type") == "bye":
                raise PermissionError(f"对方拒绝: {hello.get('reason', '未知原因')}")
            if hello.get("type") != "hello":
                self._bye(conn, "protocol_error")
                raise PermissionError("对方不是 CopyAny 协议")
            if hello.get("group") != self.group:
                self._bye(conn, "group_mismatch")
                raise PermissionError("群组不一致")
            peer_device = str(hello.get("device") or "")
            conn.peer_id = peer_device or None   # 老版本对端不带 device 字段
            their_nonce = _b64d(str(hello.get("nonce", "")))
            conn.send_plain({"type": "auth", "hmac": crypto.hmac_hex(self.key, their_nonce)})
            auth = conn.recv_plain()
            if auth.get("type") == "bye":
                raise PermissionError(f"对方拒绝: {auth.get('reason', '未知原因')}")
        finally:
            conn.sock.settimeout(None)
        expected = crypto.hmac_hex(self.key, our_nonce)
        if auth.get("type") != "auth" or not std_hmac.compare_digest(str(auth.get("hmac", "")), expected):
            self._bye(conn, "key_mismatch")
            raise PermissionError("共享密钥不一致")

    @staticmethod
    def _bye(conn: _Conn, reason: str) -> None:
        """断开前告知原因; 对方已断开时静默忽略。"""
        try:
            conn.send_plain({"type": "bye", "reason": reason})
        except OSError:
            pass

    # ---------- 消息处理 ----------

    def _on_message(self, conn: _Conn, obj: dict) -> None:
        t = obj.get("type")
        if t == "sync":
            want = [h for h in obj.get("hashes", []) if isinstance(h, str) and not self.store.has(h)]
            for i in range(0, len(want), SYNC_BATCH):
                conn.send({"type": "want", "hashes": want[i:i + SYNC_BATCH]})
        elif t == "want":
            for h in obj.get("hashes", [])[: SYNC_BATCH * 5]:
                row = self.store.get(h)
                if row:
                    conn.send({"type": "item", "item": self._encode_row(row)})
        elif t == "item":
            row = self._decode_row(obj.get("item") or {})
            if row:
                h = digest(row["content"])
                # 实时判定 = 经 have 通知拉取(_live) 或 内容本身刚复制(LIVE_WINDOW 内)。
                # 后者兜底: have 丢失/对端版本行为差异导致实时记录走了其他路径时,
                # 仍能按实时处理; 上线补齐的旧记录(超过窗口或"未来"时间戳)不算实时
                is_live, row["created_at"] = self._classify_arrival(
                    row["created_at"], h in self._live, time.time())
                h, is_new = self.store.add(row["kind"], row["content"],
                                           source=f"{conn.addr[0]}", created_at=row["created_at"])
                if is_new:
                    log.info("已同步对端 %s 的%s记录", conn.addr[0],
                             "图片" if row["kind"] == KIND_IMAGE else "文本")
                    self.itemsChanged.emit()
                    if is_live:
                        self.remoteItemReceived.emit(row["kind"], row["content"])
                self._live.discard(h)
        elif t == "have":
            h = obj.get("hash")
            if isinstance(h, str) and not self.store.has(h):
                self._live.add(h)
                conn.send({"type": "want", "hashes": [h]})
        elif t == "dup":
            # 对端判定本条连接多余(同设备已有更优连接): 记录后断开,
            # 在被保留的连接存续期间 _connect_loop 不再向该对端重拨
            if conn.outbound and conn.peer_id:
                self._passive[(conn.addr[0], conn.addr[1])] = conn.peer_id
            raise ConnectionError("对端关闭了重复连接")
        elif t == "ping":
            conn.send({"type": "pong"})
        # pong 无需处理

    @staticmethod
    def _classify_arrival(raw_ts: float, in_live: bool, now: float) -> tuple[bool, float]:
        """返回 (是否实时, 入库时间戳)。时间戳以本机为准(各机时钟可能不一致):
        实时记录按到达时刻入库, 面板顺序与剪贴板内容都按到达顺序, 两者天然一致;
        补齐的历史保留原时间(未来时间戳钳到到达时刻), 维持原有先后。"""
        if in_live or 0 <= now - raw_ts < LIVE_WINDOW:
            return True, now
        return False, min(raw_ts, now)

    @staticmethod
    def _encode_row(row: dict) -> dict:
        return {
            "hash": row["hash"],
            "kind": row["kind"],
            "content": _b64e(row["content"]),
            "created_at": float(row["created_at"]),
        }

    @staticmethod
    def _decode_row(obj: dict) -> dict | None:
        try:
            kind = obj["kind"]
            if kind not in (KIND_TEXT, KIND_IMAGE):
                return None
            content = _b64d(str(obj["content"]))
            if not content or len(content) > MAX_ITEM_BYTES:
                return None
            # created_at 保留对端原值, 钳制与实时判定由 _classify_arrival 完成
            created_at = float(obj.get("created_at") or time.time())
            return {"kind": kind, "content": content, "created_at": created_at}
        except (KeyError, TypeError, ValueError):
            return None

    # ---------- 对外接口 ----------

    def broadcast_have(self, h: str) -> None:
        """本机新增记录后, 向所有已认证对端广播其哈希。"""
        with self._conns_lock:
            conns = list(self._conns)
        for c in conns:
            try:
                c.send({"type": "have", "hash": h})
            except OSError:
                c.close()

    def connected_count(self) -> int:
        """已认证的去重后设备数(同一设备的双向双连接只算一台;
        老版本对端无 device_id, 按来源 IP 去重)。"""
        with self._conns_lock:
            return len({c.peer_id or f"ip:{c.addr[0]}" for c in self._conns})

    def _ping_loop(self) -> None:
        while not self._stop.wait(PING_INTERVAL):
            with self._conns_lock:
                conns = list(self._conns)
            for c in conns:
                try:
                    c.send({"type": "ping"})
                except OSError:
                    c.close()

    def _emit_status(self) -> None:
        self.peerStatusChanged.emit(self.connected_count(), len(self.peers))
