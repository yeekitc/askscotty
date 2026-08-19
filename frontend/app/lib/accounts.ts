import AsyncStorage from '@react-native-async-storage/async-storage'

const ACCOUNTS_KEY = 'askscotty.saved_accounts'

export type SavedAccount = {
  sessionId: string   // bearer token — treat like a password
  displayName: string // snapshot at save time
  savedAt: string     // ISO 8601, newest first
}

export async function getSavedAccounts(): Promise<SavedAccount[]> {
  try {
    const raw = await AsyncStorage.getItem(ACCOUNTS_KEY)
    if (!raw) return []
    return JSON.parse(raw) as SavedAccount[]
  } catch {
    return []
  }
}

export async function saveAccount(sessionId: string, displayName: string): Promise<void> {
  const accounts = await getSavedAccounts()
  const entry: SavedAccount = { sessionId, displayName, savedAt: new Date().toISOString() }
  const rest = accounts.filter((a) => a.sessionId !== sessionId)
  const updated = [entry, ...rest]
  try {
    await AsyncStorage.setItem(ACCOUNTS_KEY, JSON.stringify(updated))
  } catch {
    // Nothing to do — the list is purely a UX convenience.
  }
}

export async function removeAccount(sessionId: string): Promise<void> {
  const accounts = await getSavedAccounts()
  const updated = accounts.filter((a) => a.sessionId !== sessionId)
  try {
    await AsyncStorage.setItem(ACCOUNTS_KEY, JSON.stringify(updated))
  } catch {
    // Same.
  }
}
