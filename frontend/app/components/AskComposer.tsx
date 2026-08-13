/**
 * The search/ask pill — used both centered under the empty-state hero and
 * pinned to the bottom once a thread has messages (see app/index.tsx).
 *
 * Built on ComposerPrimitive so Enter-to-send and clear-on-submit are
 * handled by assistant-ui itself; we only style it and add the source
 * filter dropdown, which is app-specific and has no primitive of its own.
 */

import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { ComposerPrimitive as Composer } from '@assistant-ui/react-native'

import { colors, spacing } from '../lib/theme'

/** Matches the live/mock sources the backend can eventually filter by (PRD §4–§7). */
export const SOURCE_OPTIONS = ['Course Catalog', 'Directory', 'Piazza', 'Canvas', 'Handshake']

type Props = {
  sources: string[]
  onSourcesChange: (sources: string[]) => void
}

export function AskComposer({ sources, onSourcesChange }: Props) {
  const [showSources, setShowSources] = useState(false)

  function toggleSource(name: string) {
    onSourcesChange(
      sources.includes(name) ? sources.filter((s) => s !== name) : [...sources, name],
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

        <Pressable
          style={styles.sourcesButton}
          accessibilityRole="button"
          accessibilityState={{ expanded: showSources }}
          onPress={() => setShowSources((s) => !s)}
        >
          <Text style={styles.sourcesText}>Sources ▾</Text>
        </Pressable>

        <Composer.Send style={styles.sendButton}>
          <Text style={styles.sendText}>↑</Text>
        </Composer.Send>
      </Composer.Root>

      {showSources ? (
        <View style={styles.menu}>
          {SOURCE_OPTIONS.map((name) => {
            const checked = sources.includes(name)
            return (
              <Pressable
                key={name}
                style={styles.menuItem}
                onPress={() => toggleSource(name)}
                accessibilityRole="checkbox"
                accessibilityState={{ checked }}
              >
                <View style={[styles.checkbox, checked && styles.checkboxChecked]}>
                  {checked ? <Text style={styles.checkmark}>✓</Text> : null}
                </View>
                <Text style={styles.menuText}>{name}</Text>
              </Pressable>
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
  },
  pill: {
    flexDirection: 'row',
    alignItems: 'center',
    width: '100%',
    backgroundColor: colors.surface,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.border,
    paddingVertical: 8,
    paddingHorizontal: 12,
    shadowColor: '#000',
    shadowOpacity: 0.05,
    shadowRadius: 8,
    elevation: 2,
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
    borderLeftWidth: 1,
    borderLeftColor: colors.border,
  },
  sourcesText: {
    color: colors.textMuted,
    fontSize: 14,
  },
  sendButton: {
    backgroundColor: colors.accent,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 8,
    marginLeft: 8,
  },
  sendText: {
    color: colors.accentText,
    fontSize: 16,
    fontWeight: '700',
  },
  menu: {
    marginTop: spacing.sm,
    alignSelf: 'flex-end',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    padding: spacing.sm,
    minWidth: 180,
  },
  menuItem: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    gap: spacing.sm,
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
})
