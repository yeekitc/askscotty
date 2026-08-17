/**
 * Inline `[S1]` markers: finding them in an answer, and pairing each one with
 * the word it cites.
 *
 * Kept out of `lib/markdown.ts` deliberately — that file is a markdown parser
 * and says so. A citation marker is not markdown syntax, it is our own
 * convention, and the two have different rules about what may be dropped.
 *
 * **Markers only ever render on a finished answer.** While one streams the
 * adapter strips them (`provisional` in `lib/assistantAdapter.ts`), and that is
 * not only cosmetic: source parts arrive with the final `done` event, so a chip
 * shown mid-stream would have nothing to resolve against. The backend has also
 * not yet had a chance to strip ids it never issued, so a marker seen early can
 * still turn out to be invented.
 */

import { splitWords } from './reveal'

/**
 * One id per bracket. `validate_markers` (apps/planner/citations.py) rewrites a
 * multi-id marker into adjacent single-id ones, so the wide pattern the adapter
 * needs mid-stream is not needed here.
 */
const MARKER = /\[S(\d+)\]/g

type Segment = { type: 'text'; text: string } | { type: 'marker'; id: string }

function segmentMarkers(text: string): Segment[] {
  const segments: Segment[] = []
  let last = 0

  MARKER.lastIndex = 0
  let match: RegExpExecArray | null
  while ((match = MARKER.exec(text)) !== null) {
    if (match.index > last) segments.push({ type: 'text', text: text.slice(last, match.index) })
    segments.push({ type: 'marker', id: `S${match[1]}` })
    last = match.index + match[0].length
  }
  if (last < text.length) segments.push({ type: 'text', text: text.slice(last) })

  return segments
}

/** A word of prose, plus any citation markers that immediately followed it. */
export type Word = { text: string; markers: string[] }

/**
 * Leaf string → the words the reveal counts.
 *
 * A marker rides along with the word before it rather than occupying a slot of
 * its own. Two reasons: a citation should never appear a tick ahead of the
 * claim it supports, and counting it as a word would make the chip look like it
 * was being typed out.
 */
export function toWords(text: string): Word[] {
  const words: Word[] = []

  for (const segment of segmentMarkers(text)) {
    if (segment.type === 'marker') {
      // A marker opening the string has nothing to attach to. Rare enough that
      // an empty carrier word is cheaper than a special case downstream.
      if (words.length === 0) words.push({ text: '', markers: [] })
      words[words.length - 1].markers.push(segment.id)
      continue
    }

    for (const chunk of splitWords(segment.text)) words.push({ text: chunk, markers: [] })
  }

  return words
}
