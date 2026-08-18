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

import json

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
    PIAZZA = "piazza", "Piazza"
    GRADESCOPE = "gradescope", "Gradescope"


# What a credential must contain, per provider. One place knows the shape, so
# the connections endpoint and the tools that spend the credential cannot
# disagree about it. A provider absent from this map cannot be connected at all.
#
# Piazza and Gradescope want an email and password rather than a scoped token
# because their unofficial libraries offer nothing else — see
# docs/b5-piazza-gradescope.md for that decision and the risk accepted with it.
#
# STELLIC maps to no required keys: it is a mock (docs/b5-canvas-ed-stellic.md
# Part C) with nothing to authenticate, but it still connects — with an empty
# credential — so the settings UI can toggle it like any other source rather
# than special-casing it.
CREDENTIAL_FIELDS: dict[str, tuple[str, ...]] = {
    Provider.CANVAS: ("token",),
    Provider.ED: ("token",),
    Provider.PIAZZA: ("email", "password"),
    Provider.GRADESCOPE: ("email", "password"),
    Provider.STELLIC: (),
}


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
        help_text="Fernet ciphertext of a JSON credential. Read it through "
        "get_credential(), never directly.",
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

    def set_credential(self, credential: dict) -> None:
        """Encrypt and store a credential dict. Does not save.

        Always a JSON object, never a bare string: Canvas and Ed hand over one
        token, but Piazza and Gradescope need an email *and* a password, and one
        stored shape means the endpoint and the tools never have to ask which
        kind of provider they are holding.
        """
        self.encrypted_token = encrypt(json.dumps(credential))

    def get_credential(self) -> dict:
        """Decrypt and parse the stored credential.

        Keep the return value local and let it go out of scope. Do not log it,
        do not attach it to an exception, do not return it.
        """
        return json.loads(decrypt(self.encrypted_token))

    def set_token(self, raw_token: str) -> None:
        """Convenience for single-token providers (Canvas, Ed)."""
        self.set_credential({"token": raw_token.strip()})

    def get_token(self) -> str:
        """Convenience for single-token providers (Canvas, Ed).

        Same discipline as get_credential(): local, and never logged or returned.
        """
        return self.get_credential()["token"]
