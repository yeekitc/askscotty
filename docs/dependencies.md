# Dependencies

Everything AskScotty depends on, and **why**. The version will change; the
reasoning is what tells you whether a swap is safe.

**Adding something? Add a row here in the same commit.** A package with no line
here is a package nobody can safely remove later, because nobody remembers what
it was for.

- Backend versions are pinned exactly (`==`) in [requirements.txt](../backend/requirements.txt).
  After changing it: `docker compose up -d --build`. A plain restart is not enough.
- Frontend versions are ranges in [package.json](../frontend/app/package.json).
  Install with **`npx expo install <pkg>`**, never `npm install` — Expo resolves the
  version matching the installed SDK; npm will hand you a newer one that breaks
  the native build.

---

## Backend — Python

| Package | Why it's here |
|---|---|
| `Django` | The web framework, on the **5.2.x LTS**. Do not drop to 5.1: it is end-of-life and carries an unpatched critical SQL-injection advisory (CVE-2025-64459). |
| `djangorestframework` | Serializers are the API contract in code (tasklist §2), and the browsable form at `/api/ask/` is how a non-technical teammate pokes the API without writing any. 3.16 was the first release supporting Django 5.1+; we run 3.18, which targets 5.2. |
| `django-cors-headers` | The Expo app calls the API from a different origin. Without it every browser request fails. |
| `psycopg2-binary` | Postgres driver. The `-binary` wheels are prebuilt, so nobody installs Postgres headers to get the container running. |
| `python-dotenv` | Loads `.env` into the environment in `config/settings.py`. |
| `gunicorn` | Production WSGI server. Idle in development — compose overrides the command with `runserver` — so that the image is deployable as built. |
| `whitenoise` | Serves the Django admin's static files without a second web server. |
| `anthropic` | The planner **and** the web-search lane. Claude's tool use drives the multi-hop loop (Courses → Maps → Dining → Events) the demo is built on, and its server-side `web_search` / `web_fetch` are why no search provider appears below. Default `claude-sonnet-5`: the planner routes and selects tools rather than reasoning deeply, at roughly half Opus's per-token cost. Set `PLANNER_MODEL=claude-opus-5` if multi-hop answers come out weak — nothing else changes. |
| `openai` | **Embeddings only** (`text-embedding-3-small`), for the vector half of hybrid retrieval. Anthropic has no embeddings endpoint, so a second provider is unavoidable; this is the one narrow job it does. A local `sentence-transformers` model needs no key, but adds ~2GB to the image and slows container start enough to hurt a five-minute setup. |
| `pgvector` | Vector column and index types for Django/psycopg. Keeping vectors in the Postgres we already run means one database to start, back up and ship a fixture from — Chroma/Qdrant/Pinecone each add a moving part to a setup that must work first try on a teammate's laptop. The Postgres **extension** is enabled separately by the first migration; this package is only the integration. |
| `cryptography` | Fernet encryption for personal credentials at rest (PRD §9). Authenticated, so a tampered ciphertext fails loudly rather than decrypting to garbage. Also an indirect dependency of the SDKs above, pinned here because [`apps/personal/crypto.py`](../backend/apps/personal/crypto.py) imports it directly. |
| `httpx` | HTTP client for the crawler and the live-tool clients: timeouts, connection reuse and one retry policy without hand-rolling them. Already in the image as both SDKs use it. Not `requests`, which has no default timeout — exactly the failure that hangs a demo. |
| `beautifulsoup4` | HTML → clean text for the crawler ([`apps/rag/crawler.py`](../backend/apps/rag/crawler.py)): strips nav/footer/script/style and walks the tree for heading-segmented text. `html.parser` alone gives a DOM but no tree-walk or tag-removal API. Not `lxml`, whose C extension fails without `libxml2-dev` — and the crawler is network-bound, so parser speed is not the bottleneck. |

### The two connectors that store a password

`piazza-api` and `gradescopeapi` are unofficial, reverse-engineered clients, and
both authenticate with the student's **real email and password** — neither
service issues a scoped token. So connecting either stores a credential we can
decrypt, which the student cannot revoke without changing their login.

That is materially worse than Canvas's PAT, and it was accepted deliberately
rather than by default. Read [b5-piazza-gradescope.md](./b5-piazza-gradescope.md)
before adding anything else in this shape.

