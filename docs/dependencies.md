# Dependencies

Everything AskScotty depends on, and **why** — the reasoning matters more than
the version number, because the version will change and the reasoning is what
tells you whether a swap is safe.

**Adding something? Add a row here in the same commit.** A package that appears
in `requirements.txt` or `package.json` without a line here is a package nobody
can safely remove later, because no one remembers what it was for.

- Backend versions are pinned exactly (`==`) in [backend/requirements.txt](./backend/requirements.txt).
  After changing it: `docker compose up -d --build` — a plain restart is not enough.
- Frontend versions are ranges in [frontend/app/package.json](./frontend/app/package.json),
  because Expo pins the set of versions that work together. Change them with
  `npx expo install <pkg>`, not `npm install <pkg>`.

---

## Backend — Python

Installed into the `backend` container. See [backend/requirements.txt](./backend/requirements.txt).

### Web framework

| Package | Why it's here |
|---|---|
| `Django` | The web framework. Pinned to the **5.2.x LTS** — do not drop back to 5.1, which is end-of-life and carries an unpatched critical SQL-injection advisory (CVE-2025-64459). |
| `djangorestframework` | Serializers and the browsable API. The serializers are the API contract in code (tasklist §2), and the browsable form at `/api/ask/` is how non-technical teammates poke the API without writing code. 3.16 was the first release supporting Django 5.1+; we run 3.18, which targets 5.2. |
| `django-cors-headers` | Lets the Expo app call the API from a different origin. Without it every request from `localhost:8081` fails in the browser. |
| `psycopg2-binary` | Postgres driver. The `-binary` build ships pre-compiled wheels, so nobody has to install Postgres headers to get the container running. |
| `python-dotenv` | Loads `.env` into the environment in `config/settings.py`. |
| `gunicorn` | Production WSGI server. Unused in development (Docker overrides the command with `runserver`), kept so the image can be deployed as-is. |
| `whitenoise` | Serves static files for the Django admin without a separate web server. |

### Planner, retrieval and connectors

Added for tasklist §1. Each of these is a decision that was made once and should
not be re-litigated per-file — if you disagree with one, change it here and in
tasklist §1 together.

| Package | Why it's here | Alternatives considered |
|---|---|---|
| `anthropic` | The planner, **and the web-search lane**. Claude's tool-use API drives the multi-hop loop (Courses → Maps → Dining → Events) that is the demo's whole point. It also ships **server-side `web_search` / `web_fetch`**, which is why there is no search provider on this list. Default model `claude-sonnet-5` — the planner mostly does routing and tool selection rather than deep reasoning, and Sonnet is roughly half the cost of Opus per token. Set `PLANNER_MODEL=claude-opus-5` if multi-hop answers come out weak; nothing else changes. **The loop runs on Managed Agents** — same package, `client.beta.agents` / `client.beta.sessions`; see below. | OpenAI function calling — no reason to prefer it, and we would still need Anthropic-quality tool use. |
| `openai` | **Embeddings only** (`text-embedding-3-small`), for the vector half of hybrid retrieval. Anthropic has no embeddings endpoint, so a second provider is unavoidable — this is the one narrow job it does. | A local `sentence-transformers` model: no API key and no per-call cost, but it adds ~2GB to the image and slows the container start enough to hurt a five-minute setup. Revisit if API budget becomes the binding constraint. |
| `pgvector` | Vector column and index types for Postgres. Keeping vectors in the Postgres we already run means one database to start, back up and ship a demo fixture from — no second service in `docker-compose.yml`. The Postgres **extension** still has to be enabled separately (tasklist B0); this package is only the Django/psycopg integration. | Chroma, Qdrant, Pinecone — all add a moving part to a setup that has to work first try on a teammate's laptop. |
| `cryptography` | Fernet encryption for personal access tokens at rest (PRD §9). Also an indirect dependency of the SDKs above, but pinned here because [`apps/personal/crypto.py`](./backend/apps/personal/crypto.py) imports it directly — a direct import deserves a direct pin. | Rolling our own with `hashlib` — no. Fernet is authenticated, so a tampered ciphertext fails loudly instead of decrypting to garbage. |
| `httpx` | HTTP client for the crawler and the live-tool clients. Gives us timeouts, connection reuse and a shared retry policy without hand-rolling them; also the client both SDKs above already use, so it is in the image regardless. | `requests` — no timeout by default, which is exactly the failure mode that hangs a demo. |
| `beautifulsoup4` | HTML → clean text extraction for the campus crawler (`apps/rag/crawler.py`). Strips `<nav>`, `<footer>`, `<script>`, `<style>` boilerplate and walks the element tree to collect heading-segmented text for the chunker. No viable standard-library substitute: `html.parser` alone gives you a DOM but no convenient tree-walk or tag-removal API. Pinned to 4.12.x, the last stable series before the 4.13 release train (API-stable across 4.x). | `lxml` — faster, but requires a C extension that fails on a fresh Python install without `libxml2-dev`; the crawler is I/O-bound on the network, so parser speed is not the bottleneck. |
| `piazza-api` | The Piazza connector (`apps/personal/piazza.py`). **The honest reason this is here: Piazza issues students no API token, so the only way in is `user_login(email, password)` with their real Piazza password — which means we store a password we can decrypt, not a scoped credential a student can revoke without changing their login.** That is a materially worse failure mode than Canvas's PAT and it was accepted deliberately, not by default (see [docs/b5-piazza-gradescope.md](./b5-piazza-gradescope.md)). Unofficial and reverse-engineered: it posts to `piazza.com/class` and scrapes the response for an error string, so a login-page change breaks it with no deprecation warning. `search_feed(query)` is a real server-side search, which is why the tool does not page through `iter_all_posts`. | Not building it at all, or accepting an uploaded export instead — both were on the table and the risk was taken knowingly. Writing our own client: same password exposure, plus the reverse-engineering. |
| `gradescopeapi` | The Gradescope connector (`apps/personal/gradescope.py`). Same password trade-off as `piazza-api` above, and it applies harder here: `Assignment` carries `grade` and `max_grade`, so a leaked Gradescope credential exposes grades, not just deadlines. Note the PyPI name is `gradescopeapi`, **not** the `gradescope-api` of the repo — the hyphenated name is not on PyPI at all. Also drags in `fastapi` and `pytest` as *runtime* requirements, which is a packaging bug on their side; we neither import nor serve either. | `piazza-api`'s alternatives, identically. |

