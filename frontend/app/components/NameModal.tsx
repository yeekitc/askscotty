/**
 * First-run welcome dialog. Appears once — when displayNameLoaded is true but
 * displayName is empty — and resolves as soon as the user submits a name.
 * No tap-to-dismiss: a name is required to proceed.
 */

import { useEffect, useState } from 'react'
import { Modal, Pressable, StyleSheet, Text, TextInput, View } from 'react-native'
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated'

import { durations, easing, offsets, useReducedMotion } from '../lib/motion'
import { colors, radius, shadows, spacing } from '../lib/theme'
import { setDisplayName } from '../lib/user'

type Props = {
  visible: boolean
}

export function NameModal({ visible }: Props) {
  const reduceMotion = useReducedMotion()
  const enter = useSharedValue(0)
  const [mounted, setMounted] = useState(visible)
  const [name, setName] = useState('')

  useEffect(() => {
    if (visible) {
      setMounted(true)
      enter.value = reduceMotion ? 1 : withTiming(1, { duration: durations.entrance, easing })
    } else if (mounted) {
      if (reduceMotion) {
        setMounted(false)
        return
      }
      enter.value = withTiming(0, { duration: durations.base, easing }, (finished) => {
        if (finished) runOnJS(setMounted)(false)
      })
    }
  }, [visible, mounted, reduceMotion, enter])

  const cardStyle = useAnimatedStyle(() => ({
    opacity: enter.value,
    transform: [{ translateY: (1 - enter.value) * offsets.view }],
  }))

  const canSubmit = name.trim().length > 0

  const handleSubmit = async () => {
    if (!canSubmit) return
    await setDisplayName(name.trim())
  }

  return (
    <Modal visible={mounted} transparent animationType="none">
      <View style={styles.root}>
        <Animated.View style={[styles.card, cardStyle]}>
          <Text style={styles.title}>Welcome to AskScotty</Text>
          <Text style={styles.subtitle}>What should Scotty call you?</Text>
          <TextInput
            style={styles.input}
            value={name}
            onChangeText={setName}
            placeholder="Your name"
            placeholderTextColor={colors.textFaint}
            autoFocus
            autoCapitalize="words"
            autoCorrect={false}
            returnKeyType="done"
            onSubmitEditing={handleSubmit}
          />
          <Pressable
            style={[styles.button, !canSubmit && styles.buttonDisabled]}
            onPress={handleSubmit}
            disabled={!canSubmit}
            accessibilityRole="button"
          >
            <Text style={styles.buttonText}>Get started</Text>
          </Pressable>
        </Animated.View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.overlay,
  },
  card: {
    backgroundColor: colors.background,
    borderRadius: radius.xl,
    padding: spacing.xl,
    width: 320,
    ...shadows.soft,
    gap: spacing.sm,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.xs,
  },
  subtitle: {
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: spacing.sm,
  },
  input: {
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    fontSize: 15,
    color: colors.text,
  },
  button: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    alignItems: 'center',
    marginTop: spacing.xs,
  },
  buttonDisabled: {
    opacity: 0.4,
  },
  buttonText: {
    color: colors.accentText,
    fontSize: 14,
    fontWeight: '600',
  },
})
