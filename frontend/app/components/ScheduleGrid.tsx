import { useState } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'
import { colors, radius, spacing } from '../lib/theme'

type CourseSlot = {
  course: string
  title: string
  days: string[]
  begin: string
  end: string
  room: string
}

const DAY_CODES = ['M', 'T', 'W', 'R', 'F']
const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']

const TIME_START = 8    // 8 AM
const TIME_END = 22     // 10 PM
const HOUR_HEIGHT = 56
const TIME_LABEL_WIDTH = 44
const BLOCK_GAP = 4

const COURSE_COLORS = [
  colors.accent,
  '#1a5276',
  '#1e8449',
  '#7d3c98',
  '#b7950b',
  '#922b21',
]

function toMinutes(t: string): number {
  const match = t.trim().match(/^(\d{1,2}):(\d{2})\s*(AM|PM)$/i)
  if (!match) return 0
  let hours = parseInt(match[1], 10)
  const minutes = parseInt(match[2], 10)
  const meridiem = match[3].toUpperCase()
  if (meridiem === 'PM' && hours !== 12) hours += 12
  if (meridiem === 'AM' && hours === 12) hours = 0
  return hours * 60 + minutes
}

export function ScheduleGrid({ text }: { text: string }) {
  const [gridWidth, setGridWidth] = useState(0)

  let slots: CourseSlot[] = []
  try {
    slots = JSON.parse(text)
  } catch {
    return null
  }
  if (!Array.isArray(slots) || slots.length === 0) return null

  const gridHeight = (TIME_END - TIME_START) * HOUR_HEIGHT
  const hours = Array.from({ length: TIME_END - TIME_START + 1 }, (_, i) => TIME_START + i)
  const numDays = DAY_CODES.length
  const colWidth = gridWidth > 0 ? (gridWidth - TIME_LABEL_WIDTH) / numDays : 0

  return (
    <View style={styles.container}>
      {/* Day header row */}
      <View style={styles.headerRow}>
        <View style={{ width: TIME_LABEL_WIDTH }} />
        {DAY_CODES.map((_, i) => (
          <View key={i} style={styles.dayHeader}>
            <Text style={styles.dayLabel}>{DAY_NAMES[i]}</Text>
          </View>
        ))}
      </View>

      <ScrollView style={styles.scrollArea} showsVerticalScrollIndicator={false}>
        <View
          style={[styles.gridBody, { height: gridHeight }]}
          onLayout={(e) => setGridWidth(e.nativeEvent.layout.width)}
        >
          {/* Hour labels + horizontal rules */}
          {hours.map((h, i) => {
            const label = h === 12 ? '12 PM' : h < 12 ? `${h} AM` : `${h - 12} PM`
            return (
              <View key={h} style={[styles.hourRow, { top: i * HOUR_HEIGHT }]}>
                <Text style={styles.hourLabel}>{label}</Text>
                <View style={styles.hourLine} />
              </View>
            )
          })}

          {/* Course blocks */}
          {colWidth > 0 &&
            slots.map((slot, slotIndex) => {
              const color = COURSE_COLORS[slotIndex % COURSE_COLORS.length]
              const startMin = toMinutes(slot.begin)
              const endMin = toMinutes(slot.end)
              const blockTop = ((startMin - TIME_START * 60) / 60) * HOUR_HEIGHT
              const blockHeight = Math.max(((endMin - startMin) / 60) * HOUR_HEIGHT - 2, 18)

              return slot.days.map((day) => {
                const dayIndex = DAY_CODES.indexOf(day)
                if (dayIndex < 0) return null
                const blockLeft = TIME_LABEL_WIDTH + dayIndex * colWidth

                return (
                  <View
                    key={`${slot.course}-${day}`}
                    style={[
                      styles.block,
                      {
                        backgroundColor: color,
                        top: blockTop,
                        height: blockHeight,
                        left: blockLeft,
                        width: colWidth - BLOCK_GAP,
                      },
                    ]}
                  >
                    <Text style={styles.blockCourse} numberOfLines={1}>
                      {slot.course}
                    </Text>
                    {blockHeight > 30 && (
                      <Text style={styles.blockRoom} numberOfLines={1}>
                        {slot.room}
                      </Text>
                    )}
                  </View>
                )
              })
            })}
        </View>
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.md,
    backgroundColor: colors.surface,
    overflow: 'hidden',
  },
  headerRow: {
    flexDirection: 'row',
    borderBottomWidth: 1,
    borderBottomColor: colors.borderSoft,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  dayHeader: {
    flex: 1,
    alignItems: 'center',
  },
  dayLabel: {
    fontSize: 11,
    fontWeight: '600',
    color: colors.textMuted,
    textTransform: 'uppercase',
  },
  scrollArea: {
    maxHeight: 420,
  },
  gridBody: {
    position: 'relative',
    marginHorizontal: spacing.xs,
  },
  hourRow: {
    position: 'absolute',
    left: 0,
    right: 0,
    flexDirection: 'row',
    alignItems: 'center',
  },
  hourLabel: {
    width: TIME_LABEL_WIDTH,
    fontSize: 10,
    color: colors.textFaint,
    textAlign: 'right',
    paddingRight: spacing.sm,
  },
  hourLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.borderSoft,
    opacity: 0.6,
  },
  block: {
    position: 'absolute',
    borderRadius: radius.sm,
    paddingHorizontal: spacing.xs,
    paddingVertical: 2,
    overflow: 'hidden',
  },
  blockCourse: {
    fontSize: 10,
    fontWeight: '700',
    color: '#ffffff',
  },
  blockRoom: {
    fontSize: 9,
    color: 'rgba(255,255,255,0.8)',
    marginTop: 1,
  },
})