### The loop: Managed Agents, not `tool_runner` and not our own

**No new dependency** — Managed Agents is the same `anthropic` package under
`client.beta.agents` and `client.beta.sessions`. Worth a row here anyway, because
it changes what the package *is* to us: an SDK we call becomes a platform we run
on, and two of the alternatives below were previously chosen and are now not.

| Option | Why not |
|---|---|
| `client.beta.messages.tool_runner()` | **Does not resume a `pause_turn`.** A long web-search turn ends early and the runner hands the paused turn back as if finished, with no error — the demo silently truncates. Also wants `@beta_tool`-decorated functions when our registry is plain functions plus hand-written schemas, and keeps a message list it won't show us. |
| Our own loop | What we built, and it works. Superseded because the platform now gives us durable sessions, cancel and compaction for free, and takes `pause_turn` off our hands entirely — the very thing that ruled out the runner. |
| `claude-agent-sdk` | A **different package**: Claude Code as a library. Built-in Read/Write/Edit/Bash over a filesystem we don't have, custom tools only through MCP, and a shell running in the process that ingests crawled pages. Wrong product for a routing planner. |

An earlier version of this file said B4's loop was "a parameter, not code we
write", then corrected itself to say we must write it. Both halves were right
about `tool_runner` and wrong about where the loop should live. The trade we are
actually making is recorded in [b4-planner.md](./b4-planner.md): a network round
trip per tool batch, and a deadline path that has to be rebuilt.

### Removed: `tavily-python` — Claude does web search server-side

We picked Tavily for the PRD §6 verify lane, then found the Claude API already
covers it. Removed 2026-08-15 along with `TAVILY_API_KEY`. **Don't add a search
provider back without re-running the test below** — the finding, not the opinion,
is what settled this.

`web_search_20260318` and `web_fetch_20260318` are **server-side**: declare them
in the `tools` array and they run on Anthropic's infrastructure under
`ANTHROPIC_API_KEY`. Both take `allowed_domains`, `blocked_domains`, `max_uses`,
`max_content_tokens` — which is the entire B3 requirement list:

| B3 / PRD §6 needed | Built-in parameter |
|---|---|
| Site-filtered search (`site:cs.cmu.edu`) | `allowed_domains` |
| Allowlist of public hosts for `fetch_url` | `allowed_domains` |
| Canvas / SIO / Stellic can never be fetched | `blocked_domains` |
| Rate-limit the verify lane | `max_uses` |

