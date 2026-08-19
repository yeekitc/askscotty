# Browser Extension — AskScotty Demo Connector

Chrome Manifest V3 extension at `browser-extension/`. **DEBUG/demo use only.**
It lets Piazza and Gradescope work via a live session cookie already in the
browser rather than storing a CMU password.

Canvas and Ed are not supported here — they use revocable personal access tokens
and have a proper connect flow (`docs/b5-canvas-ed-stellic.md`).

---

## Load it in Chrome

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. Click **Load unpacked**
4. Select the `browser-extension/` folder in this repo

The extension appears in the toolbar as "AskScotty Demo Connector".

---

## Use it

### Prerequisites

- Backend running locally (`docker compose up -d`)
- Signed in to Gradescope or Piazza in the **same Chrome profile**
- AskScotty app open in a browser tab so you can get your session ID

### Find your session ID

Open the app, open DevTools → Application → Local Storage →
`http://localhost:19006` (or whatever Expo serves). Copy the value of
`askscotty.session_id`.

Alternatively, open the app's network tab, pick any API request, and copy the
`X-Session-ID` request header.

### Connect

1. Navigate to `gradescope.com` or `piazza.com` in Chrome — the extension
   auto-detects the provider from the active tab.
2. Click the extension icon. The popup shows the detected provider.
3. Paste your session ID into the **Session ID** field.
4. Confirm the **Backend URL** is `http://localhost:8000` (saved across uses).
5. Click **Connect \<provider\>**.

The extension collects every cookie set for that domain and POSTs to:

```
POST /api/personal/demo/cookies/
X-Session-ID: <your session id>

{ "provider": "gradescope", "cookies": { "_gradescope_session": "...", ... } }
```

The backend stores them as the connection credential. The next time a personal
tool runs for that session, `tools.py` injects the cookies into the library's
HTTP session instead of calling `login()`, bypassing Duo.

---

## Backend endpoint

`backend/apps/personal/demo_only/` — registered only when `settings.DEBUG` is
`True` (see `config/urls.py`). A production build does not expose this path.

`DemoCookieConnectView` validates the payload (provider in allowlist,
≤25 cookies, each ≤8192 bytes) and calls `UserConnection.set_credential` —
the same write-only discipline as the real connect endpoint. Nothing here reads
the credential back out.

`COOKIE_PROVIDERS` in `views.py` lists the accepted providers. The URL is
`/api/personal/demo/cookies/`.

---

## Security scope

- **localhost only.** `host_permissions` in `manifest.json` covers
  `www.gradescope.com`, `gradescope.com`, `piazza.com`, and `localhost` only.
- **DEBUG only.** The Django route does not exist when `DEBUG=False`.
- **Do not ship.** The extension should never leave your machine. Do not add it
  to the Chrome Web Store or distribute it to users.

---

## Add a provider

Two places:

1. `browser-extension/popup.js` — add an entry to the `PROVIDERS` object:
   ```js
   "example.com": { name: "example", keys: ["session_cookie_name"] }
   ```
   `keys` documents the expected cookies (the extension now sends all cookies
   for the domain regardless, but the list is useful reference).

2. `backend/apps/personal/demo_only/views.py` — add the provider slug to
   `COOKIE_PROVIDERS`:
   ```python
   COOKIE_PROVIDERS = frozenset({Provider.PIAZZA.value, Provider.GRADESCOPE.value, Provider.EXAMPLE.value})
   ```

Also ensure the corresponding personal tool in `apps/personal/tools.py` checks
for a `cookies` key in the credential and injects it (see the Piazza/Gradescope
blocks for the pattern).
