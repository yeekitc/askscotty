/**
 * An answer's sources: a two-column grid of cards, capped at 4 by default.
 *
 * A tool issues a citation per row it returns — one course search can issue
 * twenty — so cards beyond the first four are hidden behind a "Show all N
 * sources" button. Grouping by source keeps live structured lookups ("CMU
 * Courses API") visually separate from crawled or web results, so they don't
 * read as equally authoritative (PRD §9).
 *
 * Rendered here rather than through `Message.Content`'s `renderSource` slot,
 * which emits each source where it appears in the part list and so cannot group
 * them.
 */

import { useMemo, useRef, useState } from 'react'
import { Linking, Pressable, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native'

import { relativeTime } from '../lib/citations'
import { colors, fonts, radius, spacing } from '../lib/theme'
import type { Citation } from '../lib/types'
import { useCitationOverlay } from './CitationOverlay'
import { HoverPressable } from './HoverPressable'

/** Narrower than this and a two-column card is all ellipsis. */
const MIN_COLUMN = 168

const PREVIEW_CARDS = 4

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

/**
 * The host, or the source name when there is no link.
 *
 * Derived here rather than stored — `domain` is deliberately not a field on
 * `Citation` (docs/b4-planner.md). Regex rather than `URL`, which Hermes has
 * only behind a polyfill.
 */
function domainOf(citation: Citation): string {
  if (!citation.url) return citation.source
  const match = /^https?:\/\/([^/]+)/i.exec(citation.url)
  return match ? match[1].replace(/^www\./i, '') : citation.source
}

export function CitationList({ citations }: { citations: Citation[] }) {
  const [width, setWidth] = useState(0)
  const [cardsExpanded, setCardsExpanded] = useState(false)

  const groups = useMemo(() => groupBySource(citations), [citations])

  const totalCards = citations.length
  const visibleIds = useMemo(() => {
    const slice = cardsExpanded ? citations : citations.slice(0, PREVIEW_CARDS)
    return new Set(slice.map((c) => c.id))
  }, [citations, cardsExpanded])

  if (citations.length === 0) return null

  // Measured, not guessed off the window: the answer card is inset by its own
  // padding and by the sidebar, so window width says little about the space here.
  const columns = width >= MIN_COLUMN * 2 + spacing.sm ? 2 : 1
  const cardWidth = columns === 2 ? (width - spacing.sm) / 2 : undefined
  const onLayout = (event: LayoutChangeEvent) => setWidth(event.nativeEvent.layout.width)

  return (
    <View style={styles.list} onLayout={onLayout}>
      {groups.map(([source, items]) => {
        const visible = items.filter((c) => visibleIds.has(c.id))
        if (visible.length === 0) return null
        return (
          <View key={source} style={styles.group}>
            <Text style={styles.groupLabel}>{source}</Text>
            <View style={styles.grid}>
              {visible.map((citation) => (
                <SourceCard key={citation.id} citation={citation} width={cardWidth} />
              ))}
            </View>
          </View>
        )
      })}

      {totalCards > PREVIEW_CARDS ? (
        <Pressable onPress={() => setCardsExpanded((e) => !e)} style={styles.expandBtn}>
          <Text style={styles.expandBtnText}>
            {cardsExpanded ? 'Show less ↑' : `Show all ${totalCards} sources ↓`}
          </Text>
        </Pressable>
      ) : null}
    </View>
  )
}

/**
 * One source, compact enough to sit two abreast.
 *
 * A card with no link opens the preview instead of going nowhere — that is
 * where its snippet lives, and for a course the snippet is the meeting times.
 */
function SourceCard({ citation, width }: { citation: Citation; width: number | undefined }) {
  const { open } = useCitationOverlay()
  const ref = useRef<View>(null)

  const domain = domainOf(citation)
  const initial = (/[a-z0-9]/i.exec(domain)?.[0] ?? '?').toUpperCase()
  // One of the two, not both — the card has room for a stamp, not a history.
  // The full pair is in the preview this expands to. PRD §9 wants freshness
  // surfaced, so a card never hides it entirely.
  const verified = relativeTime(citation.verified_at)
  const indexed = relativeTime(citation.indexed_at)
  const freshness = verified ? `Verified ${verified}` : indexed ? `Indexed ${indexed}` : null

  const press = () => {
    if (citation.url) {
      void Linking.openURL(citation.url).catch(() => {
        // A dead url is the source's problem, not a crash.
      })
      return
    }
    const node = ref.current
    if (!node) {
      open(citation, null, true)
      return
    }
    node.measureInWindow((x, y, w, h) => open(citation, { x, y, width: w, height: h }, true))
  }

  return (
    <HoverPressable
      ref={ref}
      onPress={press}
      accessibilityRole={citation.url ? 'link' : 'button'}
      accessibilityLabel={`${citation.title}, ${domain}`}
      style={({ hovered }) => [styles.card, { width }, hovered && styles.cardHovered]}
    >
      <View style={styles.cardHead}>
        <View style={styles.avatar}>
          <Text style={styles.avatarText}>{initial}</Text>
        </View>
        <Text style={styles.domain} numberOfLines={1}>
          {domain}
        </Text>
      </View>

      <Text style={styles.cardTitle} numberOfLines={2}>
        {citation.title}
      </Text>

      {freshness ? <Text style={styles.cardFreshness}>{freshness}</Text> : null}
    </HoverPressable>
  )
}

const styles = StyleSheet.create({
  list: {
    gap: spacing.sm,
  },
  group: {
    gap: spacing.xs,
  },
  groupLabel: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.6,
    textTransform: 'uppercase',
    color: colors.textFaint,
  },
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  expandBtn: {
    alignSelf: 'center',
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    marginTop: spacing.xs,
  },
  expandBtnText: {
    fontSize: 12,
    color: colors.textMuted,
  },
  card: {
    gap: spacing.xs,
    padding: spacing.md,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    backgroundColor: colors.surface,
  },
  // A 1px lift, instant rather than eased: twenty animation drivers in one
  // answer costs more than the transition is worth at this distance.
  cardHovered: {
    borderColor: colors.border,
    transform: [{ translateY: -1 }],
  },
  cardHead: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs + 2,
  },
  avatar: {
    width: 16,
    height: 16,
    borderRadius: radius.sm - 4,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.sidebarHover,
  },
  avatarText: {
    fontSize: 9,
    fontWeight: '600',
    color: colors.textFaint,
  },
  domain: {
    flexShrink: 1,
    fontSize: 11,
    fontFamily: fonts.mono,
    color: colors.textFaint,
  },
  cardTitle: {
    fontSize: 13,
    lineHeight: 18,
    fontWeight: '500',
    color: colors.text,
  },
  cardFreshness: {
    fontSize: 11,
    color: colors.textFaint,
  },
})