| Package | Notes that will bite you |
|---|---|
| `piazza-api` | Posts to `piazza.com/class` and scrapes the response for an error string, so a login-page change breaks it with no deprecation warning. `search_feed(query)` is a real server-side search, which is why the tool does not page through `iter_all_posts`. |
| `gradescopeapi` | The risk lands harder here: `Assignment` carries `grade` and `max_grade`, so a leaked credential exposes grades, not just deadlines. The PyPI name is `gradescopeapi` — the repo's `gradescope-api` is not on PyPI at all. Drags `fastapi` and `pytest` in as *runtime* requirements, a packaging bug on their side; we import neither. |

### The loop runs on Managed Agents

No new dependency — same `anthropic` package, under `client.beta.agents` and
`client.beta.sessions`. Worth recording because it changes what the package *is*
to us: an SDK we call becomes a platform we run on.

| Alternative | Why not |
|---|---|
| `client.beta.messages.tool_runner()` | **Does not resume a `pause_turn`.** A long web-search turn ends early and the runner returns the paused turn as if finished, with no error — the demo silently truncates. It also wants `@beta_tool`-decorated functions where our registry is plain functions plus hand-written schemas, and hides the message list. |
| Our own loop | Worked, but the platform now gives durable sessions, cancel and compaction for free, and takes `pause_turn` off our hands — the very thing that ruled out the runner. |
| `claude-agent-sdk` | A different package: Claude Code as a library. Built-in Read/Write/Edit/Bash over a filesystem we do not have, custom tools only via MCP, and a shell in-process that would ingest crawled pages. Wrong product for a routing planner. |

The trade we accept — a network round trip per tool batch — is in [b4-planner.md](./b4-planner.md).

### No search provider: Claude searches server-side

`web_search_20260318` and `web_fetch_20260318` run on Anthropic's infrastructure
under `ANTHROPIC_API_KEY`. Their parameters cover the entire B3 requirement list,
which is why `tavily-python` was removed and **why a search provider should not
be added back** without re-running the test below.

| B3 / PRD §6 needs | Built-in parameter |
|---|---|
| Site-filtered search (`site:cs.cmu.edu`) | `allowed_domains` |
| Allowlist of public hosts for `fetch_url` | `allowed_domains` |
| Canvas / SIO / Stellic never fetched | `blocked_domains` |
| Rate-limit the verify lane | `max_uses` |

Verified live rather than read off a docs page: a search restricted to
`cs.cmu.edu` returned 30 hits with **zero** off-domain leaks, and a blocked fetch
of `canvas.cmu.edu` failed with `url_not_allowed` — while the same URL under a
*non-covering* denylist failed with `url_not_accessible`. Two different codes, so
the denylist does real work rather than coinciding with Canvas being login-walled.
That control is the whole test; without it the result means nothing, because
Canvas fails either way.

**The cost is the catch.** Results land in the context window: one searching query
measured **~35.9k input tokens and ~26 seconds**. Verify only when the index is
genuinely stale, and cap with `max_uses` / `max_content_tokens`.

Two wiring traps: do not declare `code_execution` alongside these (dynamic
filtering is built in, and a second execution environment confuses the model),
and handle `pause_turn`, which otherwise ends the loop early looking like a
finished answer.

### `edapi`: declined, the Ed path is a direct call

Ed Discussion was going to use `edapi`, once believed to authenticate by scraping
a browser cookie. Its source settles both halves: it uses the same official
Bearer token as Canvas (`edstem.org/us/settings/api-tokens`), and there is
nothing it does that the two endpoints we need — `GET user`,
`GET courses/{id}/threads` — do not do in one line each through
`apps.core.http.get_json`. Do not add it without a reason those two calls cannot
cover.

---

## Frontend — npm

One Expo/React Native app that runs on iOS, Android and web from the same source.

