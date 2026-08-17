/**
 * The preview that opens when an inline `[S1]` chip is tapped, and the two
 * contexts the chip needs to do it.
 *
 * **Why the preview lives at screen level.** A chip is a nested `<Text>` deep
 * inside a `FlatList` row. A popup rendered there would be clipped by the row
 * and would scroll away with it, so the card is rendered once at the root and
 * the chip only reports where it is.
 *
 * **Why citations are a second, separate context.** `renderText` receives only
 * its own text part — it cannot see the sibling `source` parts on the same
 * message — so the message supplies them from above instead.
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Pressable, StyleSheet, useWindowDimensions, View } from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { colors, radius, shadows, spacing, WIDE_BREAKPOINT } from '../lib/theme'
import type { Citation } from '../lib/types'
import { CitationCard } from './CitationCard'

/** Where the chip sits in the window, from `measureInWindow`. */
export type Anchor = { x: number; y: number; width: number; height: number }

type Opened = {
  citation: Citation
  /** Null on a phone, where the card is pinned to the bottom and never anchored. */
  anchor: Anchor | null
  /** A tap pins the card open; a hover does not. */
  pinned: boolean
}

type OverlayApi = {
  openId: string | null
  open: (citation: Citation, anchor: Anchor | null, pinned: boolean) => void
  close: () => void
}

const OverlayContext = createContext<OverlayApi | null>(null)

export function useCitationOverlay(): OverlayApi {
  const api = useContext(OverlayContext)
  // Loud rather than inert: without the provider every chip would simply do
  // nothing when pressed, which looks like a broken chip rather than a missing
  // wrapper.
  if (!api) throw new Error('Citation chips need a <CitationProvider> above them')
  return api
}

const MessageCitationsContext = createContext<Citation[]>([])

/** Publishes one message's sources to the chips inside its answer. */
export function MessageCitations({
  citations,
  children,
}: {
  citations: Citation[]
  children: ReactNode
}) {
  return (
    <MessageCitationsContext.Provider value={citations}>{children}</MessageCitationsContext.Provider>
  )
}

export function useMessageCitation(id: string): Citation | null {
  const citations = useContext(MessageCitationsContext)
  return citations.find((citation) => citation.id === id) ?? null
}

/** Widest the card is allowed to get on a large screen. */
const CARD_WIDTH = 320

export function CitationProvider({ children }: { children: ReactNode }) {
  const [opened, setOpened] = useState<Opened | null>(null)
  const { width, height } = useWindowDimensions()
  const insets = useSafeAreaInsets()

  const open = useCallback((citation: Citation, anchor: Anchor | null, pinned: boolean) => {
    setOpened((current) => {
      // A hover must never displace a card the user deliberately opened.
      if (current?.pinned && !pinned) return current
      return { citation, anchor, pinned }
    })
  }, [])

  const close = useCallback(() => setOpened(null), [])

  const api = useMemo<OverlayApi>(
    () => ({ openId: opened?.citation.id ?? null, open, close }),
    [opened, open, close],
  )

  const cardWidth = Math.min(CARD_WIDTH, width - spacing.lg * 2)

  // Anchoring needs room either side of the chip. On a phone there isn't any,
  // so the card pins to the bottom edge instead and the measurement goes unused.
  const placement =
    opened?.anchor && width >= WIDE_BREAKPOINT
      ? {
          width: cardWidth,
          // Centred on the chip, then held clear of both edges.
          left: Math.max(
            spacing.lg,
            Math.min(
              opened.anchor.x + opened.anchor.width / 2 - cardWidth / 2,
              width - cardWidth - spacing.lg,
            ),
          ),
          // Pinning the card's bottom above the chip avoids having to measure
          // the card's own height before placing it.
          bottom: height - opened.anchor.y + spacing.sm,
        }
      : {
          left: spacing.lg,
          right: spacing.lg,
          bottom: insets.bottom + spacing.lg,
        }

  return (
    <OverlayContext.Provider value={api}>
      <View style={styles.root}>
        {children}

        {opened ? (
          <>
            {/* Only a pinned card gets a backdrop. On a hover-opened one it
                would sit over the chip and swallow the hover-out. */}
            {opened.pinned ? (
              <Pressable
                style={StyleSheet.absoluteFill}
                onPress={close}
                accessibilityLabel="Close source preview"
              />
            ) : null}

            <View style={[styles.card, placement]} pointerEvents="box-none">
              <CitationCard citation={opened.citation} />
            </View>
          </>
        ) : null}
      </View>
    </OverlayContext.Provider>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  card: {
    position: 'absolute',
    // Above the sidebar drawer, which is the tallest thing on the screen.
    zIndex: 80,
    backgroundColor: colors.surface,
    borderRadius: radius.lg,
    ...shadows.soft,
  },
})
