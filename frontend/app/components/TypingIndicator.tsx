/**
 * The three bouncing dots shown while Scotty is answering, laid out to match
 * the assistant row in ChatMessage so they sit where the answer will appear.
 *
 * Hand-rolled because assistant-ui's <ThreadPrimitive.InProgress> and
 * @assistant-ui/elements-typing-indicator render DOM nodes, which a React
 * Native app cannot use. app/index.tsx owns the show/hide.
 */

import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Animated, Easing, Image, Platform, StyleSheet, Text, View } from 'react-native'

import { MODE_LABELS } from '../lib/assistantAdapter'
import { getNoRun, getRun, subscribeToRuns } from '../lib/runs'
import { colors, fonts, radius, spacing } from '../lib/theme'

const MASCOT = require('../assets/mascot.png')

/** Every dot runs on this same clock. */
const CYCLE_MS = 1100
/** How long a single dot takes to rise, and again to fall. */
const STEP_MS = 220
/** What makes it read as a wave rather than a pulse. */
const STAGGER_MS = 160
const DOT_DELAYS = [0, STAGGER_MS, STAGGER_MS * 2]

// react-native-web has no native animation module, so asking for the native
// driver there only produces a console warning.
const USE_NATIVE_DRIVER = Platform.OS !== 'web'

function Dot({ delay }: { delay: number }) {
  // useRef, not useState: mutated 60x/second, and must never re-render.
  const progress = useRef(new Animated.Value(0)).current

  useEffect(() => {
    // Idling out the rest of the cycle keeps all three loops the same length,
    // so the wave never drifts out of phase.
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

/**
 * Names the lane that is running, with elapsed seconds beside it.
 *
 * The assistant-ui `thinking-indicator` element is the same idea, but it is a
 * shadcn copy-paste of Tailwind classNames on DOM nodes, so it is a pattern to
 * port rather than a component to install. The data behind it is ours already:
 * `mode_start` / `mode_end` have been on the wire since SSE landed.
 *
 * It earns its place now rather than being polish. Managed Agents pushed
 * time-to-first-token to roughly half a minute (docs/b4-planner.md), so without
 * this the demo is a bouncing dot for 30 seconds with nothing to say for itself.
 */
function ThinkingStatus({ threadId }: { threadId: string }) {
  // Per thread, because two answers can now be generating at once — a single
  // global slot would show one conversation's lanes under the other's question.
  const run = useSyncExternalStore(
    subscribeToRuns,
    () => getRun(threadId),
    getNoRun,
  )

  // Re-render once a second purely to advance the clock. Mounted only while the
  // indicator is up, so the timer stops when the answer starts.
  const [, tick] = useState(0)
  const startedAt = run?.startedAt ?? 0
  useEffect(() => {
    if (!startedAt) return
    const timer = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(timer)
  }, [startedAt])

  if (!run) return null

  const seconds = Math.floor((Date.now() - run.startedAt) / 1000)
  const label =
    run.lanes.length > 0
      ? `Checking ${run.lanes.map((mode) => MODE_LABELS[mode]).join(', ')}`
      : 'Working'

  return (
    <View style={styles.status}>
      <Text style={styles.statusLabel} numberOfLines={1}>
        {label}
      </Text>
      {/* Tabular figures, or the line twitches every time the width changes. */}
      {seconds > 0 ? <Text style={styles.elapsed}>{seconds}s</Text> : null}
    </View>
  )
}

export function TypingIndicator({ threadId }: { threadId: string }) {
  return (
    <View
      style={styles.row}
      // The dots are decorative; this is their spoken equivalent.
      accessibilityRole="progressbar"
      accessibilityLabel="Scotty is thinking"
    >
      <Image source={MASCOT} style={styles.avatar} accessibilityLabel="Scotty" />
      <View style={styles.stack}>
        <View style={styles.bubble}>
          {DOT_DELAYS.map((delay) => (
            <Dot key={delay} delay={delay} />
          ))}
        </View>
        <ThinkingStatus threadId={threadId} />
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
    // A small stub of the assistant card, rather than the full row width.
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
  // Under the dots rather than beside them: the lane list grows as lanes start,
  // and on a phone that would push the bubble off the edge.
  stack: {
    alignItems: 'flex-start',
    gap: spacing.xs,
  },
  status: {
    flexDirection: 'row',
    alignItems: 'baseline',
    gap: spacing.sm,
    paddingHorizontal: spacing.xs,
  },
  statusLabel: {
    fontSize: 12,
    color: colors.textFaint,
  },
  elapsed: {
    fontSize: 11,
    color: colors.textFaint,
    fontFamily: fonts.mono,
    // Or the row twitches every second as the digits change width.
    fontVariant: ['tabular-nums'],
  },
})
