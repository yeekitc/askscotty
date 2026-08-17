/**
 * Renders an answer's Markdown as React Native views, revealing it a word at a
 * time while it streams.
 *
 * `assistant-ui`'s markdown support is a separate package (`@assistant-ui/react-markdown`)
 * built on `react-markdown` and Radix — DOM only, so it cannot be used here.
 * `@assistant-ui/react-native` exports no markdown renderer at all; it hands you
 * the raw text and expects you to render it. This is that.
 *
 * Parsing lives in `lib/markdown.ts` and the reveal clock in `lib/reveal.ts`;
 * this file is only layout, so the three can be reasoned about separately.
 *
 * **The seam F2 needs:** every leaf string goes through `renderSpanText`. Inline
 * `[S1]` citation chips slot in there — segment the string, wrap the markers in
 * an inline `<Pressable>`, and leave the prose as plain strings. That is why the
 * spans are rendered as nested `<Text>` runs inside one outermost `<Text>` per
 * block rather than as separate views.
 *
 * **Why word offsets are precomputed.** The reveal needs to know each span's
 * absolute word index. A counter mutated as the tree renders does not work:
 * `BlockView` is a child component, so its body runs after the parent's `.map`
 * has already returned, not during it. Offsets are therefore derived up front
 * and passed down, and only accumulate locally inside a single synchronous map.
 */

import { useMemo } from 'react'
import { Linking, StyleSheet, Text, View } from 'react-native'

import { colors, fonts, radius, spacing } from '../lib/theme'
import { listMarker, parseMarkdown, type Block, type InlineSpan } from '../lib/markdown'
import { FADE_RAMP, FADE_WORDS, splitWords, useBlink, useSmoothReveal } from '../lib/reveal'

/** One span's words. */
type SpanWords = string[]
/** The spans making up one `<Text>` — a paragraph, or a single list item. */
type GroupWords = SpanWords[]
/** A block's groups. Everything but a list has exactly one. */
type BlockWords = GroupWords[]

type Props = {
  text: string
  /** Merged into every block's base text style, so callers keep control of size and colour. */
  style?: React.ComponentProps<typeof Text>['style']
  /** Whether this text is still arriving. Drives the reveal, the fade and the caret. */
  streaming?: boolean
}

/** Layout context every span needs, bundled so it is not eight props deep. */
type Reveal = {
  /** How many words, counted from the start of the answer, are showing. */
  revealed: number
  /** Absolute word index the caret sits at, or null when it is not shown. */
  caret: number | null
  /** Whether the trailing words are still fading up to full colour. */
  fading: boolean
}

function chunkBlock(block: Block): BlockWords {
  switch (block.type) {
    case 'list':
      return block.items.map((item) => item.map((span) => splitWords(span.text)))
    case 'code':
      return [[splitWords(block.text)]]
    default:
      return [block.spans.map((span) => splitWords(span.text))]
  }
}

const countWords = (words: BlockWords) =>
  words.reduce((total, group) => total + group.reduce((sum, span) => sum + span.length, 0), 0)

export function AnswerText({ text, style, streaming = false }: Props) {
  // Memoised because the reveal re-renders every 40ms, and reparsing the whole
  // answer on each tick is the one thing that makes this expensive.
  const blocks = useMemo(() => parseMarkdown(text), [text])
  const chunked = useMemo(() => blocks.map(chunkBlock), [blocks])

  // Prefix sum: the absolute word index each block starts at.
  const starts = useMemo(() => {
    let running = 0
    return chunked.map((words) => {
      const start = running
      running += countWords(words)
      return start
    })
  }, [chunked])

  const total = useMemo(() => chunked.reduce((sum, words) => sum + countWords(words), 0), [chunked])

  const revealed = useSmoothReveal(total, streaming)
  const caretOn = useBlink(streaming)

  const reveal: Reveal = {
    revealed,
    caret: streaming ? revealed : null,
    // Only while the reveal is live. Left on once it settles, the last few words
    // of a finished answer would stay permanently greyed.
    fading: streaming || revealed < total,
  }

  // Nothing parsed (an empty or whitespace-only answer): render the raw string
  // rather than an empty view, so a stray character is visible rather than lost.
  if (blocks.length === 0) {
    return <Text style={[styles.body, style]}>{text}</Text>
  }

  return (
    <View>
      {blocks.map((block, index) => (
        <BlockView
          key={index}
          block={block}
          words={chunked[index]}
          start={starts[index]}
          first={index === 0}
          style={style}
          reveal={reveal}
          caretOn={caretOn}
        />
      ))}
    </View>
  )
}

