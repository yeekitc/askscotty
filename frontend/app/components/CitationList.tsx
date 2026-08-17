/**
 * An answer's sources, grouped by where they came from.
 *
 * Grouping is what makes the mix legible: "Courses" and "CMU Eats" are live
 * structured lookups, the campus index is a crawl from some days ago, and the
 * open web is neither. Run together as one list they read as equally
 * authoritative, which is the impression PRD §9 exists to prevent.
 *
 * Rendered here rather than through `Message.Content`'s `renderSource` slot,
 * which emits each source where it appears in the part list and so cannot group
 * them.
 */

import { useMemo } from 'react'
import { StyleSheet, Text, View } from 'react-native'

import { colors, spacing } from '../lib/theme'
import type { Citation } from '../lib/types'
import { CitationCard } from './CitationCard'

/** Groups in first-appearance order, so the numbering still climbs down the page. */
function groupBySource(citations: Citation[]): [string, Citation[]][] {
  const groups = new Map<string, Citation[]>()

  for (const citation of citations) {
    const existing = groups.get(citation.source)
    if (existing) existing.push(citation)
    else groups.set(citation.source, [citation])
  }

  return [...groups]
}

export function CitationList({ citations }: { citations: Citation[] }) {
  const groups = useMemo(() => groupBySource(citations), [citations])

  if (citations.length === 0) return null

  return (
    <View style={styles.list}>
      {groups.map(([source, items]) => (
        <View key={source}>
          <Text style={styles.groupLabel}>{source}</Text>
          {items.map((citation) => (
            <CitationCard key={citation.id} citation={citation} />
          ))}
        </View>
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  list: {
    gap: spacing.sm,
  },
  groupLabel: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.textFaint,
    marginBottom: spacing.xs,
  },
})
