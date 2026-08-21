# Dependencies

Everything AskScotty depends on, and **why**. The version will change; the
reasoning is what tells you whether a swap is safe.

**Adding something? Add a row here in the same commit.** A package with no line
here is a package nobody can safely remove later, because nobody remembers what
it was for.

Tables carry the short answer. The dropdowns hold the decision behind it — open
one before changing or removing that thing.

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
| `Django` | The web framework, on the **5.2.x LTS**. Never 5.1 — see below. |
| `djangorestframework` | Serializers are the API contract in code (tasklist §2); the browsable form at `/api/ask/` lets a non-technical teammate poke the API. |
| `django-cors-headers` | The Expo app calls the API from a different origin. Without it every browser request fails. |
| `psycopg2-binary` | Postgres driver. The `-binary` wheels are prebuilt, so nobody installs Postgres headers. |
| `python-dotenv` | Loads `.env` in `config/settings.py`. |
| `gunicorn` | Production WSGI server. Idle locally — compose overrides with `runserver` — so the image is deployable as built. |
| `whitenoise` | Django admin's static files without a second web server. |
| `anthropic` | The planner **and** the web-search lane. Also *is* the agent platform. |
| `openai` | **Embeddings only** (`text-embedding-3-small`). Anthropic has no embeddings endpoint. |
| `pgvector` | Vector column and index types for Django/psycopg. One database instead of two. |
| `cryptography` | Fernet encryption for personal credentials at rest (PRD §9). |
| `httpx` | HTTP client for the crawler and live tools: timeouts, connection reuse, one retry policy. |
| `beautifulsoup4` | HTML → clean text for the crawler. |
| `piazza-api`, `gradescopeapi` | The Piazza and Gradescope connectors. ⚠️ **These store a password** — see below. |

<details>
<summary><b>Django 5.2 LTS — why not 5.1</b></summary>

5.1 is end-of-life and carries an unpatched critical SQL-injection advisory
(CVE-2025-64459). DRF 3.16 was the first release supporting Django 5.1+; we run
3.18, which targets 5.2.

</details>

<details>
<summary><b>Why a second AI provider just for embeddings</b></summary>

Anthropic has no embeddings endpoint, so the vector half of hybrid retrieval
needs someone else. `text-embedding-3-small` at 1536 dimensions is the one narrow
job `openai` does.

A local `sentence-transformers` model needs no key and no per-call cost, but adds
~2GB to the image and slows container start enough to hurt a five-minute setup.
Revisit if API budget becomes the binding constraint.

Changing the model means a migration and a full re-index, not just an env var:
the dimension is baked into the pgvector column.

</details>

<details>
<summary><b>Why pgvector rather than a real vector database</b></summary>

Keeping vectors in the Postgres we already run means one database to start, back
up and ship a demo fixture from. Chroma, Qdrant and Pinecone each add a moving
part to a setup that has to work first try on a teammate's laptop.

The Postgres **extension** is enabled by the first migration; this package is only
the Django/psycopg integration.

</details>

<details>
<summary><b>httpx over requests, beautifulsoup4 over lxml</b></summary>

`requests` has no default timeout — exactly the failure mode that hangs a demo.
`httpx` is also already in the image, since both AI SDKs use it.

`beautifulsoup4` strips nav/footer/script/style and walks the tree for
heading-segmented text ([`apps/rag/crawler.py`](../backend/apps/rag/crawler.py));
`html.parser` alone gives a DOM but no tree-walk or tag-removal API. `lxml` is
faster but its C extension fails without `libxml2-dev`, and the crawler is
network-bound anyway.

</details>

### ⚠️ Piazza and Gradescope store a password

Neither service issues students an API token, so connecting either stores their
**real password** — encrypted, but decryptable by us, and not revocable without
changing their login. That is materially worse than Canvas's PAT, and it was
accepted deliberately rather than by default.

<details>
<summary><b>The full trade-off, and what will bite you</b></summary>

Read [b5-piazza-gradescope.md](./b5-piazza-gradescope.md) before adding anything
else in this shape.

| Package | Notes |
|---|---|
| `piazza-api` | Posts to `piazza.com/class` and scrapes the response for an error string, so a login-page change breaks it with no deprecation warning. `search_feed(query)` is a real server-side search, which is why the tool does not page through `iter_all_posts`. |
| `gradescopeapi` | The risk lands harder: `Assignment` carries `grade` and `max_grade`, so a leaked credential exposes grades, not just deadlines. The PyPI name is `gradescopeapi` — the repo's `gradescope-api` is not on PyPI at all. Drags `fastapi` and `pytest` in as *runtime* requirements, a packaging bug on their side; we import neither. |

</details>

<details>
<summary><b>The loop runs on Managed Agents — not tool_runner, not our own</b></summary>