| Package | Why it's here |
|---|---|
| `expo` | The toolchain. Runs on a phone, a simulator and the browser without anyone installing Xcode or Android Studio. |
| `expo-router` | File-based routing: `app/about.tsx` → `/about` on all three platforms. |
| `expo-constants` | Reads `EXPO_PUBLIC_*` config at runtime — how the app finds the API URL. |
| `expo-linking` | Deep links, and opening citation URLs in the system browser. |
| `expo-status-bar` | Status-bar styling that behaves the same on both mobile platforms. |
| `react`, `react-dom` | React itself; `react-dom` is required by the web target. |
| `react-native` | The component primitives (`View`, `Text`, `Pressable`, `TextInput`). |
| `react-native-web` | Translates those into real HTML, which is what makes "one frontend, three platforms" true rather than aspirational. |
| `react-native-safe-area-context` | Keeps content clear of notches and home indicators. |
| `react-native-screens` | Native screen primitives for smooth navigation transitions. |
| `react-native-reanimated` | Every microinteraction. `@assistant-ui/react-native` ships **no** animation code — the web package gets its motion from Tailwind and Radix, neither of which crosses over — so the sidebar, hero-to-thread handoff and typing-indicator crossfade are ours. Chosen over RN's `Animated` because react-native-web has no native driver, so `Animated` runs on the JS thread there, and because the sidebar animates a layout width, which stutters off the UI thread. Needs no `babel.config.js`: `babel-preset-expo` wires `react-native-worklets/plugin` itself. Tokens and the reduced-motion gate live in [`lib/motion.ts`](../frontend/app/lib/motion.ts). |
| `@assistant-ui/react-native` | The chat surface the ask screen is built on — message list, composer, streaming-ready thread state. |
| `assistant-cloud` | **Required to build. Do not remove** — see below. |
| `@react-native-async-storage/async-storage` | Key-value storage that works on **all three** platforms. Holds the anonymous session id ([`lib/session.ts`](../frontend/app/lib/session.ts)) and the source filter. `localStorage` is web-only: on a phone `window` does not exist, so guarding it meant native builds silently persisted nothing and lost every conversation on restart. |
| `expo-image-picker` | Profile photo selection in `ConnectionsModal`, returned as a base64 data URL for cross-platform storage. First-party Expo package, no native config beyond the managed workflow. |
| `react-native-svg` | SVG drawing for `TaskMap` — bezier edges between nodes, filled/hollow endpoint dots. Expo-managed install, no Xcode step. |
| `typescript`, `@types/react` | Types. The API contract in [`lib/types.ts`](../frontend/app/lib/types.ts) is only load-bearing because TypeScript enforces it — keep `npx tsc --noEmit` clean. |

### `assistant-cloud` is a build requirement, not dead weight

Two things share this name, and conflating them wastes an afternoon:

- **Assistant Cloud, the hosted service** — thread storage on assistant-ui's
  servers. We do not use it (see below).
- **`assistant-cloud`, the npm package** — a hard build-time requirement anyway.

`@assistant-ui/core` declares it an *optional* peer, so it reads as removable. It
is not: core's React entry imports the cloud thread-history adapter
unconditionally, that adapter has a top-level `import "assistant-cloud"`, and
Metro walks the graph eagerly. `npm uninstall assistant-cloud` fails every
bundle — web, iOS and Android:

```
Unable to resolve module assistant-cloud from
  .../@assistant-ui/core/dist/react/runtimes/cloud/AssistantCloudThreadHistoryAdapter.js
```

**`npx tsc --noEmit` still passes when it is missing**, so a typecheck will not
catch this and neither will grepping for imports — only a real bundle does. And
because npm does not auto-install optional peers, this direct entry is the only
thing putting it in a fresh clone's `node_modules`.

It can be aliased to an empty stub via a metro `resolveRequest` hook: measured at
~436K of install and ~17KB of web bundle (1% of 1.7MB). Tried and reverted — not
worth a resolver hack pinned to a module name upstream controls. Revisit only if
assistant-ui makes the import lazy.

### Assistant Cloud, the service: declined

Free at our scale (200 MAU), and still not worth it. We run our own storage in
[`apps/core/models.py`](../backend/apps/core/models.py) because:

1. **It bypasses Django rather than integrating.** Threads would live in their
   Postgres, not ours, with Django only minting a user token. But the planner
   needs conversation history — that is what `history` in `AskSerializer` is
   for — and it cannot join against a table it does not own.
2. **React Native does not get the turnkey path.** `@assistant-ui/react-native`
   exports only the generic `useRemoteThreadListRuntime`; the cloud adapter and
   hooks live in `@assistant-ui/core/react`. Cloud would have saved the database,
   not the adapter — which is most of the work.
3. **It is third-party storage of student chat history**, which sits badly beside
   PRD §9: answers here can quote someone's Canvas assignments.

