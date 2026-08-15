/**
 * The one place that talks to the Django backend — screens call these instead
 * of fetch(), so auth headers and error handling live in a single place.
 */

import { getSessionId } from './session'
import type {
  ApiError as ApiErrorBody,
  AskEvent,
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

/**
 * A backstop against a hung request, not a latency budget. It used to be 30s,
 * which no multi-hop answer could ever land inside — one web-search turn alone
 * was measured at ~26s — so real answers were being cancelled as failures.
 */
const TIMEOUT_MS = 120_000

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
    throw new ApiError(UNREACHABLE)
  } finally {
    clearTimeout(timer)
  }
}

async function toApiError(response: Response): Promise<ApiError> {
  return apiErrorFrom(response.status, await response.text().catch(() => ''))
}

/** `{error: {code, message}}` → ApiError. Shared with the XHR path below. */
function apiErrorFrom(status: number, raw: string): ApiError {
  try {
    const parsed = JSON.parse(raw) as Partial<ApiErrorBody>
    if (parsed.error?.message) {
      return new ApiError(parsed.error.message, parsed.error.code ?? 'error', status)
    }
  } catch (e) {
    // Not JSON — a proxy error page or a Django traceback. Fall through rather
    // than showing the user raw HTML.
  }

  return new ApiError(
    `The server returned ${status}.${raw ? ` ${raw.slice(0, 200)}` : ''}`,
    'error',
    status,
  )
}

const UNREACHABLE =
  `Could not reach the API at ${API_URL}. Is the backend running? Try: docker compose up -d`

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
    id: raw.id ?? '',
    title: raw.title ?? 'Source',
    url: raw.url ?? '',
    source: raw.source ?? 'Unknown',
    snippet: raw.snippet ?? '',
    indexed_at: raw.indexed_at ?? null,
    verified_at: raw.verified_at ?? null,
    is_mock: raw.is_mock ?? false,
  }

  if (citation.is_mock) {
    console.log(`[AskScotty Mock Source Detected]: ${citation.source} - ${citation.title}`)
  }

  return citation
}

function normalizeAskResponse(raw: RawAskResponse): AskResponse {
  return { ...raw, citations: (raw.citations ?? []).map(normalizeCitation) }
}

/**
 * The ask body. The session goes in the *body* here, not just the header
 * `request` adds: /api/ask/ reads AskSerializer.session_id, and that is what
 * lets the planner use this person's connected sources. Omitting it silently
 * drops every personal tool.
 */
async function askBody(query: string, sources?: string[], threadId?: string) {
  const body: AskRequest & { sources?: string[] } = {
    query,
    session_id: await getSessionId(),
  }
  if (sources) body.sources = sources
  if (threadId) body.thread_id = threadId
  return body
}

/**
 * Ask Scotty a question, in one round trip. Backed by POST /api/ask/.
 *
 * The app uses `askEvents` instead, for the progress. This is not dead code: it
 * is the agreed fallback for anything that cannot read a stream, and it is how
 * you tell a broken planner apart from a broken stream.
 */
export async function ask(
  query: string,
  sources?: string[],
  threadId?: string,
): Promise<AskResponse> {
  const raw = await request<RawAskResponse>('/api/ask/', {
    method: 'POST',
    body: await askBody(query, sources, threadId),
  })
  return normalizeAskResponse(raw)
}

/**
 * Ask, with progress. Yields `mode_start` / `mode_end` as the planner's lanes
 * run, then `done` — which carries the same AskResponse `ask()` returns, so a
 * caller that waits only for `done` gives up nothing but the progress.
 *
 * XMLHttpRequest rather than fetch, and that is not a preference: React Native's
 * fetch is the whatwg-fetch polyfill over XHR, which exposes no `response.body`
 * and no ReadableStream, so a streamed response is unreadable on iOS and
 * Android. XHR delivers partial bodies on all three platforms, which makes this
 * one code path instead of a Platform.select.
 */
export async function* askEvents(
  query: string,
  options: { sources?: string[]; threadId?: string; signal?: AbortSignal } = {},
): AsyncGenerator<AskEvent, void> {
  const sessionId = await getSessionId()
  const body = await askBody(query, options.sources, options.threadId)

  const queue: AskEvent[] = []
  let failure: ApiError | null = null
  let finished = false
  let wake: (() => void) | null = null

  const notify = () => {
    wake?.()
    wake = null
  }
  const fail = (error: ApiError) => {
    failure = error
    finished = true
    notify()
  }

  const xhr = new XMLHttpRequest()
  xhr.open('POST', `${API_URL}/api/ask/stream/`)
  xhr.setRequestHeader('Content-Type', 'application/json')
  xhr.setRequestHeader('X-Session-Id', sessionId)
  xhr.timeout = TIMEOUT_MS

  // responseText only ever grows, so this is how much of it has been parsed.
  let consumed = 0
  let buffer = ''

  const readFrames = () => {
    const text = xhr.responseText
    buffer += text.slice(consumed)
    consumed = text.length

    let split = buffer.indexOf('\n\n')
    while (split !== -1) {
      const event = parseFrame(buffer.slice(0, split))
      buffer = buffer.slice(split + 2)
      if (event) {
        queue.push(event)
        notify()
      }
      split = buffer.indexOf('\n\n')
    }
  }

  // Assigned before send(): React Native only asks the native layer for partial
  // bodies when onprogress or onreadystatechange is set at send time.
  xhr.onprogress = () => {
    if (xhr.status === 200) readFrames()
  }
  xhr.onload = () => {
    // A rejected request (a 400 from the serializer) never streamed at all — the
    // body is the ordinary JSON error shape.
    if (xhr.status !== 200) return fail(apiErrorFrom(xhr.status, xhr.responseText))
    readFrames()
    finished = true
    notify()
  }
  xhr.onerror = () => fail(new ApiError(UNREACHABLE))
  xhr.ontimeout = () =>
    fail(new ApiError(`The server did not respond within ${TIMEOUT_MS / 1000}s.`, 'timeout'))
  xhr.onabort = () => {
    finished = true
    notify()
  }

  options.signal?.addEventListener('abort', () => xhr.abort())
  xhr.send(JSON.stringify(body))

  try {
    while (true) {
      while (queue.length) {
        const event = queue.shift() as AskEvent
        // The planner cannot send an HTTP status once the stream has started, so
        // it reports a failure as an event. Same shape, thrown the same way.
        if (event.type === 'error') throw new ApiError(event.data.message, event.data.code)
        yield event
      }
      if (failure) throw failure
      if (finished) return
      await new Promise<void>((resolve) => {
        wake = resolve
      })
    }
  } finally {
    // The consumer stopped early (an abort, or a throw upstream).
    if (!finished) xhr.abort()
  }
}

/** One SSE frame → an event, or null for anything this build doesn't know. */
function parseFrame(frame: string): AskEvent | null {
  let name = ''
  const data: string[] = []

  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim()
    else if (line.startsWith('data:')) data.push(line.slice(5).trim())
  }

  if (!name || data.length === 0) return null

  let payload: unknown
  try {
    payload = JSON.parse(data.join('\n'))
  } catch (e) {
    return null
  }

  if (name === 'done') {
    return { type: 'done', data: normalizeAskResponse(payload as RawAskResponse) }
  }
  if (name === 'mode_start' || name === 'mode_end' || name === 'text_delta' || name === 'error') {
    return { type: name, data: payload } as AskEvent
  }
  // Unknown event types are ignored on purpose: that is what keeps the backend
  // free to add one without breaking an older app.
  return null
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
