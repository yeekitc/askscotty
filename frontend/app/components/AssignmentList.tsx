import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'
import { colors, radius, spacing } from '../lib/theme'

type Assignment = {
  title: string
  course: string
  due_date: string | null
  due_time: string | null
  submitted: boolean | null
}

const PAGE_SIZE = 6

export function AssignmentList({ text }: { text: string }) {
  const [page, setPage] = useState(0)

  let items: Assignment[] = []
  try {
    items = JSON.parse(text)
  } catch {
    return null
  }
  if (!Array.isArray(items) || items.length === 0) return null

  const totalPages = Math.ceil(items.length / PAGE_SIZE)
  const visibleItems = items.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)

  return (
    <View>
      <View style={styles.grid}>
      {visibleItems.map((item, i) => (
        <View key={i} style={styles.card}>
          <View style={styles.dateCol}>
            <Text style={styles.dateDay}>{item.due_date ?? '—'}</Text>
            {item.due_time ? <Text style={styles.dateTime}>{item.due_time}</Text> : null}
          </View>
          <View style={styles.nameCol}>
            <Text style={styles.title} numberOfLines={2}>{item.title}</Text>
            <Text style={styles.course} numberOfLines={1}>{item.course}</Text>
          </View>
          <View style={styles.checkCol}>
            <View style={[styles.checkbox, item.submitted === true && styles.checkboxDone]}>
              {item.submitted === true && (
                <Text style={styles.checkmark}>✓</Text>
              )}
            </View>
          </View>
        </View>
      ))}
      </View>
      {totalPages > 1 && (
        <View style={styles.pager}>
          <Pressable
            onPress={() => setPage(p => p - 1)}
            disabled={page === 0}
            style={styles.pageBtn}
          >
            <Text style={[styles.pageBtnText, page === 0 && styles.pageBtnDisabled]}>‹</Text>
          </Pressable>
          <Text style={styles.pageLabel}>{page + 1} / {totalPages}</Text>
          <Pressable
            onPress={() => setPage(p => p + 1)}
            disabled={page === totalPages - 1}
            style={styles.pageBtn}
          >
            <Text style={[styles.pageBtnText, page === totalPages - 1 && styles.pageBtnDisabled]}>›</Text>
          </Pressable>
        </View>
      )}
    </View>
  )
}

const styles = StyleSheet.create({
  grid: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.sm,
  },
  card: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    padding: spacing.md,
    // Two columns: slightly less than half width accounting for the gap.
    width: '48.5%',
  },
  dateCol: {
    alignItems: 'center',
    minWidth: 36,
  },
  dateDay: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
  },
  dateTime: {
    fontSize: 11,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: 2,
  },
  nameCol: {
    flex: 1,
  },
  title: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text,
  },
  course: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 2,
  },
  checkCol: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkbox: {
    width: 18,
    height: 18,
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: 3,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxDone: {
    backgroundColor: colors.accent,
    borderColor: colors.accent,
  },
  checkmark: {
    fontSize: 12,
    color: colors.accentText,
    lineHeight: 14,
  },
  pager: {
    flexDirection: 'row',
    justifyContent: 'center',
    alignItems: 'center',
    marginTop: spacing.sm,
    gap: spacing.md,
  },
  pageBtn: {
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.xs,
  },
  pageBtnText: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
  },
  pageBtnDisabled: {
    color: colors.textFaint,
  },
  pageLabel: {
    fontSize: 13,
    color: colors.textMuted,
  },
})
