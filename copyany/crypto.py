"""加密与认证: 预共享密钥 -> PBKDF2 派生 AES-256-GCM 密钥, HMAC-SHA256 用于握手认证。"""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ITERATIONS = 200_000


def derive_key(shared_key: str, group_id: str) -> bytes:
    """由 共享密钥 + 群组ID 派生 32 字节会话密钥。群组不同则密钥不同。"""
    salt = b"copyany-v1:" + group_id.encode("utf-8")
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=_ITERATIONS)
    return kdf.derive(shared_key.encode("utf-8"))


def encrypt(key: bytes, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext, None)


def decrypt(key: bytes, blob: bytes) -> bytes:
    if len(blob) < 12 + 16:
        raise ValueError("密文长度非法")
    try:
        return AESGCM(key).decrypt(blob[:12], blob[12:], None)
    except InvalidTag as e:
        raise ValueError("解密失败: 密钥错误或数据被篡改") from e


def hmac_hex(key: bytes, data: bytes) -> str:
    h = hmac.HMAC(key, hashes.SHA256())
    h.update(data)
    return h.finalize().hex()