Verified live on `claude-sonnet-5`, not read off a docs page: a search restricted
to `cs.cmu.edu` returned 30 hits with **zero** off-domain leaks, and a blocked
fetch of `canvas.cmu.edu` failed with `url_not_allowed` — while the same URL
under a *non-covering* denylist failed with `url_not_accessible`. Two different
codes, so the denylist is doing real work rather than coinciding with Canvas
being login-walled. That control is the whole test; without it the result is
meaningless, because Canvas fails either way.

**The cost is the catch.** Search results land in the context window: one
searching query measured **~35.9k input tokens and ~26 seconds** — roughly 8¢ at
Sonnet 5's intro rate, ~12¢ after 2026-08-31. Verify only when the index is
genuinely stale, and cap with `max_uses` / `max_content_tokens`.

Two traps when wiring it: don't declare `code_execution` alongside these (dynamic
filtering is built in; a second execution environment confuses the model), and
handle `pause_turn` — a long search turn ends the loop early and looks like a
finished answer.

### Evaluated and declined: `edapi` — the Ed token path is a direct call

Ed Discussion was going to lean on `edapi`, once believed to authenticate by
scraping a logged-in browser cookie. Reading its source (`edapi/edapi.py`) settled
both halves: it uses the same official Bearer token as Canvas
(`edstem.org/us/settings/api-tokens`), and `apps/personal/tools.py` calls
`https://us.edstem.org/api/` directly through `apps.core.http.get_json` rather than
add the dependency — there is no cookie scraping and nothing `edapi` does that the
two endpoints we need (`GET user`, `GET courses/{id}/threads`) don't do in one line
each. It was installed once, only to read, and uninstalled. Don't add it back
without a reason those two calls can't cover.

---

## Frontend — npm

One Expo/React Native app that runs on iOS, Android and web from the same
source. See [frontend/app/package.json](./frontend/app/package.json).

> Install with **`npx expo install <pkg>`**, not `npm install`. Expo resolves the
> version that matches the installed SDK; plain `npm install` will happily give
> you a newer one that breaks the native build.

| Package | Why it's here |
|---|---|
| `expo` | The toolchain. Runs the app on a phone, a simulator and the browser without anyone installing Xcode or Android Studio first. |
| `expo-router` | File-based routing: `app/about.tsx` becomes `/about` on all three platforms. |
| `expo-constants` | Reads `EXPO_PUBLIC_*` config at runtime — how the app finds the API URL. |
| `expo-linking` | Deep links, and opening citation URLs in the system browser. |
| `expo-status-bar` | Status-bar styling that behaves the same on both mobile platforms. |
| `react`, `react-dom` | React itself; `react-dom` is needed for the web target. |
| `react-native` | The component primitives (`View`, `Text`, `Pressable`, `TextInput`). |
| `react-native-web` | Translates those components into real HTML so one codebase serves the browser too. This is what makes "one frontend, three platforms" true rather than aspirational. |
| `react-native-safe-area-context` | Keeps content clear of notches and home indicators. |
| `react-native-screens` | Native screen primitives that make navigation transitions smooth. |
| `react-native-reanimated` | Every microinteraction in the app. `@assistant-ui/react-native` ships **no** animation code at all — the web package gets its motion from Tailwind transitions and Radix, none of which crosses over — so the sidebar, the hero-to-thread handoff and the typing-indicator crossfade are all ours. Chosen over RN's built-in `Animated` because react-native-web has no native driver (see `USE_NATIVE_DRIVER` in `components/TypingIndicator.tsx`), so `Animated` runs on the JS thread there, and because the sidebar animates a layout width, which stutters off the UI thread. Was already present transitively via `expo-router`; this makes it direct. Needs no `babel.config.js` — `babel-preset-expo` wires `react-native-worklets/plugin` itself. Tokens and the reduced-motion gate live in [`lib/motion.ts`](./frontend/app/lib/motion.ts). |
| `@assistant-ui/react-native` | The chat/thread UI the ask screen is built on — message list, composer, streaming-ready thread state. Saves building a chat surface from scratch during a hackathon. |
| `@react-native-async-storage/async-storage` | Key-value storage that works on **all three** platforms. Holds the anonymous session id ([`lib/session.ts`](./frontend/app/lib/session.ts)) and the source filter. Replaced `localStorage`, which is web-only — on a phone `window` does not exist, so the guards around it meant native builds silently persisted nothing and lost every conversation on restart. |
| `expo-image-picker` | Profile photo selection in `ConnectionsModal`. Lets users pick an image from the camera roll and returns it as a base64 data URL for cross-platform storage in AsyncStorage alongside the display name. First-party Expo package; no native config needed beyond the standard Expo managed workflow. |
| `typescript`, `@types/react` | Types. The API contract in [`lib/types.ts`](./frontend/app/lib/types.ts) is only load-bearing because TypeScript enforces it — keep `npx tsc --noEmit` clean. |

