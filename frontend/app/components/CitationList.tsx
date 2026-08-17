/**
 * An answer's sources: a pill that opens into a grid of cards.
 *
 * Ported from assistant-ui's `sources` element, which is DOM and cannot be
 * installed — a count badge on a pill trigger, a chevron that turns 180°, and a
 * two-column grid of compact cards with a letter avatar and a monospace domain.
 *
 * **Folded, once the answer carries inline chips.** A tool issues a citation per
 * row it returns — one course search can issue twenty — and a wall of cards
 * under an answer whose every claim already links to its source is the same job
 * done twice, worse. Collapsed, the row still names the count and where the
 * sources came from, so provenance is legible without being exhaustive.
 *
 * **It only folds when there is something to fold behind.** An answer with no
 * markers — the setting off, or a model that wrote none — has no inline route
 * to a source, so the list stays open. PRD §9's freshness is then a tap away
 * rather than on screen, which is the deviation this makes knowingly.
 *
 * Grouping is what makes the mix legible: "CMU Courses API" and "CMU Eats" are
 * live structured lookups, the campus index is a crawl from some days ago, and
 * the open web is neither. Run together as one list they read as equally
 * authoritative, which is the impression PRD §9 exists to prevent.
 *
 * Rendered here rather than through `Message.Content`'s `renderSource` slot,
 * which emits each source where it appears in the part list and so cannot group
 * them.
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { Linking, StyleSheet, Text, View, type LayoutChangeEvent } from 'react-native'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'

import { citedIds, relativeTime } from '../lib/citations'
import { durations, easing, useReducedMotion } from '../lib/motion'
import { colors, fonts, radius, spacing } from '../lib/theme'
import type { Citation } from '../lib/types'
import { useCitationOverlay } from './CitationOverlay'
import { HoverPressable } from './HoverPressable'

/** Narrower than this and a two-column card is all ellipsis. */
const MIN_COLUMN = 168

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

export function CitationList({ citations, answer }: { citations: Citation[]; answer: string }) {
  // Null until the reader says otherwise, so the default can still change under
  // it: a message is rendered before its sources arrive, and `hasChips` only
  // becomes true when they do.
  const [override, setOverride] = useState<boolean | null>(null)
  const [width, setWidth] = useState(0)
  const reduceMotion = useReducedMotion()

  const groups = useMemo(() => groupBySource(citations), [citations])

  // Whether any chip in the prose actually resolves to one of these. Not just
  // "are there markers" — a marker for an id we do not hold renders nothing,
  // and folding behind a chip that never drew would hide the sources outright.
  const hasChips = useMemo(() => {
    const cited = citedIds(answer)
    return citations.some((citation) => cited.has(citation.id))
  }, [citations, answer])

  const open = override ?? !hasChips

  const turn = useSharedValue(open ? 1 : 0)
  useEffect(() => {
    turn.value = reduceMotion
      ? open
        ? 1
        : 0
      : withTiming(open ? 1 : 0, { duration: durations.base, easing })
  }, [open, reduceMotion, turn])

  const caretStyle = useAnimatedStyle(() => ({
    transform: [{ rotate: `${turn.value * 180}deg` }],
  }))

  if (citations.length === 0) return null

  // Measured, not guessed off the window: the answer card is inset by its own
  // padding and by the sidebar, so window width says little about the space here.
  const columns = width >= MIN_COLUMN * 2 + spacing.sm ? 2 : 1
  const cardWidth = columns === 2 ? (width - spacing.sm) / 2 : undefined
  const onLayout = (event: LayoutChangeEvent) => setWidth(event.nativeEvent.layout.width)

  return (
    <View style={styles.list} onLayout={onLayout}>
      <HoverPressable
        onPress={() => setOverride(!open)}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        accessibilityLabel={open ? 'Hide sources' : 'Show sources'}
        hitSlop={8}
        style={styles.trigger}
      >
        {({ hovered }) => (
          <>
            <Text style={[styles.triggerLabel, hovered && styles.triggerHovered]}>Sources</Text>
            <Text style={styles.count}>{citations.length}</Text>
            {/* Named, not just counted: "20" says nothing about whether to
                trust them, "CMU Courses API" does. */}
            <Text
              style={[styles.triggerLabel, styles.origins, hovered && styles.triggerHovered]}
              numberOfLines={1}
            >
              {groups.map(([source]) => source).join(', ')}
            </Text>
            <Animated.View style={caretStyle}>
              <Text style={styles.caret}>▾</Text>
            </Animated.View>
          </>
        )}
      </HoverPressable>

      {open
        ? groups.map(([source, items]) => (
            <View key={source} style={styles.group}>
              <Text style={styles.groupLabel}>{source}</Text>
              <View style={styles.grid}>
                {items.map((citation) => (
                  <SourceCard key={citation.id} citation={citation} width={cardWidth} />
                ))}
              </View>
            </View>
          ))
        : null}
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
  trigger: {
    alignSelf: 'flex-start',
    maxWidth: '100%',
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.xs + 2,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs + 2,
    borderRadius: radius.pill,
    borderWidth: 1,
    borderColor: colors.borderSoft,
  },
  triggerLabel: {
    fontSize: 12,
    color: colors.textMuted,
  },
  triggerHovered: {
    color: colors.text,
  },
  // Shrinks before the label does, so "Sources 20" survives a narrow card.
  origins: {
    flexShrink: 1,
    color: colors.textFaint,
  },
  count: {
    fontSize: 12,
    fontFamily: fonts.mono,
    fontVariant: ['tabular-nums'],
    color: colors.textFaint,
  },
  caret: {
    fontSize: 9,
    color: colors.textFaint,
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
