/**
 * One row in the thread. MessagePrimitive reads the current message from
 * ambient context, so nothing has to be passed in as a prop.
 */

import { useEffect } from 'react'
import { Image, StyleSheet, Text, View } from 'react-native'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'
import { MessagePrimitive as Message, useAuiState } from '@assistant-ui/react-native'

import { durations, easing, useReducedMotion } from '../lib/motion'
import { colors, radius, spacing } from '../lib/theme'
import { sourcePartToCitation } from '../lib/assistantAdapter'
import { AnswerText } from './AnswerText'
import { CitationCard } from './CitationCard'

const MASCOT = require('../assets/mascot.png')

export function ChatMessage() {
  // The runtime creates the assistant message as soon as a run starts, and an
  // empty card sitting above the typing indicator reads as a broken answer.
  // TypingIndicator holds this slot until there is something to put in it.
  const isBlank = useAuiState(
    (state) =>
      state.message.role === 'assistant' &&
      !state.message.content.some((part) => part.type !== 'text' || part.text.length > 0),
  )

  const reduceMotion = useReducedMotion()

  // Driven off isBlank rather than mount: the assistant message is mounted
  // empty for the whole wait, so this has to fire when content arrives, which
  // is also when TypingIndicator starts fading out.
  const enter = useSharedValue(0)
  useEffect(() => {
    if (isBlank) return
    enter.value = reduceMotion ? 1 : withTiming(1, { duration: durations.base, easing })
  }, [isBlank, reduceMotion, enter])

  const enterStyle = useAnimatedStyle(() => ({
    opacity: enter.value,
    transform: [{ translateY: (1 - enter.value) * 6 }],
  }))

  if (isBlank) return null

  return (
    <Animated.View style={enterStyle}>
      <Message.Root style={styles.root}>
        <Message.If user>
          <View style={styles.userRow}>
            <View style={styles.userBubble}>
              <Message.Content
                renderText={({ part }) => <Text style={styles.userText}>{part.text}</Text>}
              />
            </View>
          </View>
        </Message.If>

        <Message.If assistant>
          <View style={styles.assistantRow}>
            <Image source={MASCOT} style={styles.avatar} accessibilityLabel="Scotty" />
            <View style={styles.assistantCard}>
              {/* The model writes Markdown — bold, bullets, the occasional
                  heading — and nothing renders it unless we do: assistant-ui's
                  markdown package is React DOM, and the React Native one ships no
                  renderer at all. Without AnswerText the asterisks show up
                  literally. */}
              <Message.Content
                renderText={({ part }) => (
                  <AnswerText text={part.text} style={styles.assistantText} />
                )}
                renderSource={({ part }) => <CitationCard citation={sourcePartToCitation(part)} />}
              />
            </View>
          </View>
        </Message.If>
      </Message.Root>
    </Animated.View>
  )
}

const styles = StyleSheet.create({
  root: {
    marginBottom: spacing.md,
  },
  userRow: {
    alignItems: 'flex-end',
  },
  userBubble: {
    backgroundColor: colors.surface,
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.md,
    borderRadius: radius.xl,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    maxWidth: '80%',
  },
  userText: {
    color: colors.text,
    fontSize: 16,
  },
  assistantRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: spacing.md,
  },
  // No marginTop on purpose: avatar and card are top-aligned children of the
  // same row, so a 0 offset is what lines their top edges up.
  avatar: {
    width: 36,
    height: 36,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSoft,
  },
  assistantCard: {
    flex: 1,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    backgroundColor: colors.surface,
    padding: spacing.lg,
    borderRadius: radius.xl,
    gap: spacing.sm,
  },
  assistantText: {
    fontSize: 16,
    color: colors.text,
    lineHeight: 22,
  },
})