### Markdown rendering: evaluated and hand-rolled

**No package.** `lib/markdown.ts` (~180 lines) parses the subset the planner
actually writes, and `components/AnswerText.tsx` renders it.

This needed deciding because the model emits Markdown and **nothing in our stack
renders it** — assistant-ui's markdown support is a separate package,
`@assistant-ui/react-markdown`, built on `react-markdown` and Radix, so it is
React DOM only. `@assistant-ui/react-native` exports no markdown renderer at all;
it hands you `part.text` and expects you to render it. Until this landed, `**bold**`
reached the screen with the asterisks showing.

Three libraries were checked. All of them cost more than they save here:

| Package | Why not |
|---|---|
| `react-native-markdown-display` | Unpublished since 2023, on `markdown-it@10` and `react-native-fit-image` — an unmaintained renderer against RN 0.86 + React 19 is a bet, not a saving |
| `@ronradtke/react-native-markdown-display` | Maintained, but pulls `@react-native-vector-icons/material-design-icons` **and** `prism-react-renderer` — an icon font needing native linking plus a syntax highlighter, to render three bullets and some bold |
| `react-native-marked` | Needs `react-native-svg` as a peer dependency — a new native module in an Expo app whose whole selling point is that teammates never open Xcode |

Rules of thumb 1 and 2 below both bite: the standard library really does do it
(the answers are paragraphs, bullets, bold and the odd link), and every candidate
adds a native build step for a teammate.

The deciding argument is F2, though. Inline `[S1]` citation chips have to be
**direct children of the outermost `<Text>`** ([b4-planner.md](./b4-planner.md)),
and every one of these libraries owns the whole text subtree. `AnswerText`
funnels each leaf string through one `renderSpanText` seam, which is where the
chips go.

**Revisit if** answers start containing tables, images, or nested lists — at that
point the subset stops being a subset and the parser stops being small.

### `assistant-cloud` — keep it, and why removing it fails

Two separate things share this name, and conflating them wastes an afternoon:

- **Assistant Cloud, the hosted service** — thread storage on assistant-ui's
  servers. We do not use it today (we run `useLocalRuntime`, no account, no key).
- **`assistant-cloud`, the npm package** — a **hard build-time requirement**
  regardless of the above.

`@assistant-ui/core` declares it an *optional* peer, so it reads as dead weight.
It isn't: core's React entry point imports the cloud thread-history adapter
unconditionally, and that adapter has a top-level `import "assistant-cloud"`.
Metro walks the graph eagerly, so `npm uninstall assistant-cloud` fails every
bundle — web, iOS and Android alike:

```
Unable to resolve module assistant-cloud from
  .../@assistant-ui/core/dist/react/runtimes/cloud/AssistantCloudThreadHistoryAdapter.js
```

`npx tsc --noEmit` still passes when it is missing, so **typecheck will not
catch this** — only a real bundle does. And because npm does not auto-install
peers marked optional, this direct entry is the only thing putting it in a
fresh clone's `node_modules`; removing it breaks every teammate's first install.

It *can* be aliased to an empty stub via a `metro.config.js` `resolveRequest`
hook — measured at ~436K of install and ~17KB of web bundle saved (1% of 1.7MB).
That was tried and reverted: not worth a resolver hack pinned to a module name
upstream controls. Revisit only if assistant-ui makes the import lazy.

### Assistant Cloud: evaluated and declined

Assistant Cloud is assistant-ui's hosted thread storage. We looked at it
seriously — it is free at our scale (200 MAU) — and chose to run our own
storage instead ([`backend/apps/core/models.py`](./backend/apps/core/models.py)).
Recording the reasoning so the question does not get re-opened mid-hackathon:

