/**
 * Renders an answer's Markdown as React Native views.
 *
 * `assistant-ui`'s markdown support is a separate package (`@assistant-ui/react-markdown`)
 * built on `react-markdown` and Radix — DOM only, so it cannot be used here.
 * `@assistant-ui/react-native` exports no markdown renderer at all; it hands you
 * the raw text and expects you to render it. This is that.
 *
 * Parsing lives in `lib/markdown.ts`; this file is only layout, so the two can
 * be reasoned about separately.
 *
 * **The seam F2 needs:** every leaf string goes through `renderSpanText`. Inline
 * `[S1]` citation chips slot in there — segment the string, wrap the markers in
 * an inline `<Pressable>`, and leave the prose as plain strings. That is why the
 * spans are rendered as nested `<Text>` runs inside one outermost `<Text>` per
 * block rather than as separate views.
 */

import { Linking, StyleSheet, Text, View } from 'react-native'

import { colors, fonts, radius, spacing } from '../lib/theme'
import { listMarker, parseMarkdown, type Block, type InlineSpan } from '../lib/markdown'

type Props = {
  text: string
  /** Merged into every block's base text style, so callers keep control of size and colour. */
  style?: React.ComponentProps<typeof Text>['style']
}

export function AnswerText({ text, style }: Props) {
  const blocks = parseMarkdown(text)

  // Nothing parsed (an empty or whitespace-only answer): render the raw string
  // rather than an empty view, so a stray character is visible rather than lost.
  if (blocks.length === 0) {
    return <Text style={[styles.body, style]}>{text}</Text>
  }

  return (
    <View>
      {blocks.map((block, index) => (
        <BlockView key={index} block={block} first={index === 0} style={style} />
      ))}
    </View>
  )
}

function BlockView({ block, first, style }: { block: Block; first: boolean; style: Props['style'] }) {
  const spacer = first ? undefined : styles.spaced

  switch (block.type) {
    case 'heading':
      return (
        <Text style={[styles.body, style, styles[`h${block.level}`], spacer]}>
          <Spans spans={block.spans} />
        </Text>
      )

    case 'code':
      return (
        <View style={[styles.codeBlock, spacer]}>
          <Text style={styles.codeText}>{block.text}</Text>
        </View>
      )

    case 'list':
      return (
        <View style={spacer}>
          {block.items.map((item, index) => (
            <View key={index} style={styles.listItem}>
              {/* Fixed-width so wrapped lines align under the text, not under
                  the bullet. `tabular-nums` keeps "9." and "10." the same width. */}
              <Text style={[styles.body, style, styles.marker]}>{listMarker(block, index)}</Text>
              <Text style={[styles.body, style, styles.listText]}>
                <Spans spans={item} />
              </Text>
            </View>
          ))}
        </View>
      )

    default:
      return (
        <Text style={[styles.body, style, spacer]}>
          <Spans spans={block.spans} />
        </Text>
      )
  }
}

/**
 * Nested `<Text>` runs, not views: only nested Text wraps correctly mid-sentence,
 * and it is what lets an inline citation chip sit in the flow of a paragraph.
 */
function Spans({ spans }: { spans: InlineSpan[] }) {
  return (
    <>
      {spans.map((span, index) => (
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
          {renderSpanText(span.text)}
        </Text>
      ))}
    </>
  )
}

/**
 * The single place a leaf string becomes renderable content.
 *
 * A hook, deliberately: F2's inline `[S1]` markers are a transform on exactly
 * this string, and having one seam means citations do not have to touch the
 * block layout above.
 */
function renderSpanText(text: string): React.ReactNode {
  return text
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