One precedent worth keeping: [issue #2182](https://github.com/assistant-ui/assistant-ui/issues/2182)
is someone building our design — DRF thread/message endpoints behind a custom
`historyAdapter`. It crashed because the adapter wants `ExportedMessageRepository`
format (`{message, parentId}` pairs), not a flat array. We do not hit that today
because the sidebar drives `thread.reset()` directly, but it is the first thing to
know if anyone moves to the remote thread-list runtime.

### Markdown: hand-rolled on purpose

**No package.** [`lib/markdown.ts`](../frontend/app/lib/markdown.ts) parses the
subset the planner actually writes and `components/AnswerText.tsx` renders it.

This needed deciding because the model emits Markdown and nothing in our stack
renders it: assistant-ui's markdown support is a separate React-DOM-only package,
and `@assistant-ui/react-native` hands you `part.text` and expects you to render
it. Until this landed, `**bold**` reached the screen with the asterisks showing.

| Candidate | Why not |
|---|---|
| `react-native-markdown-display` | Unpublished since 2023, on `markdown-it@10` and `react-native-fit-image` — an unmaintained renderer against RN 0.86 + React 19 is a bet, not a saving |
| `@ronradtke/react-native-markdown-display` | Maintained, but pulls an icon font needing native linking **and** a syntax highlighter, to render three bullets and some bold |
| `react-native-marked` | Needs `react-native-svg` as a peer — a native module in an app whose selling point is that teammates never open Xcode |

The deciding argument is F2, though. Inline `[S1]` citation chips must be **direct
children of the outermost `<Text>`** ([b4-planner.md](./b4-planner.md)), and every
one of these libraries owns the whole text subtree. `AnswerText` funnels each leaf
string through one `renderSpanText` seam, which is where the chips go.

**Revisit if** answers start containing tables, images or nested lists — at that
point the subset stops being a subset.

---

## External services

All optional at startup: the backend boots without them, and a feature needing a
missing key fails with a clear message when used rather than blocking the team at
boot. Add every new key to [`.env.example`](../.env.example) — never to `.env`,
which is gitignored and holds real values.

| Service | Env var | What it does |
|---|---|---|
| [Anthropic](https://console.anthropic.com/settings/keys) | `ANTHROPIC_API_KEY` | The planner LLM, and the server-side search/fetch lane. Paid, credit-based. |
| [OpenAI](https://platform.openai.com/api-keys) | `OPENAI_API_KEY` | Embeddings for the search index. Paid; `text-embedding-3-small` is very cheap. |

Two settings that are not third-party keys but live alongside them:

| Env var | What it does |
|---|---|
| `CONNECTOR_ENCRYPTION_KEY` | Encrypts personal credentials before storage. Blank in development derives a key from `DJANGO_SECRET_KEY`; **required** once `DJANGO_DEBUG=false`. |
| `CRAWLER_USER_AGENT` | How the crawler identifies itself. PRD §3 requires that we say who we are — never set this to a browser user-agent string. |

### Public APIs consumed without a key

No credentials, but still dependencies: if one goes down mid-demo, so does a lane.
We are **unaffiliated consumers** of these (PRD §9).

| API | Used for |
|---|---|
| `course-tools.apis.scottylabs.org` | Course catalog, schedules, prerequisites. |
| `api.cmueats.com/v2/locations` | Dining locations and hours. Use v2 — `dining.apis` is deprecated. |
| `tartanconnect.cmu.edu/mobile_ws/...` | Public campus events feed. |
| `canvas.cmu.edu/api/v1` | A student's own coursework — **only** with a token they paste in themselves. |

---

## Infrastructure

| Thing | Why |
|---|---|
| **Docker + Docker Compose** | Runs Postgres and the API so nobody installs Python or Postgres locally. |
| **`pgvector/pgvector:pg16`** | Postgres 16 with the `vector` extension already present. Not `postgres:16-alpine`: the migration's `CREATE EXTENSION vector` fails on a stock image, and the vector half of retrieval silently never works. |
| **Node.js LTS** | Runs Expo. Must be an **even-numbered LTS** — React Native does not support odd releases. |

---

## Rules of thumb before adding anything

1. **Does the standard library already do it?** A dependency is a thing that can
   break the build on someone else's laptop at 2am.
2. **Does it need a native build step?** Anything compiling on install costs a
   teammate an hour of their five-minute setup.
3. **Is it a second thing to run?** A package is cheap; a new service in
   `docker-compose.yml` is not.
4. **Write down why, here, in the same commit.** That is the whole point of this
   file.