No new dependency: same `anthropic` package, under `client.beta.agents` and
`client.beta.sessions`. Worth recording because it changes what the package *is*
to us — an SDK we call becomes a platform we run on.

| Alternative | Why not |
|---|---|
| `client.beta.messages.tool_runner()` | **Does not resume a `pause_turn`.** A long web-search turn ends early and the runner returns the paused turn as if finished, with no error — the demo silently truncates. Also wants `@beta_tool`-decorated functions where our registry is plain functions plus hand-written schemas, and hides the message list. |
| Our own loop | Worked, but the platform gives durable sessions, cancel and compaction for free, and takes `pause_turn` off our hands — the very thing that ruled out the runner. |
| `claude-agent-sdk` | A different package: Claude Code as a library. Built-in Read/Write/Edit/Bash over a filesystem we do not have, custom tools only via MCP, and an in-process shell that would ingest crawled pages. Wrong product for a routing planner. |

The trade we accept — a network round trip per tool batch — is in
[b4-planner.md](./b4-planner.md).

Default model `claude-sonnet-5`: the planner routes and selects tools rather than
reasoning deeply, at roughly half Opus's per-token cost. Set
`PLANNER_MODEL=claude-opus-5` if multi-hop answers come out weak; nothing else
changes.

</details>

<details>
<summary><b>No search provider: Claude searches server-side</b></summary>

`web_search_20260318` and `web_fetch_20260318` run on Anthropic's infrastructure
under `ANTHROPIC_API_KEY`. Their parameters cover the entire B3 requirement list,
which is why `tavily-python` was removed and **why a search provider should not be
added back** without re-running the test below.

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
filtering is built in, and a second execution environment confuses the model), and
handle `pause_turn`, which otherwise ends the loop early looking like a finished
answer.

</details>

<details>
<summary><b>edapi: declined — the Ed path is a direct call</b></summary>

Ed Discussion was going to use `edapi`, once believed to authenticate by scraping
a browser cookie. Its source settles both halves: it uses the same official Bearer
token as Canvas (`edstem.org/us/settings/api-tokens`), and there is nothing it does
that the two endpoints we need — `GET user`, `GET courses/{id}/threads` — do not do
in one line each through `apps.core.http.get_json`. Do not add it without a reason
those two calls cannot cover.

</details>

---

## Frontend — npm

One Expo/React Native app that runs on iOS, Android and web from the same source.

| Package | Why it's here |
|---|---|
| `expo` | The toolchain. Runs on a phone, a simulator and the browser without Xcode or Android Studio. |
| `expo-router` | File-based routing: `app/about.tsx` → `/about` on all three platforms. |
| `expo-constants` | Reads `EXPO_PUBLIC_*` config at runtime — how the app finds the API URL. |
| `expo-linking` | Deep links, and opening citation URLs in the system browser. |
| `expo-status-bar` | Status-bar styling that behaves the same on both mobile platforms. |
| `react`, `react-dom` | React itself; `react-dom` is required by the web target. |
| `react-native` | The component primitives (`View`, `Text`, `Pressable`, `TextInput`). |
| `react-native-web` | Translates those into real HTML — what makes "one frontend, three platforms" true rather than aspirational. |
| `react-native-safe-area-context` | Keeps content clear of notches and home indicators. |
| `react-native-screens` | Native screen primitives for smooth navigation transitions. |
| `react-native-reanimated` | Every microinteraction — assistant-ui ships no animation code. |
| `@assistant-ui/react-native` | The chat surface: message list, composer, streaming-ready thread state. |
| `assistant-cloud` | ⚠️ **Required to build. Do not remove** — see below. |
| `@react-native-async-storage/async-storage` | Key-value storage that works on all three platforms. |
| `expo-image-picker` | Profile photo selection in `ConnectionsModal`, as a base64 data URL. |
| `react-native-svg` | SVG drawing for `TaskMap` — bezier edges, endpoint dots. Expo-managed, no Xcode step. |
| `typescript`, `@types/react` | Types. Keep `npx tsc --noEmit` clean. |

### ⚠️ `assistant-cloud` is a build requirement, not dead weight

It is imported nowhere in our source and `@assistant-ui/core` declares it an
*optional* peer, so it reads as removable. **It is not.** Uninstalling it fails
every bundle — web, iOS and Android.

<details>
<summary><b>Why, and why a typecheck won't catch it</b></summary>

