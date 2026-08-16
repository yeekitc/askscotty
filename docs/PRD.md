# PRD: AskScotty

**Hackathon:** [Stellic Pathfinders Challenge](https://www.stellic.com/pathfinders) · Jul 20 – Aug 21, 2026  
**Categories:** Overcoming Obstacles + Degree Planning (Campus Connection / College to Career secondary)  
**Name:** **AskScotty** — named for Scotty, CMU’s Scottish Terrier mascot. Not affiliated with ScottyLabs (or any other “Scotty*” campus product). We are unaffiliated consumers of ScottyLabs’ public/open APIs (and TartanConnect’s public event feed). Credit in app + submission; do not imply partnership.

**This doc owns product scope** — what we're building and why. Implementation
detail has moved to its own pages, one source of truth per topic:

| Doc | Owns |
|---|---|
| [architecture.md](./architecture.md) | how the pieces fit · the safety invariants · what's built |
| [b4-planner.md](./b4-planner.md) | the planner loop · citations · streaming · inline-citation UI |
| [artifact-plan.md](./artifact-plan.md) | maps, plan graphs, schedules — *draft, mostly open* |
| [../tasklist.md](../tasklist.md) | the frozen API contract (§2) and every task |

---

## 1. Problem

CMU knowledge is scattered across Stellic, SIO, Canvas, Ed, Discord, TartanConnect, Handshake, and public `cmu.edu`. Students have access; they can’t compose across it.

**AskScotty** = pre-indexed public campus corpus + live structured APIs + web verify for freshness + optional personal connectors.

---

## 2. Product

**One-liner:** Ask Scotty anything about CMU (and *your* CMU) — get a cited, multi-hop answer.

**Signature query**

> “I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then an interesting startup or AI event before 8.”

≈ `Courses` → `Maps` → `Dining` → `Events`

**Loop:** sign in → optional connect personal sources → ask → planner (RAG → live tools → web verify) → cited answer.

**Pitch:** Pre-index public `cmu.edu` + course sites for speed; **re-index on a schedule**; **web search/fetch verifies** when freshness matters. Live APIs for data that changes hourly.

---

## 3. Architecture

```
Query → Planner
          ├─ RAG (campus index)      ← public web, scheduled re-index
          ├─ Live tools              ← structured APIs / mocks
          ├─ Web verify              ← search / fetch if stale or missing
          └─ Personal                ← user-scoped only; never in shared index
                → cited answer (indexed_at / verified_at)
```

Do **not** dump volatile structured APIs into the vector DB. Shared index = public pages only.

→ **[architecture.md](./architecture.md)** for the rendered version, what's actually built, and the five invariants that enforce the rules below in code rather than by convention.

| Include in crawl | Exclude from crawl |
|------------------|--------------------|
| `cmu.edu` public pages, HUB, colleges, CPDC, Student Affairs | SIO, Stellic UI, Canvas, Autolab |
| Seeded course sites (Appendix B) + discovered course homes | Login walls, `robots.txt` disallow |
| cmu.guide, HKN, public LibGuides | Private Discord/Ed; student PII |

Respect `robots.txt`, rate-limit, identify crawler UA.

**Hackathon accessibility legend:** `Live` = public API/feed now · `Crawl` = we index it · `Token` = user pastes key · `Mock` = stub for demo · `Link` = deep-link only · `Skip`

---

## 4. RAG (campus index)

Scheduled crawl → chunk → hybrid BM25 + vectors. Tool: `campus_search`. Cite `url` + `indexed_at`.

| Tier | Source | Why | Hackathon accessibility |
|------|--------|-----|-------------------------|
| **Must** | Public `cmu.edu` (HUB, colleges, Student Affairs, CPDC, …) | Policies, advising, “how do I…” | **Crawl** — pre-index for demo; pitch nightly/weekly re-index |
| **Must** | Seeded SCS course sites (Appendix B) | Syllabi, textbooks, course policies | **Crawl** seeds; enqueue new URLs from web verify |
| **Must** | [cmu.guide](https://cmu.guide/) | Student lore (housing, getting around) | **Crawl** (site + GitHub Markdown) |
| **Must** | Computing Services + KB (`computing.cmu.edu`) | “Connect to the VPN / campus wifi / printing” — pure how-do-I, and nothing else we index covers it | **Crawl** public KB articles |
| **Must** | Course catalog (`coursecatalog.cmu.edu`) | Degree **requirements**. The Courses API gives schedules and prereqs but not what a major needs; Stellic is a mock, so this is our only public route to “on track for a CS minor?” | **Crawl** — static pages, safe to index |
| **Should** | Non-SCS college sites (`cit`, `dietrich`, `tepper`, `cfa`, `mcs`, `heinz`) | Appendix B is SCS-only; these carry the advising and policy pages for everyone else | **Crawl** public sections |
| **Should** | `cmu.edu/health-services` | Common “how do I…” (appointments, insurance, counselling) with no coverage today | **Crawl** |
| **Should** | `cmu.edu/housing` | Official housing policy. cmu.guide has the lore, not the rules | **Crawl** |
| **Should** | HKN ECE/CS Guide | Peer course tips | **Crawl** public GitHub Pages |
| **Should** | LibGuides | Research / subject help | **Crawl** public guides (or API if key appears) |
| **Could** | `cmu.edu/about`, `cmu.edu/academics` | Small and cheap; grounds “what/where is X” and gives the colleges list a real page | **Crawl** |
| **Could** | Lost & Found posts, ResearchStarter listings | Niche campus Qs | **Mock** (no stable public consumer API) |
| **Skip** | Auth-walled pages (SIO, Canvas, Stellic) | Not public | Never in shared index |

---

## 5. Live tools

Time-sensitive structured data. Tool-calling with filters — not “just more chunks.”

| Tier | Source | Why | Hackathon accessibility |
|------|--------|-----|-------------------------|
| **Must** | CMU Courses API\* | Catalog, schedules, prereqs, instructors | **Live** — `course-tools` / `course.apis.scottylabs.org` (no auth) |
| **Must** | CMU Eats / Dining\* | Open now, menus, locations | **Live** — `api.cmueats.com/v2/locations` (prefer; old dining.apis deprecated) |
| **Must** | TartanConnect events | Clubs / campus events | **Live** — `mobile_events_list` JSON (no auth) |
| **Must** | Maps (buildings / nearby) | Multi-hop “near Gates/Wean” | **Mock** — ~10 landmark coords/adjacency ([cmumaps.com](https://cmumaps.com) has no public REST) |
| **Should** | 25Live room occupancy | “Empty room for 90 min” | **Mock** — CollegeNET; empty without Andrew SSO; do not automate login scrape |
| **Should** | Handshake events | Career fairs / employer sessions | **Mock** or **Link** — student GraphQL needs SSO |
| **Should** | FCE ratings | Workload / quality filters | **Mock** subset — Andrew/Clerk-gated on Courses |
| **Could** | Live Maps / 25Live APIs | Replace mocks | Future data partnership (not “ScottyLabs affiliate”) |
| **Skip** | ScottyLabs internal Events S3/Railway | Not public | Use TartanConnect live + mocks instead |

\* Unaffiliated consumer of public/open APIs.

**25Live (one-liner):** CMU’s official room reservation system. Useful for free-room queries; auth-walled → mock for hackathon.

---

## 6. Web verify

Complements the index — does not replace it.

| Tier | Capability | Why | Hackathon accessibility |
|------|------------|-----|-------------------------|
| **Must** | `fetch_url` | Re-fetch a cited page when stale or user asks “is this current?” | **Live** — public hosts |
| **Must** | `web_search` | Index miss; discover new course homes → next crawl | **Live** — Claude server-side `web_search` (no separate provider) |
| **Must** | `resolve_course_site` | Map `15-213` → seeded homepage | **Live** — static map (Appendix B) |
| **Should** | Site-filtered search (`site:cs.cmu.edu`) | Find unmapped course pages | **Live** — `site:` in the query |
| **Skip** | Fetching Canvas/SIO behind login | Auth walls | Use Personal connectors instead |

**Planner default:** index hit → cite → optional verify fetch. Unmapped/stale → search/fetch → enqueue for re-index.

> **Amended 2026-08-15 — no domain allowlist or denylist.** The rows above once
> read “allowlist public hosts” and “`allowed_domains` on the same tool.” B4 runs
> on Managed Agents, whose built-in web toolset is not known to accept those
> filters. The **Skip** row still holds without them: `web_fetch` carries no
> credentials, so Canvas / SIO / Stellic return login pages and there is nothing
> behind the wall for it to reach. Source *preference* moves to prompt guidance
> seeded from Appendix B. What this gives up is the anti-exfiltration property of
> an allowlist — accepted for the hackathon, and the first thing to revisit after
> it. Reasoning: [b4-planner.md](./b4-planner.md) §4.

---

## 7. Personal (user-scoped)

Never mixed into the shared campus index. Disconnect deletes synced data.

| Tier | Source | Why | Hackathon accessibility |
|------|--------|-----|-------------------------|
| **Must** | Canvas | Due dates, announcements, grades, files | **Token** — student PAT → `canvas.cmu.edu/api/v1` |
| **Should** | Ed Discussion | Staff-endorsed course Q&A | **Token** — Ed settings API token |
| **Should** | Stellic | Degree audit / multi-semester plan | **Mock** / upload JSON — institutional PAT only; no student OAuth |
| **Could** | Autolab | SCS programming deadlines/scores | **Token** if OAuth registered; else lean on Canvas |
| **Could** | Discord / Slack | Peer lore in servers you’re in | Bot-in-guild / Slack `search:read`; only if you control a demo server |
| **Link / Skip** | Gradescope, Piazza, SIO, housing, billing | Overlap or no safe API | Prefer Canvas / Ed / **Link** out; no password scrape |

---

## 8. Example queries

| Query | Modes |
|-------|-------|
| “How do I withdraw / drop deadline?” | RAG → optional web verify |
| “9-unit ML elective, no Friday” / “After 15-213?” | Live Courses\* |
| “15-213 textbook / late policy?” | RAG (seeded site) → verify if stale |
| “Open after 8:20 near Wean” | Live Dining\* + mock Maps |
| “Startup/AI event before 8” | Live TartanConnect (+ mock Handshake) |
| “Empty room near Gates 90 min” | Mock Maps × mock 25Live |
| “What’s due this week?” | Personal Canvas |
| “Staff late-day policy on HW3?” | Personal Ed (else RAG course site) |
| “On track for CS minor?” | Personal Stellic mock + Live Courses\* |
| Signature multi-hop (§2) | Courses\* → mock Maps → Dining\* → TartanConnect |

---

## 9. Requirements & build

**P0:** Campus index + `campus_search` · Live Courses\* + Eats\* + TartanConnect · `web_search`/`fetch_url` · mock Maps (± 25Live) · Canvas token *or* strong public-only demo · signature multi-hop · credits footer  

**P1:** Re-index job (even manual) for pitch · Ed · Stellic mock · Handshake mocks  

**P2:** Discord/Slack · Andrew SSO · live Maps/25Live via future partnership  

→ Build detail: **[b4-planner.md](./b4-planner.md)** (planner loop, citations, streaming) · **[artifact-plan.md](./artifact-plan.md)** (interactive answers — draft) · **[../tasklist.md](../tasklist.md)** (every task, with owners)


| Days | Slice |
|------|-------|
| 1–2 | Crawl + index seeds + `campus_search` |
| 1–2 | Planner + live Courses\* / Eats\* / TartanConnect |
| 1 | Web verify + stale path |
| 1 | Mock Maps / 25Live + signature multi-hop |
| 1–2 | Canvas/Ed + Stellic mock · polish · video |

**Credits copy:** “Uses publicly available CMU web pages and public campus APIs, including open APIs published by ScottyLabs (e.g. Courses). We are not affiliated with ScottyLabs.”

**Non-goals:** Replace Stellic/SIO/Canvas · imply ScottyLabs partnership · SSO-scrape 25Live/Handshake · put auth data in shared index · write grades / autoregister.

**Privacy:** Shared index = public web only · personal = user-scoped · show `indexed_at`/`verified_at` · label mocks · tokens as passwords.

---

## Appendix A — API & product URLs

| Name | URL |
|------|-----|
| Pathfinders | https://www.stellic.com/pathfinders |
| Courses API\* | https://course-tools.apis.scottylabs.org (`/courses/search`, `/course/{id}`, `/schedules`) also `course.apis.scottylabs.org` |
| CMU Eats API\* | https://api.cmueats.com/v2/locations |
| TartanConnect events | https://tartanconnect.cmu.edu/mobile_ws/v17/mobile_events_list?range=0 |
| cmu.guide | https://cmu.guide/ |
| Canvas | https://canvas.cmu.edu |
| Stellic (CMU) | https://academicaudit.andrew.cmu.edu |
| Autolab | https://autolab.andrew.cmu.edu |
| Handshake | https://cmu.joinhandshake.com |
| CMU Maps (UI) | https://cmumaps.com |
| 25Live Pro | https://25live.collegenet.com/pro/cmu |
| 25Live HUB docs | https://www.cmu.edu/hub/registrar/25live/index.html |
| ScottyLabs projects (upstream; unaffiliated) | https://www.scottylabs.org/projects/ |

\* Public/open API; we are not affiliated with the publisher.

---

## Appendix B — Course site crawl seeds

| Course | Homepage |
|--------|----------|
| 15-210 | https://www.cs.cmu.edu/~15210/ |
| 15-213 | https://www.cs.cmu.edu/~213/ |
| 15-150 | https://www.cs.cmu.edu/~15150/ |
| 15-122 | https://www.cs.cmu.edu/~15122/ |
| 15-251 | https://www.cs.cmu.edu/~15251/ |
| 15-451 | https://www.cs.cmu.edu/~15451/ |
| 10-601 | https://www.cs.cmu.edu/~mgormley/courses/10601/ |
| Deep Learning | https://deeplearning.cs.cmu.edu/ |
| 17-313 | https://cmu-313.github.io/ |
| 15-445/645 | https://15445.courses.cs.cmu.edu/ |

---

## Appendix C — General Crawl Seeds (B1 implementation)

Seeds in addition to the Appendix B course sites. All are **public / Crawl** tier.
Inserted into `CrawlSeed` by `manage.py load_seeds`; authoritative list in `backend/apps/rag/seed_urls.py`.

| Label | URL | Notes |
|-------|-----|-------|
| `cmu-main` | https://www.cmu.edu/ | Root — links to everything else |
| `cmu-about` | https://www.cmu.edu/about/ | Institutional overview |
| `cmu-hub` | https://www.cmu.edu/hub/ | HUB registrar: deadlines, policies |
| `cmu-academics` | https://www.cmu.edu/academics/ | Academic programs |
| `cmu-student-affairs` | https://www.cmu.edu/student-affairs/ | Student life, resources |
| `cmu-housing` | https://www.cmu.edu/housing/ | Official housing policy (cmu.guide has the lore, not the rules) |
| `cmu-dining` | https://www.cmu.edu/dining/ | Dining plans, locations |
| `cmu-health` | https://www.cmu.edu/health-services/ | Health, counselling, insurance |
| `cmu-career` | https://www.cmu.edu/career/ | CPDC career services |
| `cmu-news` | https://www.cmu.edu/news/ | Static institutional news |
| `cmu-admissions` | https://admission.enrollment.cmu.edu/ | Public admissions info |
| `scs` | https://scs.cmu.edu/ | School of Computer Science |
| `cit` | https://www.cit.cmu.edu/ | College of Engineering |
| `dietrich` | https://www.cmu.edu/dietrich/ | Dietrich College |
| `tepper` | https://www.tepper.cmu.edu/ | Tepper School of Business |
| `cfa` | https://www.cfa.cmu.edu/ | College of Fine Arts |
| `mcs` | https://www.cmu.edu/mcs/ | Mellon College of Science |
| `heinz` | https://www.heinz.cmu.edu/ | Heinz College |
| `course-catalog` | https://coursecatalog.cmu.edu/ | Degree requirements; public substitute for Stellic audit |
| `computing` | https://computing.cmu.edu/ | Computing Services KB — VPN, printing, wifi how-tos |
| `library` | https://library.cmu.edu/ | LibGuides and research help |
| `cmu-guide` | https://cmu.guide/ | Student-written campus lore |
| `student-orgs` | https://studentorgs.cmu.edu/ | Org directory (**Should** — §4). Event listing sub-pages are volatile; the depth=2 cap naturally excludes them. |

**Sources not crawled:**

| URL | Reason |
|-----|--------|
| `enr-apps.as.cmu.edu/open/SOC/SOCServlet` | Volatile structured data (same registrar feed ScottyLabs wraps in the Courses API). Covered by the Live Courses tool (B2), not indexed. |
| `events.cmu.edu` listing pages | Hourly-volatile event data. Static about/info pages are crawlable if reached within depth; event listing pages are excluded by the volatile-data rule. TartanConnect covers CMU events as a Live tool. |
| `kilthub.cmu.edu` | Research data repository. Low priority for the demo; add as "Could / Crawl" in a post-hackathon pass. |
