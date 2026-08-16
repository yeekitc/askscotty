/**
 * Motion tokens, and the reduced-motion gate every animation goes through.
 *
 * Reanimated rather than RN's `Animated`: react-native-web has no native driver
 * (see USE_NATIVE_DRIVER in components/TypingIndicator.tsx), so Animated runs on
 * the JS thread there — and the sidebar drives a layout width, which stutters
 * badly off the UI thread. Reanimated has no such platform split.
 */

import { Easing } from 'react-native-reanimated'

export { useReducedMotion } from 'react-native-reanimated'

export const durations = {
  /** Press and hover feedback. Slower than this reads as lag, not polish. */
  fast: 120,
  /** Fades and short offsets. */
  base: 200,
  /** Surfaces that cross the screen — the sidebar. */
  slow: 260,
}

/** Leaves quickly, settles softly. The CSS ease-out most web UIs transition on. */
export const easing = Easing.bezier(0.22, 1, 0.36, 1)

/** Underdamped just enough to feel physical, not enough to visibly wobble. */
export const pressSpring = { mass: 0.4, damping: 14, stiffness: 320 }
