"""User-scoped connections to personal sources (Canvas, Ed, …).

Scoped by an anonymous session id the app generates and stores on the device,
not a Django user account (tasklist §1) — enough to scope a connector for a demo
without building a login screen. The trade-off, stated plainly: a session id is
a bearer token, not an identity, so anyone who learns one can read that
session's connected data. Real accounts are the upgrade path.

PRD §7 rules this file exists to enforce:
  - tokens are encrypted at rest, never logged, never returned by any endpoint
  - everything is scoped to one session_id
  - disconnecting deletes the synced data along with the credential
"""

from __future__ import annotations

from django.db import models

from .crypto import decrypt, encrypt


class Provider(models.TextChoices):
    """The personal sources a session can connect.

    The value is the slug used everywhere else: `requires_connector` on a tool,
    the connect/disconnect URLs, and the settings UI.
    """

    CANVAS = "canvas", "Canvas"
    ED = "ed", "Ed Discussion"
    STELLIC = "stellic", "Stellic (uploaded audit)"


class UserConnection(models.Model):
    """One credential, belonging to one session.

    Deliberately not registered in admin.py: the admin renders every field, and
    `encrypted_token` reaching a browser — even as ciphertext — is exactly the
    accident PRD §9 is about.
    """

    session_id = models.CharField(
        max_length=128,
        db_index=True,
        help_text="Anonymous session this credential belongs to. Never a real user id.",
    )
    provider = models.CharField(max_length=32, choices=Provider.choices)
    encrypted_token = models.TextField(
        help_text="Fernet ciphertext. Read it through get_token(), never directly.",
    )
    connected_at = models.DateTimeField(auto_now_add=True)
    last_sync_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When we last pulled data from this source. Shown in the connectors UI.",
    )

    class Meta:
        constraints = [
            # Reconnecting updates the existing row rather than quietly leaving
            # a stale token behind.
            models.UniqueConstraint(
                fields=["session_id", "provider"],
                name="unique_connection_per_session_provider",
            )
        ]
        ordering = ["provider"]

    def __str__(self) -> str:
        # Truncated session, no token: this string ends up in logs and error
        # pages, so it must stay boring.
        return f"{self.get_provider_display()} (session {self.session_id[:8]}…)"

    def set_token(self, raw_token: str) -> None:
        """Encrypt and store a credential. Does not save."""
        self.encrypted_token = encrypt(raw_token.strip())

    def get_token(self) -> str:
        """Decrypt the credential for an outbound API call.

        Keep the return value local and let it go out of scope. Do not log it,
        do not attach it to an exception, do not return it.
        """
        return decrypt(self.encrypted_token)
