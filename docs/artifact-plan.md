# Artifacts — answers that aren't just prose

> ⚠️ **Design sketch — none of this is built.** There is no `artifacts` field on
> the API response, no renderer registry, and no artifact route. Read this as a
> plan, not a feature list.
>
> It exists so the team has visibility and so we don't paint ourselves into a
> corner. Most of it is deliberately undecided. Where something *is* fixed, it's
> because a PRD rule or a platform constraint fixes it — not because someone
> picked a favourite.

---

## The idea

Some answers want to be more than a paragraph:

| Question | Better as |
|---|---|
| "How do I get from Wean to Gates?" | a campus map with a route |
| "What should I take next semester?" | a plan graph with prereq dependencies you can tick off |
| "What's my week look like?" | a schedule grid |

Ideally inline in the answer, **and** at a URL you can keep open in a tab.

---

## Legend

| | Meaning |
|---|---|
| 🟢 | **Fixed** — a PRD rule or platform constraint forces it |
| 🟡 | **Leaning** — current thinking, happy to be talked out of |
| ⚪ | **Open** — genuinely undecided, don't build on it yet |

---

## The shape

🟡 The response grows a third channel next to `answer` and `citations`:

```ts
artifacts: Artifact[]      // discriminated union on `type`
```

🟡 Each artifact is roughly `{ id, type, title, data, is_mock, fallback_text }`,
and the frontend keys off `type` into a renderer registry — the mirror image of
the backend's tool registry.

⚪ Everything about the actual `data` shapes. Those get designed per artifact
type, when we build that type. **Don't try to design a universal schema up
front** — it'll be wrong.

---

## Guidelines we're confident about

Four, each with its reason, so anyone can overrule them knowingly.

### 🟢 1. An unknown `type` must never crash the app

Phones run stale builds, so a client will meet artifact types it has never heard
of.

→ Every artifact carries `fallback_text`. Unknown type renders that. The
renderer registry always has a default case.

### 🟢 2. `is_mock` propagates to artifacts, and shows *in* the artifact

PRD §9 requires mock data be visibly labelled. A map built from our mock landmark
fixture is a mock map, and the map itself has to say so — a badge on a citation
underneath doesn't count when the thing someone is looking at is the map.

→ Derive `is_mock` from the contributing tools, the same mechanical way
`citation_defaults()` already does it.

### 🟢 3. Anything derived from personal data is session-scoped

PRD §7. A study plan built from Canvas is personal; a campus map isn't.

→ An artifact inherits the tier of the tools that produced it. If any
contributing tool was personal, fetching it requires the `X-Session-Id` header.
Otherwise a guessable URL leaks someone's schedule.

### 🟡 4. Rendering inputs should be references, not facts

`render_map({ landmark_ids: ["gates", "wean"] })` rather than
`render_map({ pins: [{lat, lng}] })`.

The reasoning is the same as `[S1]` citation markers: **if the model names things
instead of authoring them, it can't invent them.** The planner resolves ids
against what the tools actually returned, and an unresolvable id is a validation
error rather than a wrong pin on a map.

Marked 🟡 not 🟢 because some artifact types may not have a natural id space —
a synthesised plan graph might not. Worth holding to where it's possible.

---

## Two kinds of artifact, different trust levels

🟡 Different amounts of trust behind them:

| | Source | Example | Risk |
|---|---|---|---|
| **Tool-derived** | structured data a tool already returned | map pins, schedule, events list | low — the model only chose which tool ran |
| **Model-authored** | synthesised across several tools | study-plan dependency graph | higher — nothing else produces this, so nothing else can check it |

⚪ **How the model authors one is open.** The option that fits our existing
machinery is a *rendering tool* — `render_plan_graph(...)` registered like any
other tool, with `strict: true`, which gets schema validation from the API for
free and reuses registry, dispatch and logging unchanged. But we haven't tried
it, and structured outputs on the final turn is a real alternative.

---

## What React Native forces

### 🟢 We can't embed someone else's map

No iframes on native, and CMU Maps has no public REST API (PRD §5). A WebView
would be web-only, which breaks the one-codebase rule in [CLAUDE.md](../CLAUDE.md).

→ Deep-link out to cmumaps, and render our own view inline.

### 🟡 Rendering our own is more tractable than it sounds

B2's maps tool already carries a fixture of ~10 landmarks with coordinates and
walking times. Ten pins and a polyline is `<View>`s plus SVG — no API key, no map
SDK, all three platforms.

The dependency graph uses the same toolkit. The real work there is **layout**
(topological layering), not drawing.

⚪ Whether `react-native-svg` earns its place as a dependency, or whether plain
`<View>`s get us far enough. Needs a spike. Adding it means a row in
`dependencies.md`.

---

## The shareable URL is the expensive half

🟢 Inline rendering is ephemeral; a link you keep open is not. That means real
persistence:

- a model + stable id
- `GET /api/artifacts/{id}/`
- a route — 🟢 `app/artifact/[id].tsx` gives us a real web URL *and* a native
  screen from one file, so this part is nearly free with expo-router
- the scoping rule from guideline 3

🟢 **Not the same requirement as thread persistence.** Artifacts surviving a
reload could ride in the existing `Message.content` parts array; a URL someone
can share needs its own row.

⚪ Expiry, or whether artifacts live forever. ⚪ Whether an artifact URL is
readable by anyone who has it, or needs the session that made it even when it
contains nothing personal.

---

## How this touches B4

🟢 Less than you'd think, and additively:

- rendering tools register like any other tool — the loop doesn't change
- the loop collects artifacts the way it collects citations
- `modes_used` is unaffected
- the turn ends before the render call? prose without the artifact. Correct
  degradation.

🟢 **One real cost:** an artifact means an extra round trip on a request that's
already slow. Relevant to the streaming work in
[b4-planner.md](./b4-planner.md) — an artifact becoming ready is just another
event type.

---

## Suggested first step

🟡 Add the **empty seam** early — `artifacts: []` always empty, the union type,
the frontend dispatch with its fallback. It costs almost nothing now and means
the first real artifact is additive rather than a contract change during demo
week.

🟡 If we only build one, the **map** is probably the highest-leverage: the
signature query is Courses → Maps → Dining → Events, so a route from class to
food to event is that query made visual. The plan graph is the more impressive
artifact but depends on the Stellic mock and B1's course catalog.

Neither of these is settled. If someone has a better first artifact, say so.

---

## Explicitly not deciding yet

- The `data` schema for any artifact type
- Whether rendering is a tool call or structured output
- Animation, transitions, and how an artifact appears mid-stream
- Whether artifacts are editable (ticking off plan nodes → does that persist?)
- Multiple artifacts in one answer — allowed by the array, unexplored in the UI
- Whether an artifact can be regenerated or refined by a follow-up question
