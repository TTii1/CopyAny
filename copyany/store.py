"""SQLite 历史库: 存文本与 PNG 图片(BLOB), SHA256 去重, 支持置顶/搜索/时间倒序。"""
from __future__ import annotations

import hashlib
import sqlite3
import struct
import threading
import time
from pathlib import Path

KIND_TEXT = "text"
KIND_IMAGE = "image"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    hash       TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    content    BLOB NOT NULL,
    preview    TEXT NOT NULL DEFAULT '',
    pinned     INTEGER NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    source     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_order ON items(pinned DESC, created_at DESC);
"""


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _png_size(data: bytes) -> tuple[int, int] | None:
    """从 PNG 字节流头部解析宽高, 用于预览文案。"""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            w, h = struct.unpack(">II", data[16:24])
            return int(w), int(h)
    except (IndexError, struct.error):
        pass
    return None


def make_preview(kind: str, content: bytes) -> str:
    if kind == KIND_TEXT:
        text = content.decode("utf-8", "replace")
        return " ".join(text.split())[:200]
    size = _png_size(content)
    if size:
        return f"[图片 {size[0]}x{size[1]}]"
    return "[图片]"


class Store:
    """线程安全的历史库(网络线程与 GUI 线程共用)。"""
    def __init__(self, path, max_items: int = 1000):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        self.max_items = int(max_items)
        with self._lock, self._conn:
            self._conn.executescript(_SCHEMA)
            # 迁移: 旧版本可能已存入对端偏快时钟产生的"未来"时间戳, 钳到当前时间
            self._conn.execute("UPDATE items SET created_at=? WHERE created_at > ?",
                               (time.time(), time.time()))

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def add(self, kind: str, content: bytes, source: str = "",
            created_at: float | None = None) -> tuple[str, bool]:
        """返回 (hash, 是否为新记录)。本地重复复制只把时间顶到最前;
        同步来的旧内容(带 created_at)若已存在则保持不变。"""
        h = digest(content)
        now = created_at if created_at is not None else time.time()
        with self._lock, self._conn:
            row = self._conn.execute("SELECT hash FROM items WHERE hash=?", (h,)).fetchone()
            if row:
                if created_at is None:
                    self._conn.execute("UPDATE items SET created_at=? WHERE hash=?", (time.time(), h))
                return h, False
            self._conn.execute(
                "INSERT INTO items(hash, kind, content, preview, pinned, created_at, source)"
                " VALUES(?,?,?,?,0,?,?)",
                (h, kind, content, make_preview(kind, content), now, source),
            )
            self._trim_locked()
        return h, True

    def _trim_locked(self) -> None:
        self._conn.execute(
            """DELETE FROM items WHERE pinned = 0 AND hash NOT IN (
                   SELECT hash FROM items WHERE pinned = 0
                   ORDER BY created_at DESC LIMIT ?)""",
            (self.max_items,),
        )

    def has(self, h: str) -> bool:
        with self._lock:
            return self._conn.execute(
                "SELECT 1 FROM items WHERE hash=?", (h,)).fetchone() is not None

    def get(self, h: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE hash=?", (h,)).fetchone()
        return dict(row) if row else None

    def hashes(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute("SELECT hash FROM items").fetchall()
        return [r[0] for r in rows]

    def list(self, query: str = "", limit: int = 100) -> list[dict]:
        """按 置顶优先 + 时间倒序 返回; 文本按内容过滤, 图片可按 '图片/image' 过滤。"""
        with self._lock:
            if query:
                like = f"%{query}%"
                img_hit = query.lower() in ("图", "图片", "image", "img", "pic")
                if img_hit:
                    rows = self._conn.execute(
                        "SELECT * FROM items WHERE preview LIKE ? OR kind='image'"
                        " ORDER BY pinned DESC, created_at DESC LIMIT ?", (like, limit))
                else:
                    rows = self._conn.execute(
                        "SELECT * FROM items WHERE preview LIKE ?"
                        " ORDER BY pinned DESC, created_at DESC LIMIT ?", (like, limit))
            else:
                rows = self._conn.execute(
                    "SELECT * FROM items ORDER BY pinned DESC, created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows.fetchall()]

    def delete(self, h: str) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM items WHERE hash=?", (h,))

    def set_pinned(self, h: str, pinned: bool) -> None:
        with self._lock, self._conn:
            self._conn.execute("UPDATE items SET pinned=? WHERE hash=?", (1 if pinned else 0, h))

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])
