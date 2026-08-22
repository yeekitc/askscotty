import { useState } from 'react'
import { Linking, Pressable, StyleSheet, Text, View } from 'react-native'

import { colors, radius, spacing } from '../lib/theme'

type Event = {
  title: string
  start: string
  end: string
  location: string
  org: string
  link: string
}

// Event fields come from a model-generated block, so a missing or non-string
// date is an ordinary case. Coerce once here so the matchers below cannot throw.
function asText(s: unknown): string {
  return typeof s === 'string' ? s : ''
}

// "Mon, Nov 14, 2026 9:00 AM" → "Nov 14"
function shortDate(s: unknown): string {
  const m = asText(s).match(/,\s+(\w+ \d+),/)
  return m ? m[1] : ''
}

// Returns "Nov 14" for same-day, "Nov 14–15" for same-month, "Nov 14 – Dec 2" cross-month
function shortDateRange(start: unknown, end: unknown): string {
  const sd = shortDate(start)
  const ed = shortDate(end)
  if (!sd || !ed || sd === ed) return sd

  const [startMonth] = sd.split(' ')
  const [endMonth, endDay] = ed.split(' ')
  if (startMonth === endMonth) return `${sd}–${endDay}`
  return `${sd} – ${ed}`
}

// "Mon, Nov 14, 2026 9:00 AM" → "MON"
function dayAbbr(s: unknown): string {
  const m = asText(s).match(/^(\w{3})/)
  return m ? m[1].toUpperCase() : ''
}

// "Mon, Nov 14, 2026 9:00 AM" → "11/14"
function shortDateNum(s: unknown): string {
  const m = asText(s).match(/,\s+(\w+)\s+(\d+),/)
  if (!m) return ''
  const months: Record<string, string> = {
    Jan: '1', Feb: '2', Mar: '3', Apr: '4', May: '5', Jun: '6',
    Jul: '7', Aug: '8', Sep: '9', Oct: '10', Nov: '11', Dec: '12',
  }
  return `${months[m[1]] ?? '?'}/${m[2]}`
}

// "Mon, Nov 14, 2026 9:00 AM" → "9:00 AM"
function extractTime(s: unknown): string {
  const m = asText(s).match(/\d{4}\s+(\d+:\d+\s+[AP]M)/)
  return m ? m[1] : ''
}

// "9:00 AM – 5:00 PM", or "" when no time present
function timeRange(start: unknown, end: unknown): string {
  const t1 = extractTime(start)
  const t2 = extractTime(end)
  if (!t1) return ''
  if (!t2 || t1 === t2) return t1
  return `${t1} – ${t2}`
}

function EventRow({ event, viewMode }: { event: Event; viewMode: 'list' | 'grid' }) {
  const dateRange = shortDateRange(event.start, event.end)
  const day = dayAbbr(event.start)
  const dateNum = shortDateNum(event.start)
  const time = timeRange(event.start, event.end)
  const org = event.org || ''

  if (viewMode === 'list') {
    return (
      <Pressable
        style={styles.listRow}
        onPress={event.link ? () => { void Linking.openURL(event.link).catch(() => {}) } : undefined}
      >
        <Text style={styles.listDateLabel}>{dateRange}</Text>
        <View style={styles.listMiddle}>
          <Text style={styles.listTitle} numberOfLines={1}>{event.title}</Text>
          {event.location ? (
            <Text style={styles.listLocation} numberOfLines={1}>{event.location}</Text>
          ) : null}
        </View>
        <View style={styles.listRight}>
          <Text style={styles.listDesc} numberOfLines={3}>{org}</Text>
        </View>
      </Pressable>
    )
  }

  return (
    <View style={styles.gridCard}>
      <View style={styles.gridLeft}>
        <Text style={styles.dayAbbr}>{day}</Text>
        <Text style={styles.dateNum}>{dateNum}</Text>
        {time ? <Text style={styles.timeText}>{time}</Text> : null}
      </View>
      <View style={styles.verticalRule} />
      <View style={styles.gridRight}>
        <Text style={styles.gridTitle}>{event.title}</Text>
        {event.location ? (
          <Text style={styles.gridLocation}>📍 {event.location}</Text>
        ) : null}
        {org ? (
          <Text style={styles.gridDesc} numberOfLines={3}>{org}</Text>
        ) : null}
        {event.link ? (
          <Text
            style={styles.link}
            onPress={() => { void Linking.openURL(event.link).catch(() => {}) }}
          >
            RSVP →
          </Text>
        ) : null}
      </View>
    </View>
  )
}

