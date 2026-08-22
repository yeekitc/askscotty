/**
 * Task dependency graph: courses as side-by-side columns, tasks stacked
 * top-to-bottom, bezier/straight edges between them.
 *
 * Green edges + filled source dot when the source task is done.
 * Gray edges + hollow dots when pending.
 */

import { Fragment } from 'react'
import { ScrollView, StyleSheet, Text, View } from 'react-native'
import Svg, { Circle, Path } from 'react-native-svg'

import { colors, radius, spacing } from '../lib/theme'

// Layout constants
const COLUMN_W = 180
const COLUMN_GAP = 44
const NODE_H = 80
const NODE_V_GAP = 20
const HEADER_H = 56
const PADDING = 16
const DOT_R = 6
const EDGE_DONE = '#22863a'

type TaskNode = {
  id: string
  title: string
  due?: string
  done: boolean
}

type Group = {
  id: string
  course: string
  title: string
  nodes: TaskNode[]
}

type Edge = {
  from: string
  to: string
}

type TaskMapData = {
  groups: Group[]
  edges: Edge[]
}

type NodePos = {
  cx: number
  topY: number
  bottomY: number
  done: boolean
  gi: number
}

function colX(gi: number): number {
  return PADDING + gi * (COLUMN_W + COLUMN_GAP)
}

function nodeCx(gi: number): number {
  return colX(gi) + COLUMN_W / 2
}

function nodeTopY(ni: number): number {
  return PADDING + HEADER_H + ni * (NODE_H + NODE_V_GAP)
}

function buildPositions(groups: Group[]): Map<string, NodePos> {
  const map = new Map<string, NodePos>()
  groups.forEach((group, gi) => {
    group.nodes.forEach((node, ni) => {
      const top = nodeTopY(ni)
      map.set(node.id, {
        cx: nodeCx(gi),
        topY: top,
        bottomY: top + NODE_H,
        done: node.done,
        gi,
      })
    })
  })
  return map
}

type NodeCardProps = {
  node: TaskNode
  left: number
  top: number
}

function NodeCard({ node, left, top }: NodeCardProps) {
  const done = node.done
  return (
    <View
      style={[
        styles.card,
        { left, top, width: COLUMN_W, height: NODE_H },
        done && styles.cardDone,
      ]}
    >
      <Text style={styles.cardTitle} numberOfLines={2}>
        {node.title}
      </Text>
      <View style={styles.cardBottom}>
        <Text style={styles.cardDue} numberOfLines={1}>
          {node.due ?? ''}
        </Text>
        <View style={[styles.checkbox, done && styles.checkboxDone]}>
          {done && <Text style={styles.checkmark}>✓</Text>}
        </View>
      </View>
    </View>
  )
}

// The block is model-generated, so a group missing `nodes`, or a bare `null`,
// is an ordinary failure mode rather than a bug. Valid JSON of the wrong shape
// still has to degrade to nothing — throwing here takes the whole answer down.
function parseTaskMap(text: string): TaskMapData | null {
  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return null
  }
  if (!raw || typeof raw !== 'object') return null

  const source = raw as Partial<TaskMapData>
  if (!Array.isArray(source.groups)) return null

  const groups = source.groups
    .filter((group) => !!group && typeof group === 'object')
    .map((group) => ({
      ...group,
      nodes: Array.isArray(group.nodes) ? group.nodes.filter((node) => !!node && !!node.id) : [],
    }))
    .filter((group) => group.nodes.length > 0)

  if (groups.length === 0) return null

  const edges = Array.isArray(source.edges)
    ? source.edges.filter((edge) => !!edge && !!edge.from && !!edge.to)
    : []

  return { groups, edges }
}

