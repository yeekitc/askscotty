/**
 * One row in the thread — a user bubble or a Scotty-avatar assistant card.
 *
 * Rendered once per message by Thread.MessagesFlatList (see app/index.tsx).
 * MessagePrimitive components read the current message from ambient
 * context, so this component doesn't need the message passed in as a prop.
 */

import { Image, StyleSheet, Text, View } from 'react-native'
import { MessagePrimitive as Message } from '@assistant-ui/react-native'

import { colors, radius, spacing } from '../lib/theme'
import { sourcePartToCitation } from '../lib/assistantAdapter'
import { CitationCard } from './CitationCard'

const MASCOT = require('../assets/mascot.png')

export function ChatMessage() {
  return (
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
            <Message.Content
              renderText={({ part }) => <Text style={styles.assistantText}>{part.text}</Text>}
              renderSource={({ part }) => <CitationCard citation={sourcePartToCitation(part)} />}
            />
          </View>
        </View>
      </Message.If>
    </Message.Root>
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
  // No marginTop here on purpose — both the avatar and assistantCard are
  // top-aligned flex children of the same row, so a 0 offset is what makes
  // the avatar's top edge land exactly on the card's top edge.
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
