/**
 * A small Markdown parser for the subset Claude actually writes.
 *
 * Hand-rolled rather than a dependency, and that is a deliberate trade — see
 * docs/dependencies.md. The short version: every React Native markdown library
 * drags in native modules we do not otherwise need (icon fonts, an SVG peer, a
 * syntax highlighter), and all of them own the whole text subtree, which fights
 * F2's inline `[S1]` citation chips — those have to be direct children of the
 * outermost `<Text>`.
 *
 * The subset is not a guess. The planner's system prompt tells the model to
 * write for someone on a phone between classes: "a few sentences, or a short
 * list", lists for options and prose for explanations. So: paragraphs, headings,
 * bullet and numbered lists, fenced code, and four inline forms.
 *
 * **Nothing here ever drops text.** Anything unrecognised falls through as plain
 * prose, because a renderer that silently swallows part of an answer is worse
 * than one that renders an asterisk.
 *
 * This file is pure — no React, no react-native — so it can be reasoned about
 * and tested on its own. `components/AnswerText.tsx` turns the output into views.
 */

/** A run of text with the marks that apply to it. */
export type InlineSpan = {
  text: string
  bold?: boolean
  italic?: boolean
  code?: boolean
  /** Set when the span came from `[label](href)`. */
  href?: string
}

export type Block =
  | { type: 'paragraph'; spans: InlineSpan[] }
  | { type: 'heading'; level: 1 | 2 | 3; spans: InlineSpan[] }
  /** `ordered` drives the marker; `start` is what the first item is numbered. */
  | { type: 'list'; ordered: boolean; start: number; items: InlineSpan[][] }
  | { type: 'code'; language?: string; text: string }

const HEADING = /^(#{1,3})\s+(.*)$/
const BULLET = /^[-*+]\s+(.*)$/
const NUMBERED = /^(\d{1,3})[.)]\s+(.*)$/
const FENCE = /^```/

/**
 * Markdown source → blocks.
 *
 * Line-based rather than a real block grammar: the answers are short and flat,
 * and a nested-list parser would be a lot of code for output the prompt
 * discourages the model from producing.
 */
export function parseMarkdown(source: string): Block[] {
  const blocks: Block[] = []
  const lines = source.replace(/\r\n/g, '\n').split('\n')

  let paragraph: string[] = []
  // The list a plain line would continue, if one is still open. Markdown calls
  // this lazy continuation, and the model uses it constantly — it writes
  // "- **Hunt Library**:" and puts the description on the next line. Without
  // this the description breaks out into its own full-width paragraph.
  let openList: Extract<Block, { type: 'list' }> | null = null

  const flushParagraph = () => {
    if (paragraph.length === 0) return
    // Joined with a space, not a newline: a hard-wrapped paragraph is one
    // paragraph, and <Text> would otherwise render the author's wrapping.
    blocks.push({ type: 'paragraph', spans: parseInline(paragraph.join(' ')) })
    paragraph = []
  }

  for (let index = 0; index < lines.length; index++) {
    const line = lines[index]

    if (FENCE.test(line.trim())) {
      flushParagraph()
      openList = null
      const fenceInfo = line.trim().slice(3).trim()
      const body: string[] = []
      index++
      while (index < lines.length && !FENCE.test(lines[index].trim())) {
        body.push(lines[index])
        index++
      }
      // An unterminated fence runs to the end of the answer, which is what a
      // half-streamed code block looks like. Render what there is.
      blocks.push({ type: 'code', language: fenceInfo || undefined, text: body.join('\n') })
      continue
    }

    if (line.trim() === '') {
      flushParagraph()
      // A blank line closes the list: what follows is a new block, not more of
      // the last item.
      openList = null
      continue
    }

    const heading = HEADING.exec(line.trim())
    if (heading) {
      flushParagraph()
      openList = null
      blocks.push({
        type: 'heading',
        level: heading[1].length as 1 | 2 | 3,
        spans: parseInline(heading[2]),
      })
      continue
    }

    const bullet = BULLET.exec(line.trim())
    const numbered = NUMBERED.exec(line.trim())
    if (bullet || numbered) {
      flushParagraph()
      const ordered = Boolean(numbered)
      const text = (bullet ? bullet[1] : numbered![2]).trim()
      const previous = blocks[blocks.length - 1]

      // Append to the list above when it is the same kind, so two bullets are
      // one list rather than two one-item lists with a gap between them.
      if (previous?.type === 'list' && previous.ordered === ordered) {
        previous.items.push(parseInline(text))
        openList = previous
      } else {
        const list: Extract<Block, { type: 'list' }> = {
          type: 'list',
          ordered,
          start: numbered ? Number(numbered[1]) : 1,
          items: [parseInline(text)],
        }
        blocks.push(list)
        openList = list
      }
      continue
    }

    // A plain line directly under a list item continues that item.
    if (openList && paragraph.length === 0) {
      const item = openList.items[openList.items.length - 1]
      item.push(...parseInline(` ${line.trim()}`))
      continue
    }

    paragraph.push(line.trim())
  }

  flushParagraph()
  return blocks
}

/** A delimiter run is only emphasis if it hugs its content: `**a**`, not `** a **`. */
const hugsContent = (body: string) => body.length > 0 && body.trim() === body

/**
 * `_` only emphasises at a word boundary, so `snake_case_name` and `15_213` stay
 * literal. This is CommonMark's rule and it earns its keep here — the answers
 * are full of identifiers.
 */
const atWordBoundary = (source: string, match: RegExpExecArray) => {
  const before = source[match.index - 1] ?? ' '
  const after = source[match.index + match[0].length] ?? ' '
  return !/[A-Za-z0-9]/.test(before) && !/[A-Za-z0-9]/.test(after)
}

/**
 * Ordered by precedence, and the order matters twice over.
 *
 * Code first: backticks are literal inside, so `**x**` in a code span must not
 * come out bold. Bold before italic: they start at the same index on `**x**`,
 * and the first rule to claim an index wins.
 *
 * The bodies are lazy and allow the *other* delimiter through, so
 * `**bold with *emphasis* inside**` parses as one bold run rather than
 * collapsing into fragments.
 */
const INLINE = [
  { kind: 'code', pattern: /`([^`\n]+)`/ },
  { kind: 'link', pattern: /\[([^\]\n]*)\]\(([^)\s]+)\)/ },
  { kind: 'bold', pattern: /\*\*([^\n]+?)\*\*/, guard: hugsContent },
  { kind: 'bold', pattern: /__([^\n]+?)__/, guard: hugsContent, wordBoundary: true },
  { kind: 'italic', pattern: /\*([^\n]+?)\*/, guard: hugsContent },
  { kind: 'italic', pattern: /_([^\n]+?)_/, guard: hugsContent, wordBoundary: true },
] as const