export function TaskMap({ text }: { text: string }) {
  const data = parseTaskMap(text)
  if (!data) return null

  const positions = buildPositions(data.groups)

  const maxNodes = Math.max(...data.groups.map((g) => g.nodes.length))
  const canvasWidth =
    PADDING * 2 + data.groups.length * COLUMN_W + Math.max(0, data.groups.length - 1) * COLUMN_GAP
  const canvasHeight =
    PADDING +
    HEADER_H +
    maxNodes * NODE_H +
    Math.max(0, maxNodes - 1) * NODE_V_GAP +
    PADDING

  return (
    <View style={styles.container}>
      <Text style={styles.mapTitle}>Your Task Map</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ width: canvasWidth, height: canvasHeight, position: 'relative' }}>
          {/* Columns: header + node cards — rendered first so SVG dots sit on top of them */}
          {data.groups.map((group, gi) => (
            <Fragment key={group.id}>
              <View
                style={[
                  styles.colHeader,
                  { left: colX(gi), top: PADDING, width: COLUMN_W },
                ]}
              >
                <Text style={styles.courseCode}>{group.course}</Text>
                <Text style={styles.courseTitle} numberOfLines={2}>
                  {group.title}
                </Text>
              </View>
              {group.nodes.map((node, ni) => (
                <NodeCard
                  key={node.id}
                  node={node}
                  left={colX(gi)}
                  top={nodeTopY(ni)}
                />
              ))}
            </Fragment>
          ))}

          {/* SVG edge layer last so dots render on top of card edges */}
          <View pointerEvents="none" style={StyleSheet.absoluteFill}>
            <Svg width={canvasWidth} height={canvasHeight}>
              {data.edges.flatMap((edge, i) => {
                const src = positions.get(edge.from)
                const dst = positions.get(edge.to)
                if (!src || !dst) return []

                const stroke = src.done ? EDGE_DONE : colors.border
                const x1 = src.cx
                const y1 = src.bottomY
                const x2 = dst.cx
                const y2 = dst.topY

                const pathD =
                  src.gi === dst.gi
                    ? `M ${x1},${y1} L ${x2},${y2}`
                    : (() => {
                        const mid = (y1 + y2) / 2
                        return `M ${x1},${y1} C ${x1},${mid} ${x2},${mid} ${x2},${y2}`
                      })()

                return [
                  <Path
                    key={`e${i}`}
                    d={pathD}
                    stroke={stroke}
                    strokeWidth={1.5}
                    fill="none"
                  />,
                  // Source dot (filled)
                  <Circle
                    key={`sd${i}`}
                    cx={x1}
                    cy={y1}
                    r={DOT_R}
                    fill={stroke}
                  />,
                  // Target dot (hollow)
                  <Circle
                    key={`td${i}`}
                    cx={x2}
                    cy={y2}
                    r={DOT_R}
                    fill="white"
                    stroke={stroke}
                    strokeWidth={1.5}
                  />,
                ]
              })}
            </Svg>
          </View>
        </View>
      </ScrollView>
    </View>
  )
}

const styles = StyleSheet.create({
  container: {
    gap: spacing.sm,
  },
  mapTitle: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textMuted,
  },
  colHeader: {
    position: 'absolute',
    height: HEADER_H,
    justifyContent: 'flex-end',
    paddingBottom: spacing.xs,
  },
  courseCode: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.text,
  },
  courseTitle: {
    fontSize: 11,
    color: colors.textMuted,
    lineHeight: 14,
  },
  card: {
    position: 'absolute',
    backgroundColor: 'white',
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.md,
    padding: spacing.sm,
    justifyContent: 'space-between',
  },
  cardDone: {
    borderLeftWidth: 3,
    borderLeftColor: EDGE_DONE,
    backgroundColor: '#f0faf0',
  },
  cardTitle: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.text,
    flexShrink: 1,
  },
  cardBottom: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: spacing.xs,
  },
  cardDue: {
    fontSize: 11,
    color: colors.textMuted,
    flexShrink: 1,
    marginRight: spacing.xs,
  },
  checkbox: {
    width: 18,
    height: 18,
    borderRadius: 4,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxDone: {
    backgroundColor: EDGE_DONE,
    borderColor: EDGE_DONE,
  },
  checkmark: {
    fontSize: 11,
    color: 'white',
    fontWeight: '700',
    lineHeight: 14,
  },
})
