/**
 * An answer's sources, grouped by where they came from.
 *
 * Grouping is what makes the mix legible: "CMU Courses API" and "CMU Eats" are
 * live structured lookups, the campus index is a crawl from some days ago, and
 * the open web is neither. Run together as one list they read as equally
 * authoritative, which is the impression PRD §9 exists to prevent.
 *
 * **Folded, once the answer carries inline chips.** A tool issues a citation per
 * row it returns — one course search can issue a dozen — and a wall of cards
 * under an answer whose every claim already links to its source is the same job
 * done twice, worse. Collapsed, the row still names the count and where the
 * sources came from, so provenance is legible without being exhaustive.
 *
 * **It only folds when there is something to fold behind.** An answer with no
 * markers — the setting off, or a model that wrote none — has no inline route
 * to a source, so the list stays open. PRD §9's freshness is then a tap away
 * rather than on screen, which is the deviation this makes knowingly.
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

  const groups = useMemo(() => groupBySource(citations), [citations])

  // Whether any chip in the prose actually resolves to one of these. Not just
  // "are there markers" — a marker for an id we do not hold renders nothing,
  // and folding behind a chip that never drew would hide the sources outright.
  const hasChips = useMemo(() => {
    const cited = citedIds(answer)
    return citations.some((citation) => cited.has(citation.id))
  }, [citations, answer])

  if (citations.length === 0) return null

  const open = expanded || !hasChips
  const summary = `${citations.length} ${citations.length === 1 ? 'source' : 'sources'} · ${groups
    .map(([source]) => source)
    .join(', ')}`

  if (!open) {
    return (
      <Pressable
        onPress={() => setExpanded(true)}
        accessibilityRole="button"
        accessibilityState={{ expanded: false }}
        hitSlop={8}
        style={styles.toggle}
      >
        {/* Named, not just counted: "12 sources" says nothing about whether to
            trust them, "12 sources · CMU Courses API" does. */}
        <Text style={styles.summary} numberOfLines={1}>
          {summary}
        </Text>
      </Pressable>
    )
  }

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

      {hasChips ? (
        <Pressable
          onPress={() => setExpanded(false)}
          accessibilityRole="button"
          accessibilityState={{ expanded: true }}
          hitSlop={8}
          style={styles.toggle}
        >
          <Text style={styles.toggleText}>Hide sources</Text>
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
  summary: {
    fontSize: 12,
    color: colors.textFaint,
  },
})