1. **It bypasses Django rather than integrating with it.** The frontend talks
   straight to `https://backend.assistant-api.com`; threads would live in their
   Postgres, not ours. Django's only job would be minting a user token — one
   `httpx.post` to `/v1/auth/tokens` with `Authorization: Bearer <api key>`
   (there is **no Python SDK**; PyPI 404s). But the planner needs conversation
   history — that is what `history` in `AskSerializer` is for — and it cannot
   join against a table it does not own.
2. **React Native does not get the turnkey path.** `@assistant-ui/react-native`
   exports only the generic `useRemoteThreadListRuntime` — not
   `useCloudThreadListAdapter`, `AssistantCloud`, or a cloud runtime hook. Those
   live in `@assistant-ui/core/react`. Cloud would have saved us the database,
   **not** the adapter, which is most of the work.
3. **Nobody has done this.** Searched before committing: 0 GitHub repos combine
   assistant-ui with Django; 0 Python projects list it in `requirements.txt`;
   the Django example the maintainer split out
   ([assistant-ui/django-example](https://github.com/assistant-ui/django-example))
   has 1 star and one commit, untouched since 2025-11-17, and contains **zero**
   mentions of `assistant-cloud` or persistence. Both official Python backends
   cover the streaming protocol only.
4. **It is third-party storage of student chat history**, which sits awkwardly
   next to PRD §9 — answers here can quote someone's Canvas assignments.
   Anonymous mode (`anonymous: true`) needs no backend but does not persist
   across sessions or devices, so it solves nothing we needed.

The one precedent worth keeping: [issue #2182](https://github.com/assistant-ui/assistant-ui/issues/2182)
is someone building exactly our design — DRF thread/message endpoints behind a
custom `historyAdapter`. It crashed, and the maintainer's answer was that the
adapter wants `ExportedMessageRepository` format (`{message, parentId}` pairs,
via `ExportedMessageRepository.fromArray`), not a flat array. We do not hit that
today because the sidebar drives `thread.reset()` directly rather than going
through `useRemoteThreadListRuntime` — but that is the first thing to know if
anyone migrates to the remote thread-list runtime later.

---

## External services

These need API keys. All are optional at startup: the backend boots without
them, and a feature that needs a missing key fails with a clear message when
you use it, rather than blocking the whole team at boot.

Add every new key to [`.env.example`](./.env.example) — **never** to `.env`,
which is gitignored and holds your real values.

| Service | Env var | What it does | Free tier? |
|---|---|---|---|
| [Anthropic](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` | The planner LLM. | Paid, credit-based. |
| [OpenAI](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` | Embeddings for the search index. | Paid; `text-embedding-3-small` is very cheap. |

Two more settings that are not third-party keys but live alongside them:

| Env var | What it does |
|---|---|
| `CONNECTOR_ENCRYPTION_KEY` | Encrypts personal access tokens before storage. Blank in development derives a key from `DJANGO_SECRET_KEY`; **required** once `DJANGO_DEBUG=false`. |
| `CRAWLER_USER_AGENT` | How our crawler identifies itself. PRD §3 requires that we say who we are — never set this to a browser user-agent string. |

### Public APIs we consume without a key

No credentials, but still dependencies — if one goes down mid-demo, so does a
lane. We are **unaffiliated consumers** of these public APIs (PRD §9).

| API | Used for |
|---|---|
| `course-tools.apis.scottylabs.org` | Course catalog, schedules, prerequisites. |
| `api.cmueats.com/v2/locations` | Dining locations and opening hours. Use v2 — the `dining.apis` endpoint is deprecated. |
| `tartanconnect.cmu.edu/mobile_ws/...` | Public campus events feed. |
| `canvas.cmu.edu/api/v1` | A student's own coursework — **only** with a token they paste in themselves. |

---

## Infrastructure

| Thing | Why |
|---|---|
| **Docker + Docker Compose** | Runs Postgres and the API so nobody installs Python or Postgres locally. |
| **Postgres 16** (`postgres:16-alpine`) | The database, and — via `pgvector` — the vector store too. |
| **Node.js LTS** | Runs Expo. Must be the **LTS** build: React Native does not support odd-numbered Node versions. |

---

## Rules of thumb before adding anything

1. **Does the standard library already do it?** A dependency is a thing that can
   break the build on someone else's laptop at 2am.
2. **Does it need a native build step?** Anything requiring compilation on
   install will cost a teammate an hour of their five-minute setup.
3. **Is it a second thing to run?** A package is cheap; a new service in
   `docker-compose.yml` is not.
4. **Write down why.** Add the row here in the same commit — that is the whole
   point of this file.
