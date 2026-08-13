/**
 * The signed-in student. There's no auth flow yet, so this is a stand-in —
 * once one exists, swap the body of `useCurrentUser` for the real session
 * user. Screens should read `user.displayName` instead of hardcoding a name,
 * so that swap is the only place that needs to change.
 */

export type CurrentUser = {
  displayName: string
}

const DEFAULT_DISPLAY_NAME = 'Yee Kit'

export function useCurrentUser(): CurrentUser {
  return { displayName: process.env.EXPO_PUBLIC_DEMO_USER_NAME ?? DEFAULT_DISPLAY_NAME }
}
