"""连接诊断: 逐步探测对端, 每一步失败都给出可读原因与可操作的建议。

探测步骤: DNS 解析 -> TCP 连接 -> CopyAny 握手(hello/auth 双向认证)。
配合 net.py 的 bye 帧, 能区分 群组不一致 / 密钥不一致 / 端口被占用 等原因;
对端是旧版本(无 bye 帧)时退化为"认证阶段被断开"。
"""
from __future__ import annotations

import base64
import hmac as std_hmac
import json
import os
import socket
import time

from . import crypto
from .net import ProtocolError, recv_frame, send_frame


def _b64e(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"), validate=True)

STEP_DNS = "解析地址"
STEP_TCP = "TCP 连接"
STEP_HELLO = "握手(群组校验)"
STEP_AUTH = "认证(密钥校验)"


def _step(name: str, ok: bool | None, detail: str = "") -> dict:
    return {"name": name, "ok": ok, "detail": detail}


def _fail(result: dict, step_name: str, summary: str, advice: list[str]) -> dict:
    for s in result["steps"]:
        if s["ok"] is None:
            s["ok"] = s["name"] != step_name
            if s["name"] == step_name:
                s["detail"] = summary
    result.update(ok=False, summary=summary, advice=advice)
    return result


def _firewall_advice(port: int) -> list[str]:
    return [
        "最常见原因: 对方电脑的防火墙没有放行该端口(入站连接被静默丢弃)。",
        f"Windows: 首次运行的防火墙弹窗需勾选\"专用网络\"并允许; 或用管理员 CMD 执行: "
        f"netsh advfirewall firewall add rule name=\"CopyAny {port}\" dir=in action=allow protocol=TCP localport={port}",
        f"Linux: sudo ufw allow {port}/tcp",
        "同时确认两台电脑在同一局域网/VPN, 且对方 IP 没填错(可在对方机器的设置-测试连接里查看本机 IP)。",
    ]


def probe_peer(host: str, port: int, group_id: str, shared_key: str,
               timeout: float = 8.0) -> dict:
    """探测一个对端, 返回 {ok, steps, summary, advice, rtt_ms}。"""
    result: dict = {
        "ok": False,
        "peer": f"{host}:{port}",
        "steps": [_step(STEP_DNS, None), _step(STEP_TCP, None),
                  _step(STEP_HELLO, None), _step(STEP_AUTH, None)],
        "summary": "",
        "advice": [],
        "rtt_ms": None,
    }
    key = crypto.derive_key(shared_key, group_id)

    # ---- 1. DNS / 地址解析 ----
    try:
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        ip = infos[0][4][0]
        result["steps"][0].update(ok=True, detail=ip if ip != host else "")
    except socket.gaierror as e:
        return _fail(result, STEP_DNS, f"无法解析 \"{host}\"",
                     ["检查对端 IP/主机名是否填写正确(多一个字、错一位都会失败)。",
                      f"系统返回: {e}"])

    # ---- 2. TCP 连接 ----
    t0 = time.monotonic()
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
    except ConnectionRefusedError:
        return _fail(result, STEP_TCP, f"对方拒绝了连接({ip}:{port} 上没有程序在监听)",
                     ["对方电脑上的 CopyAny 没有启动(看托盘图标是否存在), 或启动失败(如端口被占用)。",
                      "两端\"监听端口\"必须一致, 检查是否填错了端口。",
                      "少数防火墙会主动拒绝(REJECT)未放行的端口, 也表现为\"被拒绝\"; 若确认对方已运行, 按防火墙处理。",
                      ] + _firewall_advice(port)[1:3])
    except socket.timeout:
        return _fail(result, STEP_TCP, f"连接超时({timeout:.0f} 秒内对方没有任何响应)",
                     _firewall_advice(port))
    except OSError as e:
        if e.errno in (101, 113, 10051, 10065):  # 网络/主机不可达
            return _fail(result, STEP_TCP, f"主机不可达({ip} 不在线或路由不通)",
                         ["确认对方电脑已开机且联网, IP 没填错(可先 ping 对方 IP 试试)。",
                          "确认两台电脑在同一网段/局域网, 或已通过 VPN 互联。"])
        return _fail(result, STEP_TCP, f"连接失败: {e}", ["检查 IP、端口与网络连接后重试。"])
    rtt_ms = (time.monotonic() - t0) * 1000
    result["steps"][1].update(ok=True, detail=f"{rtt_ms:.0f} ms")
    result["rtt_ms"] = round(rtt_ms)

    try:
        sock.settimeout(timeout)
        our_nonce = os.urandom(16)

        # ---- 3. 握手: 互发 hello, 校验群组 ----
        try:
            send_frame(sock, json.dumps({"type": "hello", "group": group_id,
                                         "nonce": _b64e(our_nonce)},
                                        separators=(",", ":")).encode("utf-8"))
            hello = json.loads(recv_frame(sock))
        except socket.timeout:
            return _fail(result, STEP_HELLO, "对方接受了连接但不回应(不是 CopyAny 或已卡死)",
                         [f"{ip}:{port} 上运行的可能不是 CopyAny(端口被其他程序占用), 两端换一个端口试试。"])
        except (ProtocolError, ValueError, json.JSONDecodeError):
            return _fail(result, STEP_HELLO, "对方返回了无法识别的数据(不是 CopyAny 协议)",
                         [f"{ip}:{port} 上运行的是其他程序(端口被占用), 两端换一个端口试试。"])
        except (ConnectionError, OSError):
            return _fail(result, STEP_HELLO, "对方在握手阶段直接断开了连接",
                         ["对方可能是旧版本(不告知原因): 常见为群组 ID 不一致。",
                          "若对方已是最新版仍断开, 检查双方\"群组 ID\"是否完全一致(区分大小写)。"])

        if hello.get("type") == "bye":
            reason = str(hello.get("reason", ""))
            if reason == "group_mismatch":
                return _fail(result, STEP_HELLO, "群组 ID 不一致(对方拒绝了连接)",
                             ["两端的\"群组 ID\"必须一字不差(区分大小写、首尾不能有空格)。"])
            if reason == "key_mismatch":
                return _fail(result, STEP_AUTH, "共享密钥不一致(对方拒绝了连接)",
                             _key_advice())
            return _fail(result, STEP_HELLO, f"对方拒绝: {reason or '未知原因'}",
                         ["确认两端群组 ID 与共享密钥完全一致。"])
        if hello.get("type") != "hello":
            return _fail(result, STEP_HELLO, "对方返回了无法识别的数据(不是 CopyAny 协议)",
                         [f"{ip}:{port} 上运行的是其他程序(端口被占用), 两端换一个端口试试。"])

        their_group = str(hello.get("group", ""))
        if their_group != group_id:
            return _fail(result, STEP_HELLO,
                         f"群组 ID 不一致: 对方是 \"{their_group}\", 本机是 \"{group_id}\"",
                         ["两端的\"群组 ID\"必须一字不差(区分大小写、首尾不能有空格)。"])
        result["steps"][2].update(ok=True, detail=f"对方群组 \"{their_group}\"")

        # ---- 4. 认证: HMAC 挑战-应答 ----
        try:
            their_nonce = _b64d(str(hello.get("nonce", "")))
        except ValueError:
            return _fail(result, STEP_AUTH, "对方数据格式异常(可能是版本不兼容)",
                         ["两端都升级到最新版本后重试。"])
        send_frame(sock, json.dumps({"type": "auth", "hmac": crypto.hmac_hex(key, their_nonce)},
                                    separators=(",", ":")).encode("utf-8"))
        try:
            auth = json.loads(recv_frame(sock))
        except socket.timeout:
            return _fail(result, STEP_AUTH, "对方没有回复认证结果",
                         ["对方可能版本过旧或已卡死, 两端都升级到最新版本后重试。"])
        except (ConnectionError, OSError):
            return _fail(result, STEP_AUTH, "对方在认证阶段断开了连接(通常是共享密钥不一致)",
                         ["对方若是旧版本不会告知具体原因。先按密钥不一致排查:",
                          *_key_advice()])
        except (ValueError, json.JSONDecodeError):
            return _fail(result, STEP_AUTH, "对方返回了无法识别的数据",
                         ["两端都升级到最新版本后重试。"])

        if auth.get("type") == "bye":
            reason = str(auth.get("reason", ""))
            if reason == "key_mismatch":
                return _fail(result, STEP_AUTH, "共享密钥不一致(对方拒绝了连接)",
                             _key_advice())
            if reason == "group_mismatch":
                return _fail(result, STEP_HELLO, "群组 ID 不一致(对方拒绝了连接)",
                             ["两端的\"群组 ID\"必须一字不差(区分大小写、首尾不能有空格)。"])
            return _fail(result, STEP_AUTH, f"对方拒绝: {reason or '未知原因'}",
                         ["确认两端群组 ID 与共享密钥完全一致。"])

        expected = crypto.hmac_hex(key, our_nonce)
        if auth.get("type") != "auth" or not std_hmac.compare_digest(str(auth.get("hmac", "")), expected):
            return _fail(result, STEP_AUTH, "对方的认证应答校验失败(共享密钥可能不一致)",
                         _key_advice())

        result["steps"][3].update(ok=True, detail="认证通过")
        result.update(ok=True, summary=f"连接成功, 认证通过(往返约 {result['rtt_ms']} ms)")
        return result
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _b64e(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode("ascii")


def _b64d(s: str) -> bytes:
    import base64
    return base64.b64decode(s.encode("ascii"), validate=True)


def _key_advice() -> list[str]:
    return ["两端的\"共享密钥\"必须逐字符一致: 区分大小写, 首尾不能有空格。",
            "建议两端都勾选设置里的\"显示密钥\"逐字核对, 或在其中一台上重新输入后, "
            "把完全相同的密钥复制到另一台。"]


# ---------- 本机自检 ----------

def local_ips() -> list[str]:
    """本机可用的局域网 IPv4(让对方填这些), 失败时返回空列表。"""
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    return ips


def local_checks(cfg: dict, node=None) -> list[dict]:
    """本机侧检查: 监听状态 / 本机 IP / 是否配置了对端。返回 step 列表。"""
    steps: list[dict] = []
    port = int(getattr(node, "listen_port", None) or (cfg.get("listen") or {}).get("port", 9527))
    listen_error = getattr(node, "listen_error", None) if node is not None else None
    if listen_error:
        steps.append(_step("本机监听", False,
                           f"端口 {port} 监听失败: {listen_error} —— 端口被其他程序占用, 请换端口"))
    elif node is None:
        steps.append(_step("本机监听", None, f"端口 {port}(未获取运行状态)"))
    else:
        steps.append(_step("本机监听", True, f"端口 {port} 正常监听中"))
    ips = local_ips()
    steps.append(_step("本机 IP", bool(ips),
                       ", ".join(ips) + "(让对方把这个 IP 填进对端列表)" if ips
                       else "未找到局域网 IP, 请检查网络连接"))
    if not cfg.get("peers"):
        steps.append(_step("对端配置", False,
                           "未填写任何对端 —— 至少一方要把对方 IP:端口 填进\"对端设备\""))
    return steps
