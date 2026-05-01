"""AES-GCM secret box for encrypting BYO API keys at rest."""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class SecretBox:
    def __init__(self, master_key: str) -> None:
        # Derive a 32-byte key from the configured master key.
        self._key = hashlib.sha256(master_key.encode("utf-8")).digest()

    def encrypt(self, plaintext: str, associated_data: bytes | None = None) -> bytes:
        nonce = os.urandom(12)
        aead = AESGCM(self._key)
        ct = aead.encrypt(nonce, plaintext.encode("utf-8"), associated_data)
        return nonce + ct

    def decrypt(self, blob: bytes, associated_data: bytes | None = None) -> str:
        if len(blob) < 13:
            raise ValueError("ciphertext too short")
        nonce, ct = blob[:12], blob[12:]
        aead = AESGCM(self._key)
        return aead.decrypt(nonce, ct, associated_data).decode("utf-8")

    @staticmethod
    def b64(blob: bytes) -> str:
        return base64.b64encode(blob).decode("ascii")

    @staticmethod
    def unb64(s: str) -> bytes:
        return base64.b64decode(s.encode("ascii"))