const LIMIT = 5

export function EventList({ text, viewMode }: { text: string; viewMode: 'list' | 'grid' }) {
  const [showAll, setShowAll] = useState(false)

  let events: Event[] | null = null
  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) {
      const rows = parsed.filter((event) => !!event && typeof event === 'object')
      if (rows.length > 0) events = rows as Event[]
    }
  } catch {
    return null
  }
  if (!events) return null

  const visible = showAll ? events : events.slice(0, LIMIT)
  const hasMore = events.length > LIMIT
  const remaining = events.length - LIMIT

  if (viewMode === 'grid') {
    return (
      <View>
        <View style={styles.gridContainer}>
          {visible.map((event, index) => (
            <EventRow key={index} event={event} viewMode="grid" />
          ))}
        </View>
        {hasMore && (
          <Pressable style={styles.showMore} onPress={() => setShowAll((v) => !v)}>
            <Text style={styles.showMoreText}>
              {showAll ? 'Show less ↑' : `Show ${remaining} more ↓`}
            </Text>
          </Pressable>
        )}
      </View>
    )
  }

  return (
    <View style={styles.container}>
      {visible.map((event, index) => (
        <View key={index}>
          <EventRow event={event} viewMode="list" />
          {index < visible.length - 1 && <View style={styles.divider} />}
        </View>
      ))}
      {hasMore && (
        <>
          <View style={styles.divider} />
          <Pressable style={styles.showMore} onPress={() => setShowAll((v) => !v)}>
            <Text style={styles.showMoreText}>
              {showAll ? 'Show less ↑' : `Show ${remaining} more ↓`}
            </Text>
          </Pressable>
        </>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    overflow: 'hidden',
  },
  divider: {
    height: 1,
    backgroundColor: colors.borderSoft,
    marginHorizontal: spacing.md,
  },
  // List view
  listRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  listDateLabel: {
    width: 64,
    flexShrink: 0,
    fontSize: 13,
    color: colors.textMuted,
    paddingTop: 1,
  },
  listMiddle: {
    flex: 1.2,
  },
  listTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  listLocation: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 1,
  },
  listRight: {
    flex: 1,
  },
  listDesc: {
    fontSize: 12,
    color: colors.textFaint,
    lineHeight: 17,
  },
  // Grid view
  gridContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  gridCard: {
    flexDirection: 'row',
    width: '48.5%',
    backgroundColor: colors.surface,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.md,
    overflow: 'hidden',
  },
  gridLeft: {
    width: 56,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.xs,
  },
  dayAbbr: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.textMuted,
    letterSpacing: 0.5,
  },
  dateNum: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 1,
  },
  timeText: {
    fontSize: 11,
    color: colors.textFaint,
    marginTop: 2,
    textAlign: 'center',
  },
  verticalRule: {
    width: 1,
    alignSelf: 'stretch',
    backgroundColor: colors.borderSoft,
  },
  gridRight: {
    flex: 1,
    padding: spacing.sm,
  },
  gridTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  gridLocation: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  gridDesc: {
    fontSize: 13,
    color: colors.textFaint,
    lineHeight: 18,
    marginTop: spacing.xs,
  },
  link: {
    fontSize: 12,
    color: colors.textMuted,
    textDecorationLine: 'underline',
    marginTop: spacing.xs,
  },
  showMore: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: 'center',
  },
  showMoreText: {
    fontSize: 13,
    color: colors.textMuted,
  },
})
