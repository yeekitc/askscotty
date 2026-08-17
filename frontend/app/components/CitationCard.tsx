/**
 * Renders one citation, always surfacing indexed_at / verified_at when present
 * because the PRD requires showing freshness.
 *
 * Used twice over: in the grouped list below an answer, and as the body of the
 * preview a `[S1]` chip opens.
 *
 * Mock sources are deliberately NOT badged here — `is_mock` only reaches the
 * console, via lib/api.ts. PRD §9 asks for a visible label, so this is a known
 * and accepted deviation rather than an oversight.
 */

import { Linking, Pressable, StyleSheet, Text, View } from 'react-native'

import { colors, radius, spacing } from '../lib/theme'
import type { Citation } from '../lib/types'

const MINUTE = 60
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/**
 * "2026-08-12T14:03:00Z" -> "3 days ago". Falls back to the raw text.
 *
 * Relative rather than a date, because the question a reader actually has is
 * how stale this is, and answering it with "Aug 12" makes them do the
 * subtraction. Hand-rolled: `Intl.RelativeTimeFormat` is not in Hermes.
 *
 * A timestamp in the future is clock skew between us and the source, not a
 * prediction, so it clamps to "just now" rather than counting down.
 */
function relativeTime(value: string | null): string | null {
  if (!value) return null
  const at = new Date(value).getTime()
  if (Number.isNaN(at)) return value

  const seconds = Math.max(0, Math.round((Date.now() - at) / 1000))
  if (seconds < 45) return 'just now'
  if (seconds < 90 * MINUTE) return `${Math.round(seconds / MINUTE)} min ago`
  if (seconds < 36 * HOUR) return `${Math.round(seconds / HOUR)} hr ago`

  const days = Math.round(seconds / DAY)
  if (days < 30) return days === 1 ? '1 day ago' : `${days} days ago`

  const months = Math.round(days / 30)
  return months === 1 ? '1 month ago' : `${months} months ago`
}

export function CitationCard({
  citation,
  hideSource = false,
}: {
  citation: Citation
  /** Set when a group header already names the source, so it isn't said twice. */
  hideSource?: boolean
}) {
  const indexedAt = relativeTime(citation.indexed_at)
  const verifiedAt = relativeTime(citation.verified_at)
  const hasLink = Boolean(citation.url)

  const body = (
    <View style={styles.card}>
      <View style={styles.titleRow}>
        <Text style={[styles.title, hasLink && styles.titleLink]}>{citation.title}</Text>
      </View>

      {hideSource ? null : <Text style={styles.source}>{citation.source}</Text>}

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
  // The supporting excerpt. Capped at three lines: this is the evidence for one
  // claim, not the page.
  snippet: {
    fontSize: 13,
    lineHeight: 18,
    color: colors.textMuted,
    fontStyle: 'italic',
  },
})
