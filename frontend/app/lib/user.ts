/**
 * A stand-in until there is an auth flow. Screens read `user.displayName`
 * rather than hardcoding a name, so `useCurrentUser` is the only body that
 * needs swapping when one exists.
 */

import AsyncStorage from '@react-native-async-storage/async-storage'
import { useEffect, useState } from 'react'

const DISPLAY_NAME_KEY = 'askscotty.display_name'
const PROFILE_PICTURE_KEY = 'askscotty.profile_picture'

export type CurrentUser = {
  displayName: string
  displayNameLoaded: boolean
  profilePicture: string
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

type PictureListener = (uri: string) => void
const pictureListeners = new Set<PictureListener>()
let pictureCache: string | null = null

/** Persist a new profile picture URI and notify all mounted useCurrentUser hooks. */
export async function setProfilePicture(uri: string): Promise<void> {
  pictureCache = uri
  try {
    await AsyncStorage.setItem(PROFILE_PICTURE_KEY, uri)
  } catch {
    // In-memory update still propagates even if storage fails.
  }
  for (const fn of pictureListeners) fn(uri)
}

export function useCurrentUser(): CurrentUser {
  const [name, setName] = useState<string | null>(cache)
  const [picture, setPicture] = useState<string | null>(pictureCache)

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

    if (pictureCache !== null) {
      setPicture(pictureCache)
    } else {
      AsyncStorage.getItem(PROFILE_PICTURE_KEY)
        .then((stored) => {
          if (!cancelled) {
            pictureCache = stored ?? ''
            setPicture(pictureCache)
          }
        })
        .catch(() => {
          if (!cancelled) {
            pictureCache = ''
            setPicture('')
          }
        })
    }

    const listener: Listener = (n) => {
      if (!cancelled) setName(n)
    }
    listeners.add(listener)

    const pictureListener: PictureListener = (uri) => {
      if (!cancelled) setPicture(uri)
    }
    pictureListeners.add(pictureListener)

    return () => {
      cancelled = true
      listeners.delete(listener)
      pictureListeners.delete(pictureListener)
    }
  }, [])

  return { displayName: name ?? '', displayNameLoaded: name !== null, profilePicture: picture ?? '' }
}
