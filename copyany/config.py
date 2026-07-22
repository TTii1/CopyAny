"""配置加载与保存。

配置文件位置:
  Windows: %APPDATA%/CopyAny/config.yaml
  Linux:   ~/.config/copyany/config.yaml
数据库与日志与配置文件同目录。
"""
from __future__ import annotations

import copy
import os
import sys
import uuid
from pathlib import Path

import yaml

APP_DIR_NAME = "CopyAny" if sys.platform == "win32" else "copyany"

DEFAULT_CONFIG: dict = {
    "group_id": "my-group",
    "shared_key": "please-change-me",
    "listen": {"host": "0.0.0.0", "port": 9527},
    "peers": [],                       # [{"host": "192.168.1.100", "port": 9527}]
    "history": {"max_items": 1000},
    "hotkey": {"key": "ctrl+q"},
    "clipboard": {"auto_receive": False},  # 对端复制的内容自动写入本机剪贴板
}

TEMPLATE = """\
# CopyAny 配置文件
group_id: "my-group"            # 群组标识: 同一群组的设备共享剪贴板历史
shared_key: "please-change-me"  # 共享密钥(至少 8 位), 同群组所有设备必须一致

listen:
  host: "0.0.0.0"
  port: 9527                    # 本机监听端口(防火墙需放行 TCP)

peers: []                       # 其他设备, 去掉注释填写对端 IP:
# peers:
#   - host: "192.168.1.100"
#     port: 9527

history:
  max_items: 1000               # 历史记录上限(置顶条目不会被清理)

hotkey:
  key: "ctrl+q"                 # 呼出历史面板的全局快捷键

clipboard:
  auto_receive: false           # 对端复制的内容自动写入本机剪贴板(面板底部有开关)
"""


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
        return base / "CopyAny"
    base = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "copyany"


def config_path() -> Path:
    return config_dir() / "config.yaml"


def db_path() -> Path:
    return config_dir() / "history.db"


def log_path() -> Path:
    return config_dir() / "copyany.log"


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _normalize_peers(peers) -> list:
    """允许 peers 写成 "host:port" 字符串或 {host, port} 字典。"""
    out = []
    for p in peers or []:
        try:
            if isinstance(p, str):
                host, _, port = p.partition(":")
                out.append({"host": host.strip(), "port": int(port) if port else 9527})
            elif isinstance(p, dict) and p.get("host"):
                out.append({"host": str(p["host"]).strip(), "port": int(p.get("port", 9527))})
        except (TypeError, ValueError):
            continue
    return [p for p in out if p["host"]]


def load() -> tuple[dict, bool]:
    """返回 (配置, 是否为首次创建)。"""
    cfg_file = config_path()
    created = False
    if not cfg_file.exists():
        cfg_file.parent.mkdir(parents=True, exist_ok=True)
        cfg_file.write_text(TEMPLATE, encoding="utf-8")
        created = True
    try:
        data = yaml.safe_load(cfg_file.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        backup = cfg_file.with_suffix(".yaml.bak")
        cfg_file.replace(backup)          # 配置损坏时备份后重建, 避免启动崩溃
        cfg_file.write_text(TEMPLATE, encoding="utf-8")
        data = {}
    cfg = _merge(DEFAULT_CONFIG, data if isinstance(data, dict) else {})
    cfg["peers"] = _normalize_peers(cfg.get("peers"))
    if not cfg.get("device_id"):
        # 本机设备标识: 两台互填 IP 时会出现两条连接, 握手时用它识别同一设备并去重
        cfg["device_id"] = uuid.uuid4().hex
        with cfg_file.open("a", encoding="utf-8") as f:
            f.write(f'\n# 本机设备标识(自动生成, 请勿修改)\ndevice_id: "{cfg["device_id"]}"\n')
    return cfg, created


def save(cfg: dict) -> None:
    cfg_file = config_path()
    cfg_file.parent.mkdir(parents=True, exist_ok=True)
    cfg_file.write_text(
        yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )
