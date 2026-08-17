/**
 * Renders one citation, always surfacing indexed_at / verified_at when present
 * because the PRD requires showing freshness.
 *
 * This is the full rendering — url, freshness and the supporting excerpt. It is
 * the body of the preview a `[S1]` chip opens, and what a source card in the
 * list expands to reach. The list itself uses a compact card of its own.
 *
 * Mock sources are deliberately NOT badged here — `is_mock` only reaches the
 * console, via lib/api.ts. PRD §9 asks for a visible label, so this is a known
 * and accepted deviation rather than an oversight.
 */

import { Linking, Pressable, StyleSheet, Text, View } from 'react-native'

import { relativeTime } from '../lib/citations'
import { colors, radius, spacing } from '../lib/theme'
import type { Citation } from '../lib/types'

export function CitationCard({ citation }: { citation: Citation }) {
  const indexedAt = relativeTime(citation.indexed_at)
  const verifiedAt = relativeTime(citation.verified_at)
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

      {citation.snippet ? (
        <Text style={styles.snippet} numberOfLines={3}>
          {citation.snippet}
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
  // The supporting excerpt. Capped at three lines: this is the evidence for one
  // claim, not the page.
  snippet: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.textMuted,
    fontStyle: 'italic',
  },
})