type BlockProps = {
  block: Block
  words: BlockWords
  start: number
  first: boolean
  style: Props['style']
  reveal: Reveal
  caretOn: boolean
}

function BlockView({ block, words, start, first, style, reveal, caretOn }: BlockProps) {
  const spacer = first ? undefined : styles.spaced

  // A block whose first word has not been reached yet contributes nothing —
  // including its top margin, or an empty gap opens below the answer.
  if (reveal.revealed <= start) return null

  switch (block.type) {
    case 'heading':
      return (
        <Text style={[styles.body, style, styles[`h${block.level}`], spacer]}>
          <Spans
            spans={block.spans}
            words={words[0]}
            start={start}
            reveal={reveal}
            caretOn={caretOn}
          />
        </Text>
      )

    case 'code': {
      const chunks = words[0][0]
      const visible = Math.min(chunks.length, reveal.revealed - start)
      return (
        <View style={[styles.codeBlock, spacer]}>
          <Text style={styles.codeText}>{chunks.slice(0, visible).join('')}</Text>
        </View>
      )
    }

    case 'list': {
      // Each item is its own `<Text>`, so its offset has to be accumulated here
      // rather than inside one map over spans.
      let offset = start
      const items = block.items.map((item, index) => {
        const itemStart = offset
        offset += words[index].reduce((sum, span) => sum + span.length, 0)
        if (reveal.revealed <= itemStart) return null

        return (
          <View key={index} style={styles.listItem}>
            {/* Fixed-width so wrapped lines align under the text, not under
                the bullet. `tabular-nums` keeps "9." and "10." the same width. */}
            <Text style={[styles.body, style, styles.marker]}>{listMarker(block, index)}</Text>
            <Text style={[styles.body, style, styles.listText]}>
              <Spans
                spans={item}
                words={words[index]}
                start={itemStart}
                reveal={reveal}
                caretOn={caretOn}
              />
            </Text>
          </View>
        )
      })

      return <View style={spacer}>{items}</View>
    }

    default:
      return (
        <Text style={[styles.body, style, spacer]}>
          <Spans
            spans={block.spans}
            words={words[0]}
            start={start}
            reveal={reveal}
            caretOn={caretOn}
          />
        </Text>
      )
  }
}

/**
 * Nested `<Text>` runs, not views: only nested Text wraps correctly mid-sentence,
 * and it is what lets an inline citation chip sit in the flow of a paragraph.
 */
function Spans({
  spans,
  words,
  start,
  reveal,
  caretOn,
}: {
  spans: InlineSpan[]
  words: GroupWords
  start: number
  reveal: Reveal
  caretOn: boolean
}) {
  // Safe to accumulate: this map runs to completion inside one render.
  let offset = start

  return (
    <>
      {spans.map((span, index) => {
        const spanStart = offset
        const chunks = words[index]
        offset += chunks.length
        if (reveal.revealed <= spanStart) return null

        return (
          <Text
            key={index}
            style={[
              span.bold && styles.bold,
              span.italic && styles.italic,
              span.code && styles.codeInline,
              span.href && styles.link,
            ]}
            // Nested Text carries no accessible role on its own, and a link the
            // screen reader cannot announce is not a link.
            {...(span.href
              ? {
                  accessibilityRole: 'link' as const,
                  onPress: () => {
                    void Linking.openURL(span.href!).catch(() => {
                      // A malformed href is the model's mistake, not a crash.
                    })
                  },
                }
              : null)}
          >
            {renderSpanText(chunks, spanStart, reveal, caretOn)}
          </Text>
        )
      })}
    </>
  )
}

