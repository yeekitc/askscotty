/**
 * Shape of the data the backend sends back.
 *
 * This file is the single source of truth for the API shape. If you change
 * `AskResponse` here, TypeScript will tell you everywhere in the app that
 * needs updating — on phone AND web at the same time.
 *
 * The matching backend definition lives in backend/apps/core/serializers.py,
 * and the contract itself is agreed in tasklist.md §2. Change one, change all
 * three — a mismatch is invisible until it breaks in the app.
 */

/**
 * Every field here is required, and "missing" is spelled `null` (or `''` for a
 * url) rather than `undefined`. The backend is allowed to omit fields, so
 * `ask()` in api.ts fills the gaps before anything else sees a Citation —
 * that way components never have to write `citation.source ?? 'Unknown'`.
 */
export type Citation = {
  title: string
  /** Link to the source page. Empty string when the source has no public URL. */
  url: string
  /** Where this came from, e.g. "Courses", "CMU Eats", "TartanConnect". */
  source: string
  /** When our index last crawled it (PRD requires showing this). */
  indexed_at: string | null
  /** When we last confirmed it live (PRD requires showing this). */
  verified_at: string | null
  /**
   * True when this came from mock data. Reported to the console by api.ts
   * rather than badged in the UI — see the note there.
   */
  is_mock: boolean
}

/**
 * Which tool families actually ran, for the mode chips.
 *
 * Fixed vocabulary — the backend validates `modes_used` against the same list
 * (MODES in backend/apps/tools/registry.py), so a string the union doesn't
 * cover means the two have drifted apart.
 */
export type Mode =
  | 'rag'
  | 'courses'
  | 'dining'
  | 'events'
  | 'maps'
  | 'web_verify'
  | 'personal'

/** One earlier turn, replayed so follow-up questions have context. */
export type HistoryMessage = {
  role: 'user' | 'assistant'
  content: string
}

/** POST /api/ask/ request body. */
export type AskRequest = {
  query: string
  /**
   * The anonymous session this question belongs to. Optional: without it the
   * backend answers from public sources only. With it, anything the user has
   * connected (Canvas, …) becomes available to the planner for this request.
   */
  session_id?: string
  /** Prior turns, oldest first. */
  history?: HistoryMessage[]
}

export type AskResponse = {
  answer: string
  citations: Citation[]
  modes_used: Mode[]
  /** A caveat to show above the answer, or null when there is nothing to flag. */
  note: string | null
}

/** One row of GET /api/sources/ — the credits and freshness list. */
export type Source = {
  name: string
  /** "public" sources are shared and indexable; "personal" ones are user-scoped. */
  tier: 'public' | 'personal'
  /** How we reach it. "Mock" is fixture data and must be labelled in the UI. */
  access: 'Crawl' | 'Live' | 'Token' | 'Mock'
  /** When this source was last refreshed, or null if never / not applicable. */
  indexed_at: string | null
  /** False while the lane is still a placeholder — don't imply coverage we lack. */
  implemented?: boolean
  /** One line on what this source gives us, for the credits page. */
  note?: string
}

/** GET /api/sources/ response body. */
export type SourcesResponse = {
  sources: Source[]
}

/**
 * One stored turn of a saved conversation.
 *
 * `content` is assistant-ui's message *parts* array, not a string: an assistant
 * turn is its answer text plus one "source" part per citation. Storing it whole
 * is what lets citations survive a reload — see backend apps/core/models.py.
 * Typed as `unknown[]` because this file describes the wire, and the parts are
 * assistant-ui's types; lib/chatThreads.ts is where the two meet.
 */
export type StoredMessage = {
  role: 'user' | 'assistant'
  content: unknown[]
}

/** One saved thread. `id` is the id the app generated for it. */
export type StoredThread = {
  id: string
  messages: StoredMessage[]
  /** Server-side last-write time, ISO 8601. Orders the sidebar. */
  updated_at: string
}

/** GET /api/threads/ response body. */
export type ThreadListResponse = {
  threads: StoredThread[]
}

/**
 * Every API failure uses this shape (tasklist §2), alongside a real HTTP
 * status. Switch on `code`; show `message` to the user.
 */
export type ApiError = {
  error: {
    code: string
    message: string
  }
}
