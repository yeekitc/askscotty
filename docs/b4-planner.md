# B4 — The Planner

**What it is:** the thing that turns a question into a cited answer. It takes the
query, decides which tools to call, calls them, and writes the reply.

**Where it goes:** replaces the stub in `backend/apps/core/views.py:77`.

**Branch:** `b4-planner` · **Owner:** — · **Depends on:** nothing (see [Build order](#build-order))

---

## TL;DR

Read this if you read nothing else.

1. **Write a manual agentic loop.** Not the SDK's tool runner. It can't resume
   `pause_turn`, and that failure is silent.
2. **Most of B4 already exists** in `apps/tools/registry.py`. We're writing the
   loop, not the plumbing.
3. **Don't set `temperature`.** It's a 400 on our model.
4. **Never put the current time in the system prompt.** It kills prompt caching.
   Time goes in the user turn.
5. **Citations are collected by code, never written by the model.** The model
   only ever emits an id like `[S1]`.
6. **Two new citation fields (`snippet`, `id`) need agreeing now** — see
   [Contract change](#contract-change-snippet-and-id). This blocks nobody but
   gets expensive once B1/B2 write their tools.
7. **Drop the app's 30-second timeout** — a single search turn already takes ~26s.
   Then consider SSE for progress events, which is smaller than it sounds.

---

## What already exists — don't rebuild it

`backend/apps/tools/registry.py` is further along than the tasklist suggests.

| You might think you need to write | It's already there |
|---|---|
| Convert tools to Anthropic's format | `Tool.definition()` |
| Figure out which tools this user gets | `tools_for_session(session_id)` |
| Call a tool safely | `run_tool(name, args, session_id=...)` |
| Stop personal data leaking into public tools | `Tool.run()` — public tools can't receive `session_id` |
| Work out `modes_used` | `modes_for(tool_names)` |
| Stamp `is_mock` on a citation | `citation_defaults(tool)` |
| Log every tool call | `run_tool` does it |

**So B4 = the loop, and nothing either side of it.**

---

## Decision: manual loop, not the SDK tool runner

The Anthropic SDK ships a `tool_runner` that drives the loop for you. **We are
not using it.** Four reasons, heaviest first:

| Reason | Detail |
|---|---|
| **`pause_turn`** | A long web-search turn ends early with `stop_reason: "pause_turn"`. The Python runner **does not resume it** — it exits and hands back the paused turn as if finished. No error. The demo just silently truncates. In a manual loop this is 4 lines. |
| **Our tools aren't decorated functions** | The runner wants `@beta_tool`-decorated functions. Our registry is plain functions + hand-written JSON schemas. We'd re-declare everything. |
| **We need the transcript** | The runner keeps its own message list and won't show you. We need it to harvest citations and to build a partial answer on timeout. |
| **It's beta** | The manual loop isn't. |

---

## The loop, step by step

```
backend/apps/planner/
├── client.py      # Anthropic client, model/effort/timeout config
├── prompt.py      # system prompt (frozen) + volatile user-turn preamble
├── loop.py        # ← the actual loop
├── citations.py   # tool results → Citation dicts
└── errors.py      # PlannerError → the API error shape
```

Then `AskView.post` shrinks to: validate → `run_planner(...)` → serialize.

**The loop:**

1. Build the **tools array** from `tools_for_session(session_id)`.
2. Build the **system prompt** — frozen, cacheable, no timestamps.
3. Build **messages** = `history` + user turn. The user turn carries the query
   *and* the volatile preamble (current date/time, timezone).
4. Call `messages.create`.
5. **`stop_reason == "end_turn"`** → done, go to 10.
6. **`stop_reason == "pause_turn"`** → append the assistant turn, call again,
   back to 5. (Cap the resumes.)
7. **`stop_reason == "tool_use"`** → collect *every* `tool_use` block, run them
   (thread pool), append the assistant content, then append **one** user message
   containing **all** the `tool_result` blocks.
8. **Harvest citations** from those tool results, and from any
   `web_search_tool_result` / `web_fetch_tool_result` blocks in the assistant
   content.
9. **Check the deadline and the iteration cap.** Over either → one final call
   with `tool_choice: {"type": "none"}`, which forces prose out of what it has.
10. Extract text → validate markers → build payload → `AskResponseSerializer`.

---

## Model settings

We're on **`claude-sonnet-5`** (`PLANNER_MODEL`). Three things about this model
that will bite:

| Setting | Do this | Why |
|---|---|---|
| `temperature` / `top_p` / `top_k` | **Don't set them at all** | Non-default values are a **400** on this model. Steer with the prompt. |
| `thinking` | **Omit it** — adaptive is on by default | Disabling thinking makes the model *less* likely to call tools. That's the opposite of what a routing planner wants. And `budget_tokens` is a 400. |
| `output_config.effort` | Start at `"medium"`, env-configurable | Default is `high`. For tool routing, medium is plenty and it's our main latency lever. |

`max_tokens`: keep at or below **16000**. The contract is non-streaming
(frozen decision), and above ~16k the SDK starts refusing non-streaming calls.

---

## Six places this will break

### 1. Never put the time in the system prompt

Prompt caching is a **prefix match**. One changing byte early in the prompt
invalidates everything after it.

The planner *needs* to know it's "tomorrow at 4:20" — so:

- ❌ `system = f"Today is {datetime.now()}..."`
- ✅ Time goes in the **user turn**, after the cache breakpoint.

Put `cache_control` on the last system block. Check it actually worked once:
`response.usage.cache_read_input_tokens` should be non-zero on the second call.

### 2. Parallel tool results go back in ONE message

One assistant turn can contain several `tool_use` blocks. If you send their
results as separate user messages, **the model quietly stops making parallel
calls** for the rest of the conversation.

Our signature query has a parallel leg (Dining and Events, once Maps resolves),
so this matters. A small `ThreadPoolExecutor` around the dispatch is worth it —
the tools are all I/O-bound HTTP.

### 3. A failed tool is a result, not a gap

When a tool raises `ToolError`, send back a `tool_result` with
`is_error: true` and the message. **Do not drop the block** — that breaks the
tool_use/tool_result pairing and the API rejects the next call.

Doing it right is also what makes "degrade, don't crash" real: the model reads
the error and routes around a dead upstream mid-answer.

### 4. Server-side tools don't fit the registry

`web_search` and `web_fetch` run on **Anthropic's** servers. We declare them but
never execute them, and their output arrives as blocks inside the *assistant*
message.

So:
- the registry needs an `is_server_tool` flag → declare, never dispatch
- `citations.py` needs a second path for those blocks
- `modes_used` gets `web_verify` from a `server_tool_use` block, not from
  `run_tool`

**This is B4's job, not B3's.** B3 owns the domain allow/deny lists.

Four non-obvious rules come with them:

| Rule | Consequence if ignored |
|---|---|
| **Append assistant content back byte-for-byte.** Search results carry an `encrypted_content` field. | Missing or modified → **400 validation error** on the next call. Never reconstruct assistant blocks; append what you got. |
| **Mixing our tools and theirs in one turn defers the search.** If the model calls `campus_search` *and* `web_search` in the same parallel batch, you get `stop_reason: "tool_use"` and the search **has not run yet**. | A loop that assumes "tool_use means only my tools ran" mishandles the turn. Return our results; the API runs the search on the next request. |
| **Errors arrive as HTTP 200.** A failed search is a `web_search_tool_result_error` object inside `content`, with codes like `max_uses_exceeded`, `too_many_requests`, `unavailable`. | Uncaught → crash on a rate limit. Note `content` is an *object* on error and a *list* on success — branch before indexing. |
| **Set `response_inclusion: "excluded"`** on `web_search_20260318`. | Otherwise raw search content is echoed back in the response, and we pay output tokens for text we never show. |

### 5. Timeout → forced-text turn, not a 504

Keep a wall-clock deadline. When it trips, stop dispatching tools and make one
more call with `tool_choice: {"type": "none"}`. You get real prose from partial
data, plus a `note` explaining what was skipped.

### 6. Markers can reference sources that don't exist

See below. One hallucinated `[S7]` renders as a dead superscript in the demo.

---

## Citations

### The rule

> **The model never writes a citation. It only ever writes an id.**

Tools return citation data. The planner unions it. `citation_defaults()` stamps
`source` and `is_mock` from the tool that produced it.

This means the model **physically cannot** invent a source or relabel a mock as
live. PRD §9 enforced by construction, not by prompt.

### How markers work

1. As tool results come back, the planner assigns each citation a **stable id**:
   `S1`, `S2`, `S3`… monotonic across the whole turn.
2. Those ids go into what the model sees.
3. The system prompt requires an `[S1]`-style marker on factual claims.
4. **After the final turn, validate**: parse the markers out, drop any id we
   never issued, and note which issued ids went unreferenced.

### Web search citations are a separate harvest

Anthropic attaches its own citations to the **text** blocks it writes, as a
`citations` array of `web_search_result_location` objects — *not* only to the
`web_search_tool_result` block. Each one has `url`, `title`, and `cited_text`.

So `citations.py` reads two places for a web-verify answer: the result block
(what was searched) and the text blocks (what was actually cited). **The text
blocks are the ones worth harvesting** — they're the claims the model actually
leaned on, and they arrive with the snippet already filled in.

### What this does and doesn't protect against

| ✅ Can't happen | ⚠️ Can still happen |
|---|---|
| Model invents a source | Model puts the right id on the wrong sentence |
| Mock citation appears as live | An issued source goes uncited |
| Broken URL in a citation | |

Misattribution is the real cost of numbered markers. It's bounded and we accept
it — but say so out loud rather than claiming the citations are airtight.

---

## Contract change: `snippet` and `id`

**Needed for:** inline citations (tap a marker → see a preview).
**Blocks:** nobody today. **Gets expensive:** once B1/B2 write their tools.

A preview that shows only the title is pointless — and `title` is all we return
today. So `Citation` gains two fields:

| Field | Type | What it is |
|---|---|---|
| `id` | `string` | `"S1"` — what the model cites. Explicit, not positional, so filtering the list later can't silently break the mapping. |
| `snippet` | `string` | The supporting text excerpt. Empty string when there isn't one. |

**`domain` is NOT stored** — derive it from `url` at render time.

### Who fills in `snippet`

| Tool | Snippet is… |
|---|---|
| `campus_search` (B1) | the matched chunk text, truncated — it has this for free |
| `search_courses` (B2) | `"9 units · MWF 10:00 · Prof. Smith"` |
| `find_dining` (B2) | `"Open 08:00–20:00 · Wean Hall"` |
| `find_events` (B2) | `"Tue 6:00 PM · Gates 6115 · CMU AI Club"` |
| `web_fetch` / `web_search` (B3) | **free** — each citation carries `cited_text` (≤150 chars), and `cited_text`/`title`/`url` don't count toward token usage |

### Changes needed

- [x] `backend/apps/core/serializers.py` → add both fields to `CitationSerializer`
- [x] `frontend/app/lib/types.ts` → add both to `Citation`
- [x] `tasklist.md` §2 → record the amendment
- [x] `README.md` → API table, if it lists citation fields

### Bonus: this fixes a known deviation

Mock citations have `url: ''`, so they have no domain and no favicon. That slot
should show the **mock badge** instead — which finally does what PRD §9 asks and
`CitationCard.tsx`'s own docstring admits it currently skips (`is_mock` only
goes to the console today).

A marker sitting mid-sentence is exactly where "this claim is mock data" needs
to be visible.

---

## Inline citation UI (React Native)

### Why we're not using assistant-ui's element

Three reasons, and the third is the surprising one:

1. **It's web DOM.** shadcn + Tailwind + `@base-ui/react`. There's no DOM on
   iOS/Android for it to render into, `className` is inert in RN, and we have no
   Tailwind pipeline even for web.
2. **Its `Source` shape can't hold our data.** `{domain, title, snippet}` — no
   slot for `indexed_at`, `verified_at`, or `is_mock`.
3. **The exported component is a demo, not a citation renderer.** `InlineCitation`
   hardcodes its own paragraph of prose with exactly two insertion points.
   `sources[2]` and beyond are **silently dropped**. The genuinely reusable unit
   is an internal `Citation` component that isn't exported.

So even a React-DOM app would be reimplementing this. We're porting the
*pattern*.

### The marker is a chip, not a superscript

Worth correcting an early assumption. The real design is a small rounded-square
chip with a monospace number, nudged up 2px — not raised superscript text.

**The chip must be an inline `<Pressable>`, not a styled `<Text>`.** This is the
least obvious finding in the whole port, so here is the evidence.

A nested `<Text>` run can only carry the attributes in RN's `TextAttributes`:
colour, background, font, spacing, decoration, shadow. **There is no padding, no
border, no transform, no baseline offset.** So on native:

| Technique | iOS | Android | Web |
|---|---|---|---|
| `transform: translateY` on nested `<Text>` | ❌ ignored | ❌ ignored | ❌ ignored\* |
| `padding` / `borderRadius` on nested `<Text>` | ❌ ignored | ❌ ignored | ✅ works |
| `lineHeight` trick | ❌ shifts the whole paragraph | ⚠️ unreliable | — |
| Unicode superscript (`¹²³`) | ✅ | ⚠️ **only ¹ ² ³ ⁴** | ✅ |
| **Inline `<Pressable>` inside `<Text>`** | ✅ | ✅ *needs explicit w/h* | ✅ |

\* Not a React Native quirk — CSS transforms don't apply to non-replaced inline
boxes, and RNW renders nested Text as `display: inline`.

The `padding`/`borderRadius` row is the dangerous one: it **works on web and
silently does nothing on a phone**, the worst possible failure mode, because it
looks finished in the browser.

**Android needs an explicit `width` and `height` on the chip.** Inline views
can't size to their content there, so width has to be computed from the digit
count.

The `lineHeight` trick deserves a specific warning since it's the common
suggestion online: on iOS the baseline offset is computed from the *maximum*
line-height across the range and applied to the **entire range**, never per run.
Raising one marker raises the whole paragraph.

Inline views, meanwhile, are better supported than their reputation: Fabric lays
them out as real attachments with frames, Android baseline-aligns them via a
`ReplacementSpan`, iOS via `NSTextAttachment`, and react-native-web explicitly
gives a `View` inside a `Text` `display: inline-flex`.

**And an inline `Pressable` is the only option that gives us `hitSlop`,
`borderRadius`, `transform`, first-class hover props, and measurability.** The
nested-`Text` path can't do the chip at all.

**Fallback if it misbehaves on a real device:** a nested `<Text onPress>` at
~0.7× font size with a `backgroundColor`, sitting **on** the baseline rather than
raised. Not a true superscript, but 100% reliable everywhere. Add
`borderRadius`/`padding` behind `Platform.OS === 'web'` for the pill look on web
only.

**Do *not* fall back to Unicode superscript digits.** Roboto only covers ¹ ² ³ ⁴
— `⁰` and `⁵`–`⁹` fall through to Android's Noto fallback at a different weight
and metrics, so a citation list looks fine up to 4 and then visibly degrades.
With an explicit custom `fontFamily`, Android may suppress the fallback entirely
and render tofu.

*Web-only nicety:* `verticalAlign: 'super'` passes straight through to real CSS
on react-native-web (no-op on native, needs a TS cast). Free polish where it
works.

| Marker state | Original | Our tokens |
|---|---|---|
| Closed | bg `foreground @ 6%`, text `foreground @ 45%` | `colors.sidebarHover` bg, `colors.textMuted` text |
| Hover (web) | text → `foreground @ 90%` | `colors.text` |
| **Open** | **fully inverted** — solid bg, background-coloured text | `colors.accent` bg, `colors.accentText` text |

The inversion is the main affordance — it's what tells you which chip the open
card belongs to. **Keep it.**

Other marker facts: 1-based numbering, 16px tall, monospace 10px, 2px margin
each side, `tabular-nums` (RN: `fontVariant: ['tabular-nums']`, only matters at
2+ digits).

### The card, top to bottom

256px wide, radius 16, padding 14. Four rows — the fourth is ours:

| Row | Content |
|---|---|
| 1. Header | 16px avatar square + domain text (mono, 11px, muted) |
| 2. Title | 13px, weight 500 |
| 3. Snippet | 13px, muted |
| 4. **Freshness + mock badge** | **our addition** — `indexed_at` / `verified_at`, and the mock badge |

**The avatar is one character** — literally `domain[0].toUpperCase()`. Not
initials, not a favicon. `www.cmu.edu` → `W`, because `www.` isn't stripped. If
we copy this, strip `www.` first.

**Mock citations have no `url`, so no domain, so no avatar letter.** That slot
takes the mock badge instead — `colors.mockBadge` already exists in `theme.ts`.
This is how PRD §9's "label mock data" finally gets satisfied.

### Interaction: what changes for touch

The original is **mouse-only by construction** — `mouseOnly: true` means tapping
it does literally nothing, and Base UI's own docs say preview cards "are not
accessible to touch or screen reader users."

| Behaviour | Original | Ours |
|---|---|---|
| Open | hover, 0ms | **tap** (primary), hover on web |
| Close | hover-out after 300ms | tap outside, tap again, or a close control |
| Diagonal pointer travel | `safePolygon()` | **drop** — no touch analogue |
| Click/tap | nothing | opens |
| Escape / outside press | closes | keep both |
| One open at a time | `openIndex: number \| null` in the parent | **keep** — clean pattern, ports as-is |
| Hit target | 16px chip | ✋ **way below the 44pt minimum** — needs `hitSlop` |
| Screen readers | unsupported | needs a real `accessibilityLabel` and role |

The 0ms-open / 300ms-close delays are hover hysteresis. With tap they're noise —
open instantly, close on next tap.

### Animation

**Keep:** marker colour inversion; card enter at opacity 0→1 + scale 0.97→1 over
200ms with a strong ease-out (`cubic-bezier(0.23, 1, 0.32, 1)`).

**Drop:** dynamic transform-origin, `z-50`/Portal (RN has neither), and
`motion-reduce` unless we're already reading `AccessibilityInfo`.

### ⚠️ Collision avoidance is free on web and absent in RN

Base UI's positioner flips the card and clamps it to the viewport automatically.
**We get none of that.** A 256px card anchored to a marker near the screen edge
will just overflow.

This is the single biggest argument for a bottom sheet on phone rather than an
anchored card: it sidesteps positioning entirely.

### Where the card renders: screen level, one component, two placements

**Decision: an absolutely-positioned overlay at screen level — a sibling of the
`FlatList`, not a child of the message row, and not a `Modal`.**

Why not inside the message row, which would be the obvious choice? Because
`Thread.MessagesFlatList` is a real `FlatList`, and **`removeClippedSubviews`
defaults to `true` on Android.** A card that overflows its row can be clipped or
unmounted mid-interaction. (Plain `View`s don't clip — the hazard is specifically
the virtualised list.)

Why not `Modal`? It only buys us dismissal semantics, and a backdrop `Pressable`
gives us that at a fraction of the weight. A full modal for a lightweight preview
feels wrong.

**We already have this exact pattern in the codebase** — the mobile sidebar
drawer at `app/index.tsx:392-403` is a full-bleed `Pressable` backdrop plus an
absolutely-positioned panel. Copy that shape.

| | Placement | Opens on |
|---|---|---|
| **Phone** | pinned to the bottom above the composer, full-width, backdrop to dismiss | tap |
| **Web / wide** | anchored near the marker using its measured rect | tap **and** hover |

`isWide` already exists in `index.tsx`, so this is one branch on placement style,
not two components. The phone placement needs **no measurement at all** and
sidesteps the collision problem entirely — it's a lightweight sheet without the
dependency.

State lives in a small context: *which citation is open* + *its anchor rect*.
`ChatMessage` sets it from deep inside the FlatList. One piece of state gives us
"only one open at a time" for free — the same `number | null` shape the original
uses.

### Measuring: web only. Never on native.

**Rule: don't measure anything on a phone.** The bottom-pinned placement needs no
anchor rect, so we simply never ask for one.

That isn't just convenience — measuring inline content on Android is a trap with
no clean exit:

| Problem | Detail |
|---|---|
| **`.measure` returns `undefined`** | View flattening. Fixed by `collapsable={false}`… |
| **…but `collapsable={false}` breaks touch** | It re-exposes Android's touch-clipping bug, where taps outside a view's bounds are rejected. **The two requirements directly conflict.** |
| **Ancestor chain must be layoutable** | The chip must be a **direct child of the outermost `<Text>`**. One inner `<Text>` in the chain zeroes the measurement — and segmented rendering naturally tempts you into exactly that nesting. |
| **`Modal` is worse** | `measure`/`onLayout` return `0` for views inside an Android Modal, so you couldn't flip or clamp the card even if you wanted to. Expo also recommends against RN `Modal` under edge-to-edge. |

Not measuring on native sidesteps every row of that table, plus the FlatList
clipping problem. **It also means the marker's visual form is now a pure
look-and-ergonomics choice** — nothing structural depends on it.

On web, where it's reliable:

- Use **`measureInWindow`** — `measure` and `onLayout` are parent-relative.
- **Not `onLayout`**: RNW implements it with `ResizeObserver`, which doesn't fire
  for non-replaced inline elements. (`onTextLayout` is native-only and unsupported
  by RNW, so that's out too.)
- **Measure on press/hover, never at mount.** Rects go stale as soon as the list
  scrolls.
- **Close the card on scroll** rather than repositioning. Tracking every scroll
  frame is jank, and dismiss-on-scroll is what native UIs do anyway.

### Parsing the markers

```ts
const MARKER = /\[S(\d+)\]/g
// [S1] -> citations[0]
```

Split the answer into text/marker segments, wrap **only** the markers, leave
prose as plain strings so the parent `<Text>` wraps normally.

Verified against leading, trailing, adjacent (`[S1][S2]`), multi-digit (`[S12]`),
absent, and newline-containing cases.

Two traps:
- **Don't `.trim()` segments or join with `{' '}`.** Whitespace is already
  correct because it stays inside the text segments; "fixing" it is what breaks
  spacing.
- **Guard against out-of-range.** The model can emit `[S5]` when there are four
  citations. Render the raw text unchanged rather than a dead marker. (The
  backend validator should catch this first — this is belt and braces.)

### 🔬 One thing to smoke-test on a real device

**How an inline view vertically aligns is genuinely unresolved.** Android's source
says it sits baseline-bottom (`fm.ascent = -height; fm.descent = 0`), but a
long-standing issue reports it rendering centred instead — though that report
used `Image`, which takes a different span path. Nobody could close this from
source alone.

**Expect to need a `Platform.select` vertical nudge**, and check the chip on a
physical Android device before polishing anything.

Scope of the risk: this affects **only the marker's appearance**, not the
architecture. The popover design above holds either way, and the nested-`Text`
baseline chip is the fallback.

### No grouping, no dedupe

One marker per source, numbered by array position. Two adjacent markers are just
two chips. If the same source backs three sentences, that's three chips with the
same number. Fine for P0 — worth revisiting only if answers get marker-heavy.

---

## Cross-lane flags

Not B4's boxes, but B4 is what makes them hurt.

### ✅ The 30s client timeout is going away

`frontend/app/lib/api.ts` aborts at 30 seconds. Tasklist §1 measured a *single*
searching turn at ~26 seconds, so a four-hop answer never lands inside it.

**Decided: remove it.** Keep a much longer backstop (~2 min) so a genuinely hung
request still fails rather than spinning forever.

That fixes *failing*. It does nothing for *feeling slow* — see below.

### 🟢 Web tool version strings — checked, tasklist is correct

`web_search_20260318` / `web_fetch_20260318` are current. There are three
versions and `_20260318` is the newest:

| Version | Adds |
|---|---|
| `web_search_20250305` | basic search |
| `web_search_20260209` | dynamic filtering |
| `web_search_20260318` | `response_inclusion` — **use this one** |

### 🟠 Web search must be enabled for the org

If an admin has disabled it in the Claude Console, declaring the tool fails with
a **400**, not a graceful in-result error. Worth confirming once before demo day
rather than discovering it live.

---

## Streaming

Three things get conflated under "streaming". They're independent and worth
separating before anyone builds:

| # | Thing | Status |
|---|---|---|
| 1 | **Client timeout** — request fails at 30s | ✅ decided: remove it |
| 2 | **Backend ↔ Anthropic** — we call `messages.stream()` internally | 🟢 do it, no contract change, invisible to the app |
| 3 | **Backend ↔ app** — SSE to the client | ✅ **we want this** — build it |

**(2) is free and we should just do it.** Long turns risk HTTP timeouts on the
non-streaming path, and the SDK refuses large `max_tokens` without streaming.
Nothing about our API contract changes — the loop still returns one payload.

**(3) is the one that needs a decision**, because tasklist §1 froze "Streaming:
no" for P0 with "revisit only if the demo feels slow, and agree SSE here first."

### Two things make (3) cheaper than it looks

**The frontend is already shaped for it.** `createHttpAdapter` is
`async *run(...)` — an async *generator* that happens to yield exactly once
today. Streaming is more yields, not a restructure.

**We probably don't need token streaming.** F1 already wants a loading state
that shows *which mode is running* and calls it "the demo's wow moment." That
needs a handful of progress events, not a token feed:

```
mode_start   { mode: "courses" }     → light up the chip
mode_end     { mode: "courses" }
done         { ...AskResponse }      → the payload we already send
```

Answer-text deltas can be added later as another event type without changing
anything else.

### Added since: `text_delta`, and it cost nothing else

The prediction held — adding it changed no other event, no serializer and no
endpoint. `stream_message` yields text as it arrives and finally yields the
`Message`; the loop forwards each chunk as an event. Two things learned:

- **Text before a `mode_start` is preamble, not answer.** The model narrates
  itself into a lookup ("let me check dining hours"), and that text is discarded
  from the final answer. The app clears what it has when a lane starts, so one
  rule handles it with no extra event.
- **It is chunky, not a typewriter.** Measured on a short answer: the API sent 8
  pieces, 15/16/19/13/17/**205/163/74** chars — small at first, then lumpier as
  generation speeds up. Coalescing tiny deltas server-side is still worth it
  (each one costs an SSE frame, a re-render, and a full re-serialisation of the
  thread in `index.tsx`'s save path), but nothing makes the API's own batching
  finer. If a smooth typewriter is ever wanted, it has to be faked client-side.

### The guideline worth committing to now

> **The final `done` event carries the same validated `AskResponse` we send
> today.**

That keeps SSE strictly additive: the non-streaming endpoint stays as a fallback,
the serializer keeps validating, and nothing already built has to change.

### Write the loop as a generator from day one

This is the decision that stops streaming being a rewrite. **`run_planner` yields
events and finishes with the payload** — then both endpoints are thin wrappers
over one implementation:

```
run_planner(...)  ──yields──►  mode_start · mode_end · … · done{AskResponse}
                                   │
   POST /api/ask/         ─────────┤  drain it, return the last event
   GET  /api/ask/stream/  ─────────┘  forward each event as SSE
```

A loop that *returns* a payload has to be rewritten to stream. A loop that
*yields* doesn't. Cost is the same on day one.

### ✅ Answered: the transport is XHR, not fetch

The suspicion was right. **RN's `fetch` cannot read a streamed response**, and
it's not a gap that might close in a patch release:
`react-native/Libraries/Network/fetch.js` is three lines that `require('whatwg-fetch')`
— the XHR-backed polyfill, version 3.6.20 here. It has **zero** references to
`ReadableStream` and defines no `body` getter, so `response.body` is `undefined`
on iOS and Android. On web, react-native-web leaves the browser's real `fetch`
alone and `response.body` works — which is the trap, because it means the fetch
approach looks finished in a browser and is dead on a phone.

**XHR delivers partial bodies on all three platforms.**
`XMLHttpRequest.__didReceiveIncrementalData` appends to `_response` and fires a
LOADING `readystatechange` plus a `progress` event. It is gated, though: RN only
asks the native layer for incremental delivery when `onreadystatechange` or
`onprogress` is set **at `send()` time**, or `addEventListener('progress')` was
called first. Assign the handler before sending or the body arrives in one piece
at the end.

So: one code path, `askEvents()` in `lib/api.ts`, no `Platform.select`. Read the
growing `responseText` from a saved offset and split on `\n\n`.

### Known gotchas

- **Gunicorn sync workers hold one worker per open SSE connection.** Fine at demo
  scale; worth knowing before anyone deploys it.
- **Thread persistence saves on change, debounced ~600ms.** Streaming produces far
  more changes — check that doesn't thrash `PUT /api/threads/`.
- Streaming and artifacts compose: an artifact becoming ready is just another
  event type. See [artifact-plan.md](./artifact-plan.md).

## Build order

**The loop can be finished before B1/B2/B3 land.** Every tool currently raises
`ToolError`, which is the same path a real outage takes — so the degrade logic
gets exercised from day one.

- [x] `client.py` — Anthropic client, config from env
- [x] `prompt.py` — system prompt + user-turn preamble
- [x] `loop.py` — the loop, ending at `end_turn`, with the iteration cap
- [x] Wire `AskView` to it; delete the stub
- [x] `citations.py` — harvest from tool results, assign `S1`… ids
- [x] Marker validation
- [x] `pause_turn` resume
- [x] Deadline → forced-text final turn
- [ ] Server-tool support (`is_server_tool`, result-block parsing) — deferred with
      B3: it cannot be tested before the lane exists
- [x] Parallel dispatch (`ThreadPoolExecutor`)
- [x] SSE: `POST /api/ask/stream/`, and `askEvents()` on the app side
- [ ] Re-test against each real tool as its lane lands
- [ ] Signature multi-hop, end to end, cold start

**One thing the plan did not anticipate.** With *no* tools registered — today's
state — a prompt that says "everything factual comes from a tool" makes the model
try to satisfy it by writing a tool call out as prose. The fix belongs on the
volatile side: when the toolset is empty the user turn says so and asks for an
answer that admits it could not check. Keeping that out of the system prompt is
what keeps the cached prefix frozen.

### Frontend (inline citations) — separate, and P1

Zero new dependencies. Everything needed is RN core + react-native-web.

- [ ] 🔬 **Smoke-test the chip's vertical alignment on a real Android device** —
      decides marker form only; the rest is unaffected
- [ ] `CitationMarker` — inline `Pressable` chip, **direct child of the outermost
      `<Text>`**, explicit `width`/`height` for Android, `hitSlop`,
      `accessibilityRole="button"`, `accessibilityLabel="Source 1: <title>"`
- [ ] Marker segmentation + `AnswerText` component
- [ ] Swap the `renderText` arrow at `ChatMessage.tsx:36` for `<AnswerText>`
- [ ] Read sibling sources via `useAuiState((s) => s.message.content)` —
      `renderText` can't see them from its own args
- [ ] Open-citation context (which id, plus an anchor rect **on web only**)
- [ ] Screen-level overlay + backdrop, mirroring the drawer at `index.tsx:392-403`
- [ ] Card body — **reuse `CitationCard`**, it already renders the required
      `indexed_at`/`verified_at` freshness line
- [ ] Phone placement (bottom-pinned, no measurement) / wide placement (anchored)
- [ ] Close on scroll (web)
- [ ] Mock badge in the avatar slot — closes the PRD §9 gap
- [ ] Hover on web (`onHoverIn`/`onHoverOut`, safe to pass unguarded)
- [ ] `npx tsc --noEmit` clean

---

## Open questions

- **Effort level.** Starting at `medium`. Needs measuring against real
  multi-hop once B2's tools exist.
- **History depth.** Contract allows 40 turns. Do we send all of them, or
  truncate? Long histories are the main uncontrolled cost here.
- **Web-search context doesn't survive a follow-up.** Our `history` contract is
  `[{role, content: string}]` — plain text. The `encrypted_content` that lets
  Anthropic restore search results into context only survives if you replay the
  original content *blocks*, which our contract flattens away. So "is that still
  current?" as a follow-up re-searches from scratch rather than reusing the
  previous turn's results. Acceptable for P0; note it before anyone treats
  follow-ups as cheap.
- **Marker density.** One per sentence, or one per claim? Too many markers make
  the prose unreadable; too few make the citations decorative.
