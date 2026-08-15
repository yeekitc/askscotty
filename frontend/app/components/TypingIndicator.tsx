/**
 * The three bouncing dots shown while Scotty is answering.
 *
 * Rendered by app/index.tsx inside <Thread.If running>, which is
 * assistant-ui's loading primitive on React Native — the runtime flips
 * `isRunning` for the whole duration of the adapter's run(), so nothing here
 * needs its own loading state. (The web-only <ThreadPrimitive.InProgress>
 * and @assistant-ui/elements-typing-indicator render DOM nodes, so they
 * can't be used in this codebase — see CLAUDE.md.)
 *
 * Laid out to match the assistant row in ChatMessage (same avatar, same
 * card) so the dots sit exactly where the answer is about to appear.
 */

import { useEffect, useRef } from 'react'
import { Animated, Easing, Image, Platform, StyleSheet, View } from 'react-native'

import { colors, radius, spacing } from '../lib/theme'

const MASCOT = require('../assets/mascot.png')

/** One full loop of the animation. Every dot runs on this same clock. */
const CYCLE_MS = 1100
/** How long a single dot takes to rise, and again to fall. */
const STEP_MS = 220
/** Stagger between dots — what makes it read as a wave rather than a pulse. */
const STAGGER_MS = 160
const DOT_DELAYS = [0, STAGGER_MS, STAGGER_MS * 2]

// react-native-web has no native animation module, so asking for the native
// driver there only produces a console warning. Phones get the real thing.
const USE_NATIVE_DRIVER = Platform.OS !== 'web'

function Dot({ delay }: { delay: number }) {
  // useRef, not useState: this value is mutated 60x/second by the animation
  // and must never trigger a React re-render.
  const progress = useRef(new Animated.Value(0)).current

  useEffect(() => {
    // Each dot waits out its own stagger, bounces, then idles for whatever
    // is left of the cycle — so all three loops stay the same length and
    // the wave never drifts out of phase.
    const rest = CYCLE_MS - delay - STEP_MS * 2

    const animation = Animated.loop(
      Animated.sequence([
        Animated.delay(delay),
        Animated.timing(progress, {
          toValue: 1,
          duration: STEP_MS,
          easing: Easing.out(Easing.quad),
          useNativeDriver: USE_NATIVE_DRIVER,
        }),
        Animated.timing(progress, {
          toValue: 0,
          duration: STEP_MS,
          easing: Easing.in(Easing.quad),
          useNativeDriver: USE_NATIVE_DRIVER,
        }),
        Animated.delay(rest),
      ]),
    )

    animation.start()
    // Stops the loop when the answer arrives and this component unmounts.
    return () => animation.stop()
  }, [delay, progress])

  return (
    <Animated.View
      style={[
        styles.dot,
        {
          opacity: progress.interpolate({ inputRange: [0, 1], outputRange: [0.3, 1] }),
          transform: [
            { translateY: progress.interpolate({ inputRange: [0, 1], outputRange: [0, -5] }) },
          ],
        },
      ]}
    />
  )
}

export function TypingIndicator() {
  return (
    <View
      style={styles.row}
      // Screen readers get a spoken equivalent of the dots, which are
      // otherwise purely decorative.
      accessibilityRole="progressbar"
      accessibilityLabel="Scotty is thinking"
    >
      <Image source={MASCOT} style={styles.avatar} accessibilityLabel="Scotty" />
      <View style={styles.bubble}>
        {DOT_DELAYS.map((delay) => (
          <Dot key={delay} delay={delay} />
        ))}
      </View>
    </View>
  )
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
    marginBottom: spacing.md,
  },
  avatar: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSoft,
  },
  bubble: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs + 2,
    // Sized so the bubble reads as a small stub of the assistant card it is
    // standing in for, rather than stretching the full row width.
    alignSelf: 'flex-start',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    backgroundColor: colors.surface,
    borderRadius: radius.xl,
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: radius.pill,
    backgroundColor: colors.textMuted,
  },
})