/**
 * One line of inline markdown → spans.
 *
 * Recursive on the remainder rather than a tokeniser: with four forms and short
 * lines it is easier to follow, and it keeps the "unmatched syntax stays as
 * text" guarantee obvious — anything that does not match a pattern is emitted
 * verbatim.
 */
export function parseInline(source: string, marks: Omit<InlineSpan, 'text'> = {}): InlineSpan[] {
  if (!source) return []

  let earliest: { index: number; length: number; span: InlineSpan; body: string } | null = null

  for (const rule of INLINE) {
    const match = rule.pattern.exec(source)
    if (!match) continue
    // Strictly earlier: a tie goes to the rule declared first, which is how
    // `**x**` becomes bold rather than italic-wrapping-italic.
    if (earliest && match.index >= earliest.index) continue

    const body = match[1]
    const guard = 'guard' in rule ? rule.guard : null
    if (guard && !guard(body)) continue
    if ('wordBoundary' in rule && rule.wordBoundary && !atWordBoundary(source, match)) continue

    const span: InlineSpan =
      rule.kind === 'link'
        ? { ...marks, text: body || match[2], href: match[2] }
        : { ...marks, text: body, [rule.kind]: true }

    earliest = { index: match.index, length: match[0].length, span, body }
  }

  if (!earliest) return [{ ...marks, text: source }]

  const before = source.slice(0, earliest.index)
  const after = source.slice(earliest.index + earliest.length)

  // A code span's body is literal; everything else can nest (bold inside a
  // link, italic inside bold), so re-parse the body carrying the marks down.
  const inner: InlineSpan[] = earliest.span.code
    ? [earliest.span]
    : parseInline(earliest.body, {
        ...marks,
        bold: earliest.span.bold ?? marks.bold,
        italic: earliest.span.italic ?? marks.italic,
        href: earliest.span.href ?? marks.href,
      })

  return [
    ...(before ? [{ ...marks, text: before }] : []),
    ...(inner.length ? inner : [earliest.span]),
    ...parseInline(after, marks),
  ]
}

/** The marker shown before an item, e.g. "•" or "2.". */
export function listMarker(block: Extract<Block, { type: 'list' }>, index: number): string {
  return block.ordered ? `${block.start + index}.` : '•'
}
