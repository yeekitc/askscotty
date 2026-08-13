/**
 * The one place that talks to the Django backend.
 *
 * Every screen should call these functions instead of using fetch() directly,
 * so there is a single place to add auth headers, logging, or error handling.
 */

import type { AskResponse } from './types'

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

class ApiError extends Error {}

async function post<T>(path: string, body: unknown): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS)

  try {
    const response = await fetch(`${API_URL}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    })

    if (!response.ok) {
      // Django/DRF usually sends a JSON body explaining what went wrong.
      const detail = await response.text().catch(() => '')
      throw new ApiError(
        `The server returned ${response.status}.${detail ? ` ${detail.slice(0, 200)}` : ''}`,
      )
    }

    return (await response.json()) as T
  } catch (err) {
    if (err instanceof ApiError) throw err
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiError(`The server did not respond within ${TIMEOUT_MS / 1000}s.`)
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

/** Ask Scotty a question. Backed by POST /api/ask/ */
export function ask(query: string, sources?: string[]): Promise<AskResponse> {
  const body: any = { query }
  if (sources) body.sources = sources
  return post<AskResponse>('/api/ask/', body)
}
