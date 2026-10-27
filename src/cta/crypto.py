"""Encryption at rest: each tenant's documents are sealed with that tenant's key (AES-256-GCM), bound to the case and
document so a ciphertext cannot be moved to another record. In production the keys are KMS data keys
(deploy/terraform: one CMK per tenant, decrypted at start); locally they come from CTA_KEYRING."""

from __future__ import annotations

import base64
import json
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Keyring:
    def __init__(self, keys: dict[str, bytes]):
        self.keys = keys

    @classmethod
    def from_env(cls) -> Keyring:
        raw = os.environ.get("CTA_KEYRING")
        if not raw:
            raise RuntimeError("CTA_KEYRING is not set (JSON: {tenant: base64 32-byte key})")
        return cls({t: base64.b64decode(k) for t, k in json.loads(raw).items()})

    @staticmethod
    def generate(tenants: list[str]) -> str:
        return json.dumps({t: base64.b64encode(secrets.token_bytes(32)).decode() for t in tenants})

    def _key(self, tenant: str) -> AESGCM:
        if tenant not in self.keys:
            raise KeyError(f"no key for tenant {tenant}")
        return AESGCM(self.keys[tenant])

    def seal(self, tenant: str, context: str, plaintext: str) -> tuple[bytes, bytes]:
        nonce = secrets.token_bytes(12)
        return self._key(tenant).encrypt(nonce, plaintext.encode("utf-8"), f"{tenant}|{context}".encode()), nonce

    def open(self, tenant: str, context: str, ciphertext: bytes, nonce: bytes) -> str:
        return (
            self._key(tenant).decrypt(bytes(nonce), bytes(ciphertext), f"{tenant}|{context}".encode()).decode("utf-8")
        )
