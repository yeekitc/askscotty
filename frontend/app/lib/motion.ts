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
  fast: 140,
  /** Crossfades between two things occupying the same slot. */
  base: 200,
  /**
   * Content arriving. Deliberately slower than `base`: an entrance that resolves
   * in 200ms next to a 280px sidebar slide is measurably running and still reads
   * as a hard cut.
   */
  entrance: 300,
  /** The sidebar slide. */
  sidebar: 260,
}

/** Entrance offsets. Small enough to stay calm, large enough to register. */
export const offsets = {
  /** Swapping the hero out for the thread. */
  view: 18,
  /** A single message or card arriving. */
  item: 14,
}

/** Leaves quickly, settles softly. The CSS ease-out most web UIs transition on. */
export const easing = Easing.bezier(0.22, 1, 0.36, 1)

/** Underdamped just enough to feel physical, not enough to visibly wobble. */
export const pressSpring = { mass: 0.4, damping: 14, stiffness: 320 }

/** How far the send button shrinks under a finger. */
export const PRESS_SCALE = 0.9
