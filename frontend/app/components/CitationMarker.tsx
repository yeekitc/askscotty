/**
 * One inline `[S1]` marker, rendered as a numbered chip in the flow of a
 * sentence.
 *
 * **It is a `Pressable`, not a styled `<Text>`.** A nested `<Text>` cannot carry
 * its own background box or press target, so a chip built from one is just
 * tinted prose. The cost is that a `View` inside a `<Text>` needs an explicit
 * width and height on Android, and must be a direct child of the outermost
 * `<Text>` — which is why `AnswerText` renders spans as nested runs rather than
 * as separate views.
 *
 * The vertical nudge is unverified on a physical Android device (see the open
 * smoke-test in docs/b4-planner.md); it is correct on iOS and web.
 */

import { useRef } from 'react'
import { Pressable, StyleSheet, Text, View } from 'react-native'

import { colors, fonts, radius } from '../lib/theme'
import { useCitationOverlay, useMessageCitation } from './CitationOverlay'

export function CitationMarker({ id }: { id: string }) {
  const citation = useMessageCitation(id)
  const { openId, open, close } = useCitationOverlay()
  const ref = useRef<View>(null)

  // An id with no matching source is a dead marker. `validate_markers` strips
  // those server-side, so reaching here means something upstream changed —
  // showing nothing is better than a chip that opens an empty card.
  if (!citation) return null

  const isOpen = openId === citation.id
  const number = citation.id.replace(/^S/, '')

  const reveal = (pinned: boolean) => {
    const node = ref.current
    if (!node) {
      open(citation, null, pinned)
      return
    }
    node.measureInWindow((x, y, width, height) => open(citation, { x, y, width, height }, pinned))
  }

  return (
    <Pressable
      ref={ref}
      onPress={() => (isOpen ? close() : reveal(true))}
      // Ignored on native, so they need no platform guard.
      onHoverIn={() => reveal(false)}
      onHoverOut={() => {
        if (!isOpen) close()
      }}
      hitSlop={6}
      style={[styles.chip, isOpen && styles.chipOpen]}
      accessibilityRole="button"
      accessibilityLabel={`Source ${number}: ${citation.title}`}
    >
      <Text style={styles.number}>{number}</Text>
    </Pressable>
  )
}

const styles = StyleSheet.create({
  chip: {
    // Explicit, not intrinsic: Android lays a View out as a zero-sized box
    // inside a <Text> otherwise.
    width: 17,
    height: 17,
    marginLeft: 1,
    marginRight: 2,
    borderRadius: radius.sm - 3,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    backgroundColor: colors.sidebarHover,
    alignItems: 'center',
    justifyContent: 'center',
    // Without this the chip hangs off the baseline and reads as a dropped
    // character rather than a reference.
    transform: [{ translateY: -2 }],
  },
  chipOpen: {
    borderColor: colors.border,
    backgroundColor: colors.background,
  },
  number: {
    fontFamily: fonts.mono,
    fontSize: 10,
    lineHeight: 12,
    color: colors.textMuted,
  },
})
