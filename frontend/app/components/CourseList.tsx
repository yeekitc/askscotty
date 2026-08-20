import { useState } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { colors, radius, spacing } from '../lib/theme'

type Course = {
  course_number: string
  title: string
  units: number | null
  description: string
  prereqs: string
}

function CourseCard({ course }: { course: Course }) {
  const [expanded, setExpanded] = useState(false)

  return (
    <View style={styles.cardRow}>
      <View style={styles.card}>
        <Text style={styles.courseNum}>{course.course_number}</Text>
        <Text style={styles.title}>{course.title}</Text>
        {course.units !== null && (
          <Text style={styles.units}>{course.units} units</Text>
        )}
        {expanded && <Text style={styles.desc}>{course.description}</Text>}
        {expanded && course.prereqs !== '' && (
          <Text style={styles.prereqText}>Prereqs: {course.prereqs}</Text>
        )}
        <Pressable onPress={() => setExpanded((v) => !v)} style={styles.collapseBtn}>
          <Text style={styles.collapseBtnText}>{expanded ? 'COLLAPSE' : 'EXPAND'}</Text>
          <Text style={styles.collapseBtnText}>{expanded ? '∧' : '∨'}</Text>
        </Pressable>
      </View>
    </View>
  )
}

export function CourseList({ text, viewMode }: { text: string; viewMode: 'list' | 'grid' }) {
  let courses: Course[]
  try {
    courses = JSON.parse(text)
  } catch {
    return null
  }
  if (!Array.isArray(courses) || courses.length === 0) return null

  if (viewMode === 'list') {
    return (
      <View style={styles.listContainer}>
        {courses.map((c, i) => (
          <View key={i}>
            <View style={styles.listRow}>
              <Text style={styles.listCourseNum}>{c.course_number}</Text>
              <Text style={styles.listTitle} numberOfLines={2}>{c.title}</Text>
              <Text style={styles.listUnits}>{c.units != null ? `${c.units}u` : ''}</Text>
            </View>
            {i < courses.length - 1 && <View style={styles.divider} />}
          </View>
        ))}
      </View>
    )
  }

  return (
    <View style={styles.list}>
      {courses.map((c, i) => (
        <CourseCard key={i} course={c} />
      ))}
    </View>
  )
}

const styles = StyleSheet.create({
  // Grid view
  list: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: spacing.md,
  },
  cardRow: {
    flexDirection: 'column',
    alignItems: 'flex-start',
    width: 260,
  },
  card: {
    backgroundColor: 'white',
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.md,
    borderLeftWidth: 4,
    borderLeftColor: colors.accent,
    padding: spacing.md,
    flex: 1,
  },
  courseNum: {
    fontSize: 13,
    color: colors.textMuted,
  },
  title: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
    marginTop: 2,
  },
  units: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 4,
  },
  desc: {
    fontSize: 14,
    color: colors.text,
    lineHeight: 20,
    marginTop: spacing.sm,
  },
  prereqText: {
    fontSize: 13,
    color: colors.text,
    marginTop: spacing.sm,
  },
  collapseBtn: {
    alignSelf: 'center',
    marginTop: spacing.sm,
    flexDirection: 'row',
    gap: 4,
  },
  collapseBtnText: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.textFaint,
    letterSpacing: 1,
  },
  // List view
  listContainer: {
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    overflow: 'hidden',
  },
  listRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    gap: spacing.sm,
  },
  listCourseNum: {
    width: 80,
    fontSize: 13,
    color: colors.textMuted,
    flexShrink: 0,
  },
  listTitle: {
    flex: 1,
    fontSize: 14,
    fontWeight: '600',
    color: colors.text,
  },
  listUnits: {
    width: 40,
    fontSize: 13,
    color: colors.textMuted,
    textAlign: 'right',
  },
  divider: {
    height: 1,
    backgroundColor: colors.borderSoft,
    marginHorizontal: spacing.md,
  },
})
