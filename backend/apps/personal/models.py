"""User-scoped connections to personal sources (Canvas, Ed, …).

Scoping model for the hackathon (tasklist §1): an **anonymous session id**, not a
Django user account. The app generates one, stores it on the device, and sends
it with every request. That is enough to scope a connector to one person for a
demo, and it means nobody has to build a login screen.

The trade-off is worth stating plainly: anyone who learns a session id can read
that session's connected data. It is opaque and never guessable from anything
public, but it is a bearer token, not an identity. Real accounts are the upgrade
path if this outlives the hackathon.

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

    The value is the slug used everywhere else: in `requires_connector` on a
    tool, in the connect/disconnect URLs, and in the settings UI.
    """

    CANVAS = "canvas", "Canvas"
    ED = "ed", "Ed Discussion"
    STELLIC = "stellic", "Stellic (uploaded audit)"


class UserConnection(models.Model):
    """One credential, belonging to one session.

    Deliberately **not** registered in admin.py: the admin renders every field of
    a model, and `encrypted_token` showing up in a browser — even as ciphertext —
    is exactly the kind of accident PRD §9 is about.
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
            # One credential per provider per session. Reconnecting updates the
            # existing row rather than quietly leaving a stale token behind.
            models.UniqueConstraint(
                fields=["session_id", "provider"],
                name="unique_connection_per_session_provider",
            )
        ]
        ordering = ["provider"]

    def __str__(self) -> str:
        # Truncated session, no token. This string ends up in logs and error
        # pages, so it must stay boring.
        return f"{self.get_provider_display()} (session {self.session_id[:8]}…)"

    def set_token(self, raw_token: str) -> None:
        """Encrypt and store a credential. Does not save."""
        self.encrypted_token = encrypt(raw_token.strip())

    def get_token(self) -> str:
        """Decrypt the credential for an outbound API call.

        Keep the return value in a local variable and let it go out of scope.
        Do not log it, do not attach it to an exception, do not return it.
        """
        return decrypt(self.encrypted_token)
