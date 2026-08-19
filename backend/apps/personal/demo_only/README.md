# demo_only — NOT FOR THE JUDGES

Everything in this folder exists to make **our own** Piazza and Gradescope data
easy to reach during a live demo. It is not part of the product and must not be
presented as one.

## What it is

A browser extension (built separately) reads the session cookies of a Piazza or
Gradescope tab **we are already logged in to** and POSTs them here. The endpoint
stores them as the connection's credential, and `apps/personal/tools.py` injects
them into the library's HTTP session instead of calling `login()`.

## Why it exists

The supported connect path is email + password (`docs/b5-piazza-gradescope.md`).
CMU may route those logins through Duo, and an automated password login has no
way past a 2FA prompt — it hangs. An already-authenticated session cookie has
cleared Duo already, so injecting it is the one path that works unattended. See
the same doc's Phase 0 for why 2FA was the open risk.

## Why it is walled off here, and stays here

- Grabbing another site's cookies through an extension is not something we ship.
  It is fine for reaching **our own** accounts on **our own** machines; it is not
  fine to hand to a judge or a user.
- The route is registered **only when `settings.DEBUG` is true** (see
  `config/urls.py`). A production build does not expose it at all — the extension
  has nowhere to POST.
- Nothing in the product depends on this package. Deleting the folder and its two
  lines in `config/urls.py` removes the demo path with no other change. The
  `cookies` branch left in `tools.py` simply goes dead, because no credential
  ever carries a `cookies` key again.

## Do not

- Do not ship the extension to anyone.
- Do not enable this route with `DEBUG=False`.
- Do not widen it to Canvas/Ed — those use a real personal access token
  (`docs/b5-canvas-ed-stellic.md`); a token is revocable and does not need this.

## Full guide

For step-by-step setup, how to add a provider, and architecture notes, see
`docs/browser-extension.md`.
