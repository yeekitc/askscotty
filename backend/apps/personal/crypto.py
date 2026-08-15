"""Encryption for the credentials students paste in — the "at rest" half of
PRD §9 (encrypted at rest, never logged, never returned by any endpoint).

Fernet (AES-128-CBC + HMAC), so a stored token is unreadable without
CONNECTOR_ENCRYPTION_KEY and tampering fails loudly instead of decrypting to
garbage.
"""

from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)


class DecryptionError(Exception):
    """A stored credential could not be decrypted.

    Almost always means CONNECTOR_ENCRYPTION_KEY changed since the row was
    written. Reconnecting the source is the only fix — the old ciphertext is not
    recoverable, which is the point.
    """


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Build the cipher once per process.

    Accepts a real Fernet key or any passphrase, hashed to the 32 bytes Fernet
    needs — the passphrase path exists so a teammate can put a memorable string
    in .env and get on with the demo.
    """
    raw = (getattr(settings, "CONNECTOR_ENCRYPTION_KEY", "") or "").strip()

    if not raw:
        if not settings.DEBUG:
            raise ImproperlyConfigured(
                "CONNECTOR_ENCRYPTION_KEY must be set before storing personal "
                "credentials outside DEBUG. Generate one with: python -c "
                "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        # Keeps tokens readable across restarts with no configuration, but ties
        # them to a key checked into .env.example — hence the refusal above once
        # DEBUG is off.
        logger.warning(
            "CONNECTOR_ENCRYPTION_KEY is unset; deriving a development key from "
            "DJANGO_SECRET_KEY. Set a real key before any shared deployment."
        )
        raw = settings.SECRET_KEY

    try:
        # A genuine Fernet key is already 32 url-safe-base64 bytes; anything
        # else lands in the derive path below.
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    if not plaintext:
        raise ValueError("Refusing to encrypt an empty credential.")
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Never log the return value, and never put it in an API response."""
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "Stored credential could not be decrypted — CONNECTOR_ENCRYPTION_KEY "
            "has probably changed. Disconnect and reconnect the source."
        ) from exc