/**
 * The single place a leaf string becomes renderable content.
 *
 * A seam, deliberately: F2's inline `[S1]` markers are a transform on exactly
 * these words, and having one means citations do not have to touch the block
 * layout above.
 *
 * Words already settled are emitted as one joined string — one text node for the
 * bulk of the answer, with separate nodes only for the handful still fading.
 */
function renderSpanText(
  chunks: string[],
  start: number,
  reveal: Reveal,
  caretOn: boolean,
): React.ReactNode {
  const visible = Math.min(chunks.length, reveal.revealed - start)
  const end = start + chunks.length
  const showCaret =
    reveal.caret !== null && reveal.caret > start && reveal.caret <= end && chunks.length > 0

  // The first index that gets a fade colour. Everything before it is settled.
  const fadeFrom = reveal.fading ? Math.max(0, reveal.revealed - FADE_WORDS - start) : visible
  const settled = chunks.slice(0, Math.min(fadeFrom, visible)).join('')

  const caret = showCaret ? (
    // Kept in the tree unlit rather than removed, so the line does not reflow on
    // every blink.
    <Text style={[styles.caret, !caretOn && styles.caretOff]}>▍</Text>
  ) : null

  if (fadeFrom >= visible) {
    return (
      <>
        {settled}
        {caret}
      </>
    )
  }

  return (
    <>
      {settled}
      {chunks.slice(fadeFrom, visible).map((chunk, index) => {
        const distance = reveal.revealed - 1 - (start + fadeFrom + index)
        return (
          <Text key={index} style={{ color: FADE_RAMP[Math.min(distance, FADE_WORDS - 1)] }}>
            {chunk}
          </Text>
        )
      })}
      {caret}
    </>
  )
}

const styles = StyleSheet.create({
  body: {
    color: colors.text,
    fontSize: 15,
    lineHeight: 22,
  },
  // Between blocks only — the first block sits flush so an answer does not
  // start with a gap.
  spaced: {
    marginTop: spacing.md,
  },
  h1: { fontSize: 19, fontWeight: '600', lineHeight: 26 },
  h2: { fontSize: 17, fontWeight: '600', lineHeight: 24 },
  h3: { fontSize: 15, fontWeight: '600', lineHeight: 22 },
  bold: { fontWeight: '600' },
  italic: { fontStyle: 'italic' },
  link: {
    color: colors.textMuted,
    textDecorationLine: 'underline',
  },
  caret: {
    color: colors.textFaint,
  },
  caretOff: {
    color: 'transparent',
  },
  listItem: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    marginBottom: spacing.xs,
  },
  // minWidth rather than width, plus a margin: a bullet and "10." are very
  // different widths, and a fixed column either crowds the number or strands
  // the bullet. Either way every line in one list shares an indent, which is
  // what makes a wrapped item align under its own text.
  marker: {
    minWidth: 14,
    marginRight: spacing.sm,
    fontVariant: ['tabular-nums'],
    color: colors.textMuted,
  },
  // flexShrink, not flex: 1 — on Android a flexed Text in a row can collapse to
  // zero width instead of wrapping.
  listText: {
    flexShrink: 1,
  },
  codeInline: {
    fontFamily: fonts.mono,
    fontSize: 13,
    color: colors.textMuted,
  },
  codeBlock: {
    backgroundColor: colors.sidebarHover,
    borderRadius: radius.sm,
    padding: spacing.md,
  },
  codeText: {
    fontFamily: fonts.mono,
    fontSize: 13,
    lineHeight: 19,
    color: colors.text,
  },
})
