# Browser Extension — AskScotty Demo Connector

Chrome Manifest V3 extension at `browser-extension/`. It lets Piazza and
Gradescope work from a session cookie already in your browser, so a demo does
not need a CMU password or a Duo push.

> **Local DEBUG builds only. This does not work against a deployed AskScotty.**
> The route it posts to is mounted by `backend/config/urls.py` only when
> `settings.DEBUG` is true, so with `DJANGO_DEBUG=false` the endpoint is not
> merely restricted — it does not exist, and the extension gets a 404. Nothing
> in a deployed build accepts captured cookies, by design.

Canvas and Ed are deliberately not supported here: they authenticate with
revocable personal access tokens and go through the real connect flow
([b5-canvas-ed-stellic.md](./b5-canvas-ed-stellic.md)) instead.

---

## Load it in Chrome

1. Open `chrome://extensions/`
2. Enable **Developer mode** (top-right toggle)
3. **Load unpacked** → select `browser-extension/`

It appears in the toolbar as "AskScotty Demo Connector".

---

## Use it

You need the backend running locally (`docker compose up -d` with
`DJANGO_DEBUG=true`), to be signed in to Gradescope or Piazza in the **same
Chrome profile**, and your AskScotty session id.

**Finding your session id:** open the app on web, then DevTools → Application →
Local Storage → the Expo origin (`http://localhost:8081` by default) → copy
`askscotty.session_id`. Or pick any API request in the Network tab and copy its
`X-Session-Id` header.

**Connecting:**

1. Open a `gradescope.com` or `piazza.com` tab — the extension reads the
   provider from the active tab.
2. Click the extension icon; the popup shows the detected provider.
3. Paste your session id.
4. Confirm **Backend URL** is `http://localhost:8000` (remembered across uses).
5. Click **Connect \<provider\>**.

The extension collects every cookie set for that domain and POSTs:

```
POST /api/personal/demo/cookies/
X-Session-Id: <your session id>

{ "provider": "gradescope", "cookies": { "_gradescope_session": "…", … } }
```

The backend stores them as that connection's credential. Next time a personal
tool runs for the session, `apps/personal/tools.py` injects the cookies into the
library's HTTP session instead of calling `login()`, which is what gets past Duo.

---

## Backend endpoint

`backend/apps/personal/demo_only/` — see that folder's `README.md`.

`DemoCookieConnectView` validates the payload (provider in `COOKIE_PROVIDERS`,
≤25 cookies, each ≤8192 bytes) and calls `UserConnection.set_credential`, the
same write-only discipline as the real connect endpoint: cookies go in and
nothing reads them back out. It returns `{provider, connected_at, last_sync_at}`
— never the credential.

`COOKIE_PROVIDERS` is limited to Piazza and Gradescope, the two providers whose
libraries authenticate by session cookie at all.

---

## Security scope

- **Narrow host permissions.** `manifest.json` grants `www.gradescope.com`,
  `gradescope.com`, `piazza.com` and `localhost` — nothing else.
- **DEBUG only**, as above.
- **Do not ship.** This should never leave your machine: not the Chrome Web
  Store, not other users.

---

## Add a provider

Two places:

1. `browser-extension/popup.js` — add to `PROVIDERS`:
   ```js
   "example.com": { name: "example", keys: ["session_cookie_name"] }
   ```
   `keys` documents which cookies matter; the extension sends every cookie for
   the domain regardless.

2. `backend/apps/personal/demo_only/views.py` — add the provider slug to
   `COOKIE_PROVIDERS`.

Then make sure the matching tool in `apps/personal/tools.py` looks for a
`cookies` key in the credential and injects it — follow the Piazza/Gradescope
blocks.
