/**
 * The anonymous session id, and the device storage it lives in.
 *
 * AskScotty has no login (tasklist §1 settled this: an anonymous session id,
 * not Django user accounts). The app generates one id the first time it runs,
 * keeps it on the device, and sends it with every request. That is what scopes
 * a person's chat threads and their connected sources to them.
 *
 * TREAT THIS LIKE A PASSWORD. It is a bearer token, not a username: anyone who
 * has it can read that session's threads and connected data. So it goes in a
 * header rather than a URL (query strings land in server logs), it is never
 * logged, and it is never rendered in the UI.
 *
 * Storage is AsyncStorage rather than localStorage because `window` does not
 * exist on a phone — see CLAUDE.md. AsyncStorage works on all three platforms
 * from this one call, which localStorage never did: before this, native builds
 * silently persisted nothing at all.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'

const SESSION_KEY = 'askscotty.session_id'

/**
 * A URL-safe random id.
 *
 * Deliberately not `Math.random()`: this value guards one student's data from
 * another's, so it uses the platform crypto RNG. `crypto.getRandomValues`
 * exists on web and in React Native's Hermes runtime; the throw is there so a
 * platform without it fails loudly rather than quietly issuing guessable ids.
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

// Cached so the common case is not an async storage read on every request.
// The in-flight promise is cached too, so two callers racing on startup share
// one read and cannot end up generating two different ids.
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
      // Storage unavailable (private browsing, quota). Fall through and mint a
      // fresh id: a working session that forgets on restart beats a broken app.
    }

    const created = generateSessionId()
    try {
      await AsyncStorage.setItem(SESSION_KEY, created)
    } catch (e) {
      // Same reasoning — keep going with an in-memory-only session.
    }
    cached = created
    return created
  })()

  return inFlight
}

/**
 * Forget this device's session, and with it the link to its saved threads.
 *
 * Nothing calls this yet. It is the "sign out" primitive a connectors screen
 * will need (PRD §7), and it lives here so that flow does not reach into
 * storage keys directly.
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
