/**
 * The one place that talks to the Django backend — screens call these instead
 * of fetch(), so auth headers and error handling live in a single place.
 */

import { getSessionId } from './session'
import type {
  ApiError as ApiErrorBody,
  AskRequest,
  AskResponse,
  Citation,
  StoredThread,
  ThreadListResponse,
} from './types'

/**
 * Set in frontend/app/.env, not the repo-root .env — Expo only reads this
 * folder's. On a physical phone "localhost" is the phone itself, so it has to
 * be the laptop's LAN IP, e.g. http://192.168.1.20:8000
 */
export const API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'

/** Fails fast instead of hanging forever when the backend is down. */
const TIMEOUT_MS = 30_000

/** Carries the backend's error `code` so callers can switch on it (tasklist §2). */
export class ApiError extends Error {
  readonly code: string
  readonly status: number

  constructor(message: string, code = 'network_error', status = 0) {
    super(message)
    this.code = code
    this.status = status
  }
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
}

/**
 * Every call goes through here, so two things are guaranteed: the session id
 * rides in a header rather than the URL (it is a bearer token — see
 * lib/session.ts), and `{error: {code, message}}` becomes a thrown ApiError.
 */
async function request<T>(path: string, { method = 'GET', body }: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  try {
    const sessionId = await getSessionId()

    const response = await fetch(`${API_URL}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        'X-Session-Id': sessionId,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) {
      throw await toApiError(response)
    }

    // 204 No Content (a thread delete) has no body.
    if (response.status === 204) return undefined as T

    return (await response.json()) as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(`The server did not respond within ${TIMEOUT_MS / 1000}s.`, 'timeout')
    }
    // Almost always: backend not running, or wrong API_URL on a physical phone.
    throw new ApiError(
      `Could not reach the API at ${API_URL}. Is the backend running? ` +
        `Try: docker compose up -d`,
    )
  } finally {
    clearTimeout(timer)
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  const raw = await response.text().catch(() => '')

  try {
    const parsed = JSON.parse(raw) as Partial<ApiErrorBody>
    if (parsed.error?.message) {
      return new ApiError(parsed.error.message, parsed.error.code ?? 'error', response.status)
    }
  } catch (e) {
    // Not JSON — a proxy error page or a Django traceback. Fall through rather
    // than showing the user raw HTML.
  }

  return new ApiError(
    `The server returned ${response.status}.${raw ? ` ${raw.slice(0, 200)}` : ''}`,
    'error',
    response.status,
  )
}

/** The looser wire shape, before `normalizeCitation` fills in the gaps. */
type RawAskResponse = Omit<AskResponse, 'citations'> & {
  citations?: Partial<Citation>[]
}

/**
 * Fills in whatever the backend omitted, so components never have to.
 * Mock sources are logged rather than badged — see the note in CitationCard.
 */
function normalizeCitation(raw: Partial<Citation>): Citation {
  const citation: Citation = {
    title: raw.title ?? 'Source',
    url: raw.url ?? '',
    source: raw.source ?? 'Unknown',
    indexed_at: raw.indexed_at ?? null,
    verified_at: raw.verified_at ?? null,
    is_mock: raw.is_mock ?? false,
  }

  if (citation.is_mock) {
    console.log(`[AskScotty Mock Source Detected]: ${citation.source} - ${citation.title}`)
  }

  return citation
}

/** Ask Scotty a question. Backed by POST /api/ask/ */
export async function ask(query: string, sources?: string[]): Promise<AskResponse> {
  // /api/ask/ reads the session from the *body* (AskSerializer.session_id), not
  // the header `request` adds, and that is what lets the planner use this
  // person's connected sources. Omitting it silently drops every personal tool.
  const body: AskRequest & { sources?: string[] } = {
    query,
    session_id: await getSessionId(),
  }
  if (sources) body.sources = sources

  const raw = await request<RawAskResponse>('/api/ask/', { method: 'POST', body })
  return { ...raw, citations: (raw.citations ?? []).map(normalizeCitation) }
}

// --- Chat history -------------------------------------------------------------
//
// Threads live in our own Postgres rather than assistant-ui's hosted Cloud (see
// backend/apps/core/models.py). All three calls are scoped to this device's
// session by the header `request` adds.

/** Every saved thread for this session, newest first. */
export async function fetchThreads(): Promise<StoredThread[]> {
  const { threads } = await request<ThreadListResponse>('/api/threads/')
  return threads ?? []
}

/**
 * Save a thread, creating it if the server has not seen this id before. The
 * whole message list goes up every time, not just the new turn, so an edited
 * or branched thread cannot drift from what is stored.
 */
export function saveThread(id: string, messages: StoredThread['messages']): Promise<StoredThread> {
  return request<StoredThread>(`/api/threads/${encodeURIComponent(id)}/`, {
    method: 'PUT',
    body: { messages },
  })
}

/** Delete a thread and its messages. Deleting an unknown id throws a not_found. */
export function deleteThread(id: string): Promise<void> {
  return request<void>(`/api/threads/${encodeURIComponent(id)}/`, { method: 'DELETE' })
}
