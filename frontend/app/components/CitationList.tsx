/**
 * An answer's sources, grouped by where they came from.
 *
 * Grouping is what makes the mix legible: "CMU Courses API" and "CMU Eats" are
 * live structured lookups, the campus index is a crawl from some days ago, and
 * the open web is neither. Run together as one list they read as equally
 * authoritative, which is the impression PRD §9 exists to prevent.
 *
 * **Only what the answer cited, by default.** A tool issues a citation per row
 * it returns — one course search can issue a dozen — and rendering all of them
 * buries the four the answer actually leaned on. The rest stay one tap away
 * rather than being dropped, because which sources were consulted and not used
 * is still true and still the reader's to see.
 *
 * Rendered here rather than through `Message.Content`'s `renderSource` slot,
 * which emits each source where it appears in the part list and so cannot group
 * them.
 */

import { useMemo, useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { citedIds } from '../lib/citations'
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

export function CitationList({ citations, answer }: { citations: Citation[]; answer: string }) {
  const [expanded, setExpanded] = useState(false)

  const shown = useMemo(() => {
    if (expanded) return citations
    const cited = citedIds(answer)
    const used = citations.filter((citation) => cited.has(citation.id))
    // Nothing cited means there is no signal to filter on — an answer written
    // without markers, or the setting turned off — so show the lot.
    return used.length > 0 ? used : citations
  }, [citations, answer, expanded])

  const groups = useMemo(() => groupBySource(shown), [shown])
  const hidden = citations.length - shown.length

  if (citations.length === 0) return null

  return (
    <View style={styles.list}>
      {groups.map(([source, items]) => (
        <View key={source}>
          <Text style={styles.groupLabel}>{source}</Text>
          {items.map((citation) => (
            // The group header above already names the source.
            <CitationCard key={citation.id} citation={citation} hideSource />
          ))}
        </View>
      ))}

      {hidden > 0 || expanded ? (
        <Pressable
          onPress={() => setExpanded(!expanded)}
          accessibilityRole="button"
          hitSlop={8}
          style={styles.toggle}
        >
          <Text style={styles.toggleText}>
            {expanded
              ? 'Show only cited sources'
              : `Show ${hidden} more ${hidden === 1 ? 'source' : 'sources'} that were checked`}
          </Text>
        </Pressable>
      ) : null}
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
  toggle: {
    alignSelf: 'flex-start',
  },
  toggleText: {
    fontSize: 12,
    color: colors.textMuted,
    textDecorationLine: 'underline',
  },
})
