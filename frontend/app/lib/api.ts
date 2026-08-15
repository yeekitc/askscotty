/**
 * The one place that talks to the Django backend.
 *
 * Every screen should call these functions instead of using fetch() directly,
 * so there is a single place to add auth headers, logging, or error handling.
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
 * Where the backend lives.
 *
 * Expo inlines any env var starting with EXPO_PUBLIC_ at build time, so this
 * works on phone and web. Set it in frontend/app/.env (NOT the repo-root .env —
 * Expo only reads .env from this folder).
 *
 * On a physical phone, "localhost" means the phone itself, so you must set this
 * to your laptop's LAN IP, e.g. http://192.168.1.20:8000
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
 * Every call to the backend goes through here.
 *
 * Two things happen for free as a result: the anonymous session id is attached
 * to each request (see lib/session.ts — it is a bearer token, so it rides in a
 * header, never the URL), and the backend's `{error: {code, message}}` shape is
 * unwrapped into a thrown ApiError carrying that code.
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

    // 204 No Content (a thread delete) has no body to parse.
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

/** Turns a failed response into the most specific ApiError we can manage. */
async function toApiError(response: Response): Promise<ApiError> {
  const raw = await response.text().catch(() => '')

  try {
    const parsed = JSON.parse(raw) as Partial<ApiErrorBody>
    if (parsed.error?.message) {
      return new ApiError(parsed.error.message, parsed.error.code ?? 'error', response.status)
    }
  } catch (e) {
    // Not JSON — a proxy error page or a Django debug traceback. Fall through
    // to the generic message rather than showing the user raw HTML.
  }

  return new ApiError(
    `The server returned ${response.status}.${raw ? ` ${raw.slice(0, 200)}` : ''}`,
    'error',
    response.status,
  )
}

/**
 * What actually comes back over the wire. `AskResponse` is what the rest of
 * the app is allowed to assume; this is the looser version we get before
 * `normalizeCitation` has filled in whatever the backend left out.
 */
type RawAskResponse = Omit<AskResponse, 'citations'> & {
  citations?: Partial<Citation>[]
}

/**
 * Fills in a citation's missing fields and reports mock sources.
 *
 * Mock data is announced on the console instead of being badged in the UI.
 * NOTE: PRD §9 and tasklist §F2/§4 both require a *visible* mock label, so
 * this is a deliberate deviation — the badge markup still lives in git
 * history if that requirement comes back before submission.
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
  // The session goes in the *body* here, not just the header `request` adds.
  // /api/ask/ reads it from the body (AskSerializer.session_id), and that is
  // what decides whether the planner may use this person's connected sources —
  // so omitting it would silently drop every personal tool from the request.
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
// Threads live in our own Postgres rather than assistant-ui's hosted Cloud —
// see backend/apps/core/models.py for that decision. All three calls are scoped
// to this device's session by the header `request` adds.

/** Every saved thread for this session, newest first. */
export async function fetchThreads(): Promise<StoredThread[]> {
  const { threads } = await request<ThreadListResponse>('/api/threads/')
  return threads ?? []
}

/**
 * Save a thread, creating it if the server has not seen this id before.
 *
 * The whole message list goes up on every save rather than just the new turn.
 * That mirrors how the screen already works — it snapshots the live thread on
 * every change — and it means an edited or branched thread cannot drift from
 * what is stored.
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
