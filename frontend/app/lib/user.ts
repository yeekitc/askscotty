/**
 * A stand-in until there is an auth flow. Screens read `user.displayName`
 * rather than hardcoding a name, so `useCurrentUser` is the only body that
 * needs swapping when one exists.
 */

export type CurrentUser = {
  displayName: string
}

const DEFAULT_DISPLAY_NAME = 'Yee Kit'

export function useCurrentUser(): CurrentUser {
  return { displayName: process.env.EXPO_PUBLIC_DEMO_USER_NAME ?? DEFAULT_DISPLAY_NAME }
}
