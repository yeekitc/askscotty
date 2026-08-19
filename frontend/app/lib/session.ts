/**
 * The anonymous session id — no login, per tasklist §1 — that scopes a person's
 * threads and connected sources to them.
 *
 * TREAT IT LIKE A PASSWORD. It is a bearer token, not a username: whoever has
 * it can read that session's data. So it rides in a header rather than a URL
 * (query strings land in server logs), and is never logged or rendered.
 *
 * AsyncStorage, not localStorage: `window` does not exist on a phone, so native
 * builds used to persist nothing at all.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'

const SESSION_KEY = 'askscotty.session_id'

/**
 * Not `Math.random()`: this value guards one student's data from another's. The
 * throw is so a platform without `crypto.getRandomValues` (it exists on web and
 * in Hermes) fails loudly rather than quietly issuing guessable ids.
 */
function generateSessionId(): string {
  const bytes = new Uint8Array(24)

  if (typeof crypto === 'undefined' || !crypto.getRandomValues) {
    throw new Error('No secure random source available for the session id.')
  }
  crypto.getRandomValues(bytes)

  // Plain hex — base64 would need btoa/Buffer, which differ across platforms.
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')
}

// The in-flight promise is cached alongside the value so two callers racing on
// startup share one read and cannot generate two different ids.
let cached: string | null = null
let inFlight: Promise<string> | null = null

/** The session id for this device, creating and storing one on first run. */
export function getSessionId(): Promise<string> {
  if (cached) return Promise.resolve(cached)
  if (inFlight) return inFlight

  inFlight = (async () => {
    try {
      const stored = await AsyncStorage.getItem(SESSION_KEY)
      if (stored) {
        cached = stored
        return stored
      }
    } catch (e) {
      // Storage unavailable (private browsing, quota). A session that forgets
      // on restart beats a broken app, so mint a fresh id and carry on.
    }

    const created = generateSessionId()
    try {
      await AsyncStorage.setItem(SESSION_KEY, created)
    } catch (e) {
      // Same reasoning — an in-memory-only session still works.
    }
    cached = created
    return created
  })()

  return inFlight
}

/**
 * Forget this device's session, and with it the link to its saved threads.
 * It is the "sign out" primitive the connectors screen uses (PRD §7), kept
 * here so that flow never touches storage keys directly.
 */
export async function resetSessionId(): Promise<void> {
  cached = null
  inFlight = null
  try {
    await AsyncStorage.removeItem(SESSION_KEY)
  } catch (e) {
    // Nothing useful to do — the cache is already cleared.
  }
}

/** Restore a previously saved session id, switching this device to that session. */
export async function setSessionId(id: string): Promise<void> {
  cached = id
  inFlight = null
  try {
    await AsyncStorage.setItem(SESSION_KEY, id)
  } catch {
    // In-memory update still takes effect.
  }
}
