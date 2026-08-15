"""Encryption for the credentials students paste in.

A Canvas token is a password: whoever holds it can read that student's courses,
grades and messages. PRD §9 says treat it like one — encrypted at rest, never
logged, never returned by any endpoint. This module is the "at rest" half.

We use Fernet (AES-128-CBC + HMAC from `cryptography`), so a token in the
database is unreadable without CONNECTOR_ENCRYPTION_KEY, and tampering with the
ciphertext fails loudly instead of decrypting to garbage.
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
    written. The fix is to disconnect and reconnect the source — the old
    ciphertext is not recoverable, which is the point.
    """


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    """Build the cipher once per process.

    Accepts either a real Fernet key (`Fernet.generate_key()`) or any passphrase,
    which we hash to the 32 bytes Fernet needs. The passphrase path exists so a
    teammate can put a memorable string in .env and get on with the demo.
    """
    raw = (getattr(settings, "CONNECTOR_ENCRYPTION_KEY", "") or "").strip()

    if not raw:
        if not settings.DEBUG:
            raise ImproperlyConfigured(
                "CONNECTOR_ENCRYPTION_KEY must be set before storing personal "
                "credentials outside DEBUG. Generate one with: python -c "
                "'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
            )
        # Development convenience only. Deriving from SECRET_KEY keeps tokens
        # readable across restarts without anyone configuring anything, but it
        # ties them to a key that is itself checked into .env.example — hence
        # the refusal to do this once DEBUG is off.
        logger.warning(
            "CONNECTOR_ENCRYPTION_KEY is unset; deriving a development key from "
            "DJANGO_SECRET_KEY. Set a real key before any shared deployment."
        )
        raw = settings.SECRET_KEY

    try:
        # A genuine Fernet key is already 32 url-safe-base64 bytes.
        return Fernet(raw.encode())
    except (ValueError, TypeError):
        derived = base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
        return Fernet(derived)


def encrypt(plaintext: str) -> str:
    """Encrypt a credential for storage. Returns url-safe base64 text."""
    if not plaintext:
        raise ValueError("Refusing to encrypt an empty credential.")
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored credential.

    Never log the return value, and never put it in an API response.
    """
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise DecryptionError(
            "Stored credential could not be decrypted — CONNECTOR_ENCRYPTION_KEY "
            "has probably changed. Disconnect and reconnect the source."
        ) from exc
