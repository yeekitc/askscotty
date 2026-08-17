/**
 * This file and backend/apps/core/serializers.py describe the same JSON
 * (contract in tasklist.md §2). Change one, change the other — a mismatch is
 * invisible until it breaks in the app.
 */

/**
 * Every field is required, and "missing" is spelled `null` (or `''` for a url)
 * rather than `undefined`: the backend may omit fields, but `ask()` in api.ts
 * fills the gaps first, so components never write `citation.source ?? '…'`.
 */
export type Citation = {
  /**
   * The planner's handle for this source ("S1") — the only thing the model ever
   * writes about it, and what an inline `[S1]` marker resolves to. Explicit
   * rather than positional so filtering the list cannot rebind the markers.
   */
  id: string
  title: string
  /** Empty string when the source has no public URL. */
  url: string
  /** e.g. "Courses", "CMU Eats", "TartanConnect". */
  source: string
  /** The supporting excerpt for a citation preview. '' when there isn't one. */
  snippet: string
  /** Both timestamps must be surfaced in the UI (PRD §9). */
  indexed_at: string | null
  verified_at: string | null
  is_mock: boolean
}

/**
 * Which tool families ran, for the mode chips. Fixed vocabulary: the backend
 * validates `modes_used` against the same list (MODES in
 * backend/apps/tools/registry.py), so an uncovered string means they drifted.
 */
export type Mode =
  | 'rag'
  | 'courses'
  | 'dining'
  | 'events'
  | 'maps'
  | 'rooms'
  | 'handshake'
  | 'fce'
  | 'web_verify'
  | 'personal'

/**
 * The lanes a reader can switch off, in the order the picker shows them.
 *
 * `personal` is deliberately absent: it appears only where someone has connected
 * the source, so it is gated by the connector rather than by preference.
 */
export const LANES: { mode: Mode; label: string; mock?: boolean }[] = [
  { mode: 'rag', label: 'Campus index' },
  { mode: 'courses', label: 'Courses' },
  { mode: 'dining', label: 'Dining' },
  { mode: 'events', label: 'Events' },
  { mode: 'maps', label: 'Maps', mock: true },
  { mode: 'rooms', label: 'Rooms', mock: true },
  { mode: 'handshake', label: 'Handshake', mock: true },
  { mode: 'fce', label: 'FCE', mock: true },
  { mode: 'web_verify', label: 'Web verification' },
]

/** One earlier turn, replayed so follow-up questions have context. */
export type HistoryMessage = {
  role: 'user' | 'assistant'
  content: string
}

/** POST /api/ask/ request body. */
export type AskRequest = {
  query: string
  /**
   * Optional: without it the backend answers from public sources only. With
   * it, the user's connected sources are available to the planner.
   */
  session_id?: string
  /**
   * Optional: which conversation this belongs to. The backend keeps one planner
   * session per thread, so sending it is what lets a follow-up reuse the last
   * turn's lookups instead of starting the conversation over.
   */
  thread_id?: string
  /** Prior turns, oldest first. */
  history?: HistoryMessage[]
  /**
   * Lanes the reader unchecked in the source picker. A deny list, not an allow
   * list: a lane this build has never heard of stays on, which is what keeps
   * "everything is checked unless you uncheck it" true after a backend adds one.
   */
  disabled_modes?: Mode[]
}

export type AskResponse = {
  answer: string
  citations: Citation[]
  modes_used: Mode[]
  /** A caveat to show above the answer, or null when there is nothing to flag. */
  note: string | null
}

/**
 * What POST /api/ask/stream/ pushes while an answer is being built. Additive:
 * `done` carries the same AskResponse the non-streaming endpoint returns, so a
 * caller that ignores everything else loses nothing but the progress.
 */
export type AskEvent =
  | { type: 'mode_start'; data: { mode: Mode; tool: string } }
  | { type: 'mode_end'; data: { mode: Mode; tool: string; ok: boolean } }
  /**
   * Answer text as the model writes it. Append, but treat it as provisional:
   * text written before a lane starts was the model talking itself into a
   * lookup, and `done` is the only authoritative answer.
   */
  | { type: 'text_delta'; data: { text: string } }
  | { type: 'done'; data: AskResponse }
  | { type: 'error'; data: { code: string; message: string } }

/** One row of GET /api/sources/ — the credits and freshness list. */
export type Source = {
  name: string
  /** "public" is shared and indexable; "personal" is user-scoped (PRD §10). */
  tier: 'public' | 'personal'
  /** "Mock" is fixture data. */
  access: 'Crawl' | 'Live' | 'Token' | 'Mock'
  indexed_at: string | null
  /** False while the lane is a placeholder — don't imply coverage we lack. */
  implemented?: boolean
  note?: string
}

/** GET /api/sources/ response body. */
export type SourcesResponse = {
  sources: Source[]
}

/**
 * `content` is assistant-ui's message *parts* array, not a string — answer text
 * plus one "source" part per citation, which is what lets citations survive a
 * reload. `unknown[]` because this file describes the wire and the parts are
 * assistant-ui's types; lib/chatThreads.ts is where the two meet.
 */
export type StoredMessage = {
  role: 'user' | 'assistant'
  content: unknown[]
}

/** `id` is generated by the app, not the server. */
export type StoredThread = {
  id: string
  messages: StoredMessage[]
  /**
   * Set only by an explicit rename. Empty means the app derives the title from
   * the first user message, so an untouched thread still names itself.
   */
  title: string
  /** Server-side last-write time, ISO 8601. Orders the sidebar. */
  updated_at: string
}

/** GET /api/threads/ response body. */
export type ThreadListResponse = {
  threads: StoredThread[]
}

// --- Personal connections -----------------------------------------------------

/** The personal sources a session can connect (Provider in apps/personal/models.py). */
export type Provider = 'canvas' | 'ed' | 'stellic' | 'piazza' | 'gradescope'

/**
 * One connected source. There is deliberately no `credential` field: the
 * backend never returns one (PRD §9), so there is nothing here to hold it.
 */
export type Connection = {
  provider: Provider
  connected_at: string
  /** null until the source has actually been pulled from. */
  last_sync_at: string | null
}

/** GET /api/connections/ response body. */
export type ConnectionListResponse = {
  connections: Connection[]
}

/** Every API failure uses this shape (tasklist §2). Show `message` to the user. */
export type ApiError = {
  error: {
    code: string
    message: string
  }
}