Two things share this name: **Assistant Cloud, the hosted service** (thread storage
on assistant-ui's servers — we do not use it) and **`assistant-cloud`, the npm
package**, which is a hard build-time requirement regardless.

Core's React entry imports the cloud thread-history adapter unconditionally, that
adapter has a top-level `import "assistant-cloud"`, and Metro walks the graph
eagerly:

```
Unable to resolve module assistant-cloud from
  .../@assistant-ui/core/dist/react/runtimes/cloud/AssistantCloudThreadHistoryAdapter.js
```

**`npx tsc --noEmit` still passes when it is missing**, so neither a typecheck nor
grepping for imports will catch this — only a real bundle does. And because npm
does not auto-install optional peers, this direct entry is the only thing putting
it in a fresh clone's `node_modules`.

It can be aliased to an empty stub via a metro `resolveRequest` hook: measured at
~436K of install and ~17KB of web bundle (1% of 1.7MB). Tried and reverted — not
worth a resolver hack pinned to a module name upstream controls. Revisit only if
assistant-ui makes the import lazy.

</details>

<details>
<summary><b>Assistant Cloud, the service: evaluated and declined</b></summary>

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

One precedent worth keeping:
[issue #2182](https://github.com/assistant-ui/assistant-ui/issues/2182) is someone
building our design — DRF thread/message endpoints behind a custom
`historyAdapter`. It crashed because the adapter wants `ExportedMessageRepository`
format (`{message, parentId}` pairs), not a flat array. We do not hit that today
because the sidebar drives `thread.reset()` directly, but it is the first thing to
know if anyone moves to the remote thread-list runtime.

</details>

<details>
<summary><b>Why reanimated rather than RN's built-in Animated</b></summary>

`@assistant-ui/react-native` ships **no** animation code — the web package gets its
motion from Tailwind and Radix, neither of which crosses over — so the sidebar,
hero-to-thread handoff and typing-indicator crossfade are all ours.

react-native-web has no native driver, so `Animated` runs on the JS thread there.
The sidebar also animates a layout width, which stutters off the UI thread.

Needs no `babel.config.js`: `babel-preset-expo` wires `react-native-worklets/plugin`
itself. Tokens and the reduced-motion gate live in
[`lib/motion.ts`](../frontend/app/lib/motion.ts).

</details>

<details>
<summary><b>Markdown: hand-rolled on purpose</b></summary>

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

</details>

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

### Local

| Thing | Why |
|---|---|
| **Docker + Docker Compose** | Runs Postgres and the API so nobody installs Python or Postgres locally. |
| **`pgvector/pgvector:pg16`** | Postgres 16 with the `vector` extension present. ⚠️ Not `postgres:16-alpine` — see below. |
| **Node.js LTS** | Runs Expo. Must be an **even-numbered LTS** — React Native does not support odd releases. |

<details>
<summary><b>Why not a stock Postgres image</b></summary>

The first migration runs `CREATE EXTENSION vector`, which fails on a stock image.
The failure is quiet in the worst way: the app still starts, full-text search
still answers, and only the vector half of hybrid retrieval is silently missing.

</details>

### Deployed

| Platform | Role | Cost |
|---|---|---|
| **Render** | The API (Docker web service) and the app (static site), both from one blueprint. | Free tier; Starter $7/mo removes spin-down. |
| **Neon** | Managed Postgres 16 + pgvector. Serverless, scales to zero. | Free tier, no expiry. |
| **GitHub** | Source, and what Render auto-deploys from on push. | Free. |

<details>
<summary><b>Why not serverless — the constraint that rules out Vercel, Netlify and Lambda</b></summary>

`/api/ask/stream/` is SSE, and a worker is held for the whole life of the stream.
Serverless platforms buffer the response and cap the request at 10–60s. Answers
here measure **32–70 seconds** in production, so those platforms cannot host this
API at all — not as a tuning problem, as a design incompatibility.

The same measurement is why gunicorn runs `--timeout 300`. Its default is 30s and
a sync-family worker does not heartbeat mid-request, so every multi-hop answer
would have its worker killed and its stream cut. This never appears locally,
because compose overrides the command with `runserver`.

`gthread` rather than sync workers for the same reason: N sync workers would cap
the deployment at N concurrent questions.

</details>

<details>
<summary><b>Why Neon rather than Render's own Postgres</b></summary>

Render's free Postgres **expires 30 days after creation**, with a 14-day grace
period before the data is deleted. Neon's free tier does not expire, and both
support pgvector — so Neon costs nothing extra and removes a deadline.

The trade is a ~500ms wake on the first query after idle, since Neon scales to
zero. Harmless alone; it stacks with a Render cold start.

</details>

<details>
<summary><b>Free-tier hours: why not to keep the service warm with a pinger</b></summary>

A Render workspace gets **750 free instance hours per month** and a month is ~720,
so a service kept awake around the clock burns the allowance down to roughly a day
of margin. Exhaust it and Render **suspends every free web service in the workspace
until the next month begins** — trading a 50-second cold start for a multi-day
outage, arriving without warning.

A paid instance draws no free hours at all, which is the real argument for buying
one during any period when someone might arrive unannounced.

</details>

Deployment procedure, secrets and troubleshooting live in `docs/deploy.md`,
which lands on `main` when the `deploy` branch merges.

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
