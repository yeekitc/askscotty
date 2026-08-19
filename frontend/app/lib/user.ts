/**
 * A stand-in until there is an auth flow. Screens read `user.displayName`
 * rather than hardcoding a name, so `useCurrentUser` is the only body that
 * needs swapping when one exists.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect, useState } from 'react'

const DISPLAY_NAME_KEY = 'askscotty.display_name'

export type CurrentUser = {
  displayName: string
  displayNameLoaded: boolean
}

type Listener = (name: string) => void
const listeners = new Set<Listener>()
// null = not yet read from storage; string = known value (including empty string)
let cache: string | null = null

/** Persist a new display name and notify all mounted useCurrentUser hooks. */
export async function setDisplayName(name: string): Promise<void> {
  cache = name
  try {
    await AsyncStorage.setItem(DISPLAY_NAME_KEY, name)
  } catch {
    // In-memory update still propagates even if storage fails.
  }
  for (const fn of listeners) fn(name)
}

export function useCurrentUser(): CurrentUser {
  const [name, setName] = useState<string | null>(cache)

  useEffect(() => {
    let cancelled = false

    if (cache !== null) {
      setName(cache)
    } else {
      AsyncStorage.getItem(DISPLAY_NAME_KEY)
        .then((stored) => {
          if (!cancelled) {
            cache = stored ?? ''
            setName(cache)
          }
        })
        .catch(() => {
          if (!cancelled) {
            cache = ''
            setName('')
          }
        })
    }

    const listener: Listener = (n) => {
      if (!cancelled) setName(n)
    }
    listeners.add(listener)
    return () => {
      cancelled = true
      listeners.delete(listener)
    }
  }, [])

  return { displayName: name ?? '', displayNameLoaded: name !== null }
}
