/**
 * The search/ask pill, used both centered under the hero and pinned to the
 * bottom of an active thread (app/index.tsx). Built on ComposerPrimitive, so
 * Enter-to-send and clear-on-submit come from assistant-ui; the source filter
 * dropdown is ours, as it has no primitive of its own.
 */

import { useState } from 'react'
import { StyleSheet, Text, View } from 'react-native'
import Animated, { useAnimatedStyle, useSharedValue, withSpring } from 'react-native-reanimated'
import { ComposerPrimitive as Composer } from '@assistant-ui/react-native'

import { PRESS_SCALE, pressSpring, useReducedMotion } from '../lib/motion'
import { colors, radius, shadows, spacing } from '../lib/theme'
import { LANES, type Mode } from '../lib/types'
import { HoverPressable } from './HoverPressable'

type Props = {
  /** Lanes the reader has unchecked. Everything not listed here is on. */
  disabledModes: Mode[]
  onDisabledModesChange: (modes: Mode[]) => void
}

export function AskComposer({ disabledModes, onDisabledModesChange }: Props) {
  const [showSources, setShowSources] = useState(false)
  const [sendHovered, setSendHovered] = useState(false)
  const reduceMotion = useReducedMotion()

  // Scales the wrapper rather than the button: Composer.Send takes a plain
  // style, so there is nowhere on it to hang an animated one.
  const sendScale = useSharedValue(1)
  const sendStyle = useAnimatedStyle(() => ({ transform: [{ scale: sendScale.value }] }))

  function springSend(to: number) {
    sendScale.value = reduceMotion ? 1 : withSpring(to, pressSpring)
  }

  function toggleLane(mode: Mode) {
    onDisabledModesChange(
      disabledModes.includes(mode)
        ? disabledModes.filter((m) => m !== mode)
        : [...disabledModes, mode],
    )
  }

  return (
    <View style={styles.wrap}>
      <Composer.Root style={styles.pill}>
        <Composer.Input
          style={styles.input}
          placeholder="Search CMU databases for courses, people, policies, and more..."
          placeholderTextColor={colors.textFaint}
          accessibilityLabel="Ask Scotty"
        />

        <HoverPressable
          style={({ pressed, hovered }) => [
            styles.sourcesButton,
            (pressed || hovered) && styles.sourcesButtonActive,
          ]}
          accessibilityRole="button"
          accessibilityState={{ expanded: showSources }}
          onPress={() => setShowSources((s) => !s)}
        >
          <Text style={styles.sourcesText}>Sources ▾</Text>
        </HoverPressable>

        <Animated.View style={sendStyle}>
          <Composer.Send
            onHoverIn={() => setSendHovered(true)}
            onHoverOut={() => setSendHovered(false)}
            onPressIn={() => springSend(PRESS_SCALE)}
            onPressOut={() => springSend(1)}
            style={({ pressed }) => [
              styles.sendButton,
              (pressed || sendHovered) && styles.sendButtonActive,
            ]}
          >
            <Text style={styles.sendText}>↑</Text>
          </Composer.Send>
        </Animated.View>
      </Composer.Root>

      {showSources ? (
        <View style={styles.menu}>
          {LANES.map(({ mode, label, mock }) => {
            const checked = !disabledModes.includes(mode)
            return (
              <HoverPressable
                key={mode}
                style={({ hovered }) => [styles.menuItem, hovered && styles.menuItemHovered]}
                onPress={() => toggleLane(mode)}
                accessibilityRole="checkbox"
                accessibilityState={{ checked }}
                accessibilityLabel={mock ? `${label}, placeholder data` : label}
              >
                <View style={[styles.checkbox, checked && styles.checkboxChecked]}>
                  {checked ? <Text style={styles.checkmark}>✓</Text> : null}
                </View>
                <Text style={styles.menuText}>{label}</Text>
                {/* PRD §9: a fixture lane must say so wherever it is shown. */}
                {mock ? <Text style={styles.menuBadge}>mock</Text> : null}
              </HoverPressable>
            )
          })}
        </View>
      ) : null}
    </View>
  )
}

const styles = StyleSheet.create({
  wrap: {
    width: '100%',
    maxWidth: 720,
    alignSelf: 'center',
    // Anchors the dropdown, which opens upward over the page rather than
    // pushing the pill and everything below it up.
    position: 'relative',
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    backgroundColor: colors.surface,
    borderRadius: radius.pill,
    paddingVertical: 8,
    paddingHorizontal: 12,
    ...shadows.soft,
  },
  input: {
    flex: 1,
    fontSize: 16,
    color: colors.text,
    paddingVertical: 8,
    paddingHorizontal: 8,
  },
  sourcesButton: {
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginRight: 8,
    borderRadius: radius.md,
  },
  sourcesButtonActive: {
    backgroundColor: colors.sidebarHover,
  },
  sourcesText: {
    color: colors.textMuted,
    fontSize: 14,
  },
  sendButton: {
    backgroundColor: colors.accent,
    borderRadius: radius.pill,
    paddingHorizontal: 14,
    paddingVertical: 8,
    marginLeft: 8,
  },
  sendButtonActive: {
    opacity: 0.8,
  },
  sendText: {
    color: colors.accentText,
    fontSize: 16,
    fontWeight: '700',
  },
  menu: {
    position: 'absolute',
    bottom: '100%',
    right: 0,
    marginBottom: spacing.sm,
    zIndex: 50,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    padding: spacing.sm,
    minWidth: 190,
    ...shadows.soft,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 8,
    paddingHorizontal: spacing.sm,
    gap: spacing.sm,
    borderRadius: radius.sm,
  },
  menuItemHovered: {
    backgroundColor: colors.sidebarHover,
  },
  checkbox: {
    width: 16,
    height: 16,
    borderRadius: 4,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxChecked: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  checkmark: {
    color: colors.accentText,
    fontSize: 11,
    fontWeight: '700',
  },
  menuText: {
    color: colors.text,
    fontSize: 14,
  },
  menuBadge: {
    marginLeft: spacing.xs,
    color: colors.textMuted,
    fontSize: 11,
    textTransform: 'uppercase',
  },
})
