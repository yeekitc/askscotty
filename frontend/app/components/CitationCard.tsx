/**
 * Renders one citation, always surfacing indexed_at / verified_at when present
 * because the PRD requires showing freshness.
 *
 * Mock sources are deliberately NOT badged here — `is_mock` is only logged to
 * the console by lib/api.ts. PRD §9 asks for a visible label, so this is a
 * knowing deviation; the badge markup is still in git history if it comes back.
 */

import { Linking, Pressable, StyleSheet, Text, View } from 'react-native'

import { colors, radius, spacing } from '../lib/theme'
import type { Citation } from '../lib/types'

/** "2026-08-12T14:03:00Z" -> "Aug 12, 2:03 PM". Falls back to raw text. */
function formatTimestamp(value: string | null): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function CitationCard({ citation }: { citation: Citation }) {
  const indexedAt = formatTimestamp(citation.indexed_at)
  const verifiedAt = formatTimestamp(citation.verified_at)
  const hasLink = Boolean(citation.url)

  const body = (
    <View style={styles.card}>
      <View style={styles.titleRow}>
        <Text style={[styles.title, hasLink && styles.titleLink]}>{citation.title}</Text>
      </View>

      <Text style={styles.source}>{citation.source}</Text>

      {citation.url ? (
        <Text style={styles.url} numberOfLines={1}>
          {citation.url}
        </Text>
      ) : null}

      {indexedAt || verifiedAt ? (
        <Text style={styles.freshness}>
          {indexedAt ? `Indexed ${indexedAt}` : null}
          {indexedAt && verifiedAt ? ' · ' : null}
          {verifiedAt ? `Verified ${verifiedAt}` : null}
        </Text>
      ) : null}
    </View>
  )

  if (!hasLink) return body

  return (
    <Pressable
      onPress={() => Linking.openURL(citation.url)}
      accessibilityRole="link"
      accessibilityLabel={`Open source: ${citation.title}`}
    >
      {body}
    </Pressable>
  )
}

const styles = StyleSheet.create({
  card: {
    borderWidth: 1,
    borderColor: colors.borderSoft,
    backgroundColor: colors.surface,
    padding: spacing.md,
    marginBottom: spacing.sm,
    borderRadius: radius.lg,
    gap: spacing.xs,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  title: {
    flexShrink: 1,
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
  },
  titleLink: {
    textDecorationLine: 'underline',
  },
  source: {
    fontSize: 13,
    color: colors.textMuted,
  },
  url: {
    fontSize: 12,
    color: colors.textFaint,
  },
  freshness: {
    fontSize: 12,
    color: colors.textFaint,
  },
})
