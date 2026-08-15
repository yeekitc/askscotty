# Architecture

```mermaid
flowchart TB
    App["Expo app<br/>one codebase → iOS · Android · web"]:::done
    Ask["POST /api/ask/ · /api/ask/stream/<br/>validated in, validated out"]:::done
    Gate["tools_for_session()<br/>builds this request's toolset"]:::done
    Planner["Planner loop<br/>generator: mode events → answer"]:::done

    subgraph shared ["🌐 Shared — public data only"]
        direction LR
        RAG["Campus index<br/>crawl + pgvector · B1"]:::todo
        Live["Live tools<br/>Courses · Eats · Events · Maps* · B2"]:::todo
        Web["Web verify<br/>Anthropic search / fetch · B3"]:::todo
    end

    subgraph scoped ["🔒 User-scoped — never in the shared index"]
        Personal["Personal<br/>Canvas · Ed · Stellic* · B5"]:::part
    end

    Out["answer · citations · modes_used"]:::done

    App --> Ask --> Gate --> Planner
    Planner <--> RAG
    Planner <--> Live
    Planner <--> Web
    Planner <--> Personal
    Planner --> Out --> App

    classDef done fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef part fill:#fef9c3,stroke:#ca8a04,color:#713f12
    classDef todo fill:#f1f5f9,stroke:#94a3b8,color:#475569,stroke-dasharray:4 3
    style shared fill:#f8fafc,stroke:#cbd5e1
    style scoped fill:#fff7ed,stroke:#fdba74
```

🟩 built  ·  🟨 scaffold, client stubbed  ·  ⬜ not built  ·  `*` mock, labelled in UI

---

## Five invariants

Every safety rule is enforced **by construction**, not by convention.

| | Rule | Mechanism |
|---|---|---|
| 1 | Public tools can't see personal data | `Tool.run()` only passes `session_id` to connector-gated tools |
| 2 | The planner can't call what it wasn't offered | `tools_for_session()` builds the array per request |
| 3 | The model names, never authors | citations collected by code; model emits `[S1]` |
| 4 | A mock can't look live | `is_mock` derives from the producing tool |
| 5 | A bad answer fails in the backend | response serializers validate on the way out |

**All five survived the move to Managed Agents** (shipped 2026-08-15), because
every mechanism in the right-hand column is code that runs on our side. Anthropic
drives the loop; it never executes a tool, so `run_tool` is still the only door.

Invariant 2 changed shape but not substance — the array `tools_for_session()`
returns is passed per *session* as an `agent_with_overrides` toolset rather than
per request. A session outlives the turn, so it can be holding a toolset built
before somebody connected or disconnected a source; the driver re-applies the
current one on every follow-up. That is tidiness rather than the guarantee:
`run_tool` re-checks the connector on **every** dispatch, so a stale offer
returns an error, never someone's data.

---

## Where things live

| | |
|---|---|
| `backend/apps/core/` | endpoints, contract, errors, threads |
| `backend/apps/tools/` | tool registry, source registry |
| `backend/apps/personal/` | encrypted connectors |
| `backend/apps/planner/` | the session driver, prompt, citations. `manual_loop.py` is the pre-migration loop, still reachable via `PLANNER_MANAGED_AGENTS=false` — see [b4-planner.md](./b4-planner.md) |
| `backend/apps/rag/` | not created yet |
| `frontend/app/` | the whole app, all three platforms |

---

## Deeper plans

| Doc | Covers |
|---|---|
| [PRD.md](./PRD.md) | product, scope, sources, non-goals |
| [b4-planner.md](./b4-planner.md) | planner loop, citations, streaming, inline-citation UI |
| [b3-web-verify.md](./b3-web-verify.md) | web verify — implementation prompt, ready to hand over |
| [artifact-plan.md](./artifact-plan.md) | maps / plan graphs / schedules — draft |
| [../tasklist.md](../tasklist.md) | the API contract (§2) and every task |
| [runbook.md](./runbook.md) | running it |
| [dependencies.md](./dependencies.md) | every dependency, and why |
