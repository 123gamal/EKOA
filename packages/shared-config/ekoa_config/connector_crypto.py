"""Symmetric encryption at rest for connector credentials (Fernet).

Connector access tokens (e.g. GitHub PATs) are persisted to the database in
ciphertext form only. The key comes from ``settings.EKOA_FERNET_KEY`` — a
separate secret from ``JWT_SECRET_KEY``, never derived from it, and supplied
via environment variable / secrets manager (see the settings docstring for
generation). This module is shared by the API (encrypt on connect, decrypt on
health check) and the worker (decrypt when a sync task runs), so both services
must be configured with the same key.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from ekoa_config.settings import get_settings


def _fernet() -> Fernet:
    key = get_settings().EKOA_FERNET_KEY
    if not key:
        raise RuntimeError(
            "EKOA_FERNET_KEY is not configured. Set it to a Fernet key "
            "(e.g. the output of cryptography.fernet.Fernet.generate_key()) "
            "via environment variable or .env before using connectors."
        )
    return Fernet(key.encode("utf-8"))


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a plaintext connector token, returning URL-safe ciphertext."""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a connector token ciphertext back to plaintext."""
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError(
            "Stored connector credential could not be decrypted — the "
            "EKOA_FERNET_KEY likely changed or the value is corrupted."
        ) from exc
