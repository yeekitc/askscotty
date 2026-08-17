/**
 * Bridges assistant-ui's runtime to POST /api/ask/.
 *
 * Citations ride as assistant-ui "source" parts rather than a bespoke shape, so
 * the standard MessagePrimitive.Content renderSource slot picks them up. The
 * extra fields the PRD requires (source name, indexed_at/verified_at, is_mock)
 * don't fit its SourcePart, so they travel in `providerMetadata` and are
 * unpacked again by `sourcePartToCitation`.
 */

import type { ChatModelAdapter, SourceMessagePart } from '@assistant-ui/react-native'
import { askEvents } from './api'
import { endRun, laneEnded, laneStarted, startRun } from './progress'
import type { Citation, Mode } from './types'

const PROVIDER_KEY = 'askscotty'

function citationToSourcePart(citation: Citation, index: number): SourceMessagePart {
  const providerMetadata = {
    [PROVIDER_KEY]: {
      // Not part.id, which is assistant-ui's own handle for the part. This is
      // the planner's "S1", what an inline marker resolves to.
      id: citation.id,
      source: citation.source,
      snippet: citation.snippet,
      indexed_at: citation.indexed_at,
      verified_at: citation.verified_at,
      is_mock: citation.is_mock,
    },
  }

  if (citation.url) {
    return {
      type: 'source',
      sourceType: 'url',
      id: `citation-${index}`,
      url: citation.url,
      title: citation.title,
      providerMetadata,
    }
  }

  // Citations with no live URL (mocks, PRD refs) become opaque documents — that
  // variant requires mediaType instead of a url.
  return {
    type: 'source',
    sourceType: 'document',
    id: `citation-${index}`,
    title: citation.title || 'Source',
    mediaType: 'text/plain',
    providerMetadata,
  }
}

/** Inverse of citationToSourcePart — used by the message renderer. */
export function sourcePartToCitation(part: SourceMessagePart): Citation {
  const meta = part.providerMetadata?.[PROVIDER_KEY] ?? {}
  return {
    id: typeof meta.id === 'string' ? meta.id : '',
    title: part.title || 'Source',
    // Document parts carry no url, and a reloaded thread has been through JSON
    // both ways, so every field defaults to the Citation contract in types.ts.
    url: typeof part.url === 'string' ? part.url : '',
    source: typeof meta.source === 'string' ? meta.source : 'Unknown',
    snippet: typeof meta.snippet === 'string' ? meta.snippet : '',
    indexed_at: typeof meta.indexed_at === 'string' ? meta.indexed_at : null,
    verified_at: typeof meta.verified_at === 'string' ? meta.verified_at : null,
    is_mock: Boolean(meta.is_mock),
  }
}

/** Chip copy for each planner lane. Shared with whatever renders `modes_used`. */
export const MODE_LABELS: Record<Mode, string> = {
  rag: 'Campus index',
  courses: 'Courses',
  dining: 'Dining',
  events: 'Events',
  maps: 'Maps',
  web_verify: 'Web verify',
  personal: 'Your accounts',
}

/**
 * A whole citation marker, or a partial one still being streamed at the end.
 *
 * Wider than `[S1]` for the same reason the backend's is (see
 * `apps/planner/citations.py`): told to cite two sources for one claim the model
 * writes `[S25, S30-4]`, and a narrow pattern leaves that on screen.
 */
const STREAMED_MARKER = /\[S\d[\d\s,S-]*\]/g
const TRAILING_PARTIAL_MARKER = /\[S[\d\s,S-]*$/

/**
 * Streamed text, with citation markers held back until the answer is final.
 *
 * The agent is provisioned to write `[S1]` markers unconditionally — that is
 * what lets citations be switched on by an env var rather than a re-provision
 * (docs/b4-planner.md) — so they are in the token stream whether or not anything
 * can render them yet. The backend strips or keeps them in the `done` payload;
 * until then a raw `[S11]` would flash mid-sentence and then vanish.
 *
 * Applied to the whole accumulated string rather than each chunk, so a marker
 * split across two deltas ("[S" then "11]") is still caught. The trailing rule
 * covers the moment in between, where the text genuinely ends mid-marker.
 */
function provisional(streamed: string): string {
  return streamed.replace(STREAMED_MARKER, '').replace(TRAILING_PARTIAL_MARKER, '')
}

/**
 * Both accessors are read at request time rather than closed over once, so the
 * adapter sees the current Sources filter and the current conversation without
 * being recreated on every change to either.
 *
 * `getThreadId` is what lets a follow-up continue where the last answer left
 * off: the backend keys the thread's planner session on it, so "is that still
 * current?" reuses the previous turn's lookups instead of starting over.
 */
export function createHttpAdapter(
  getDisabledModes: () => Mode[] | undefined,
  getThreadId: () => string | undefined,
): ChatModelAdapter {
  return {
    async *run({ messages, abortSignal }) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user')
      const text = lastUser?.content.find((part) => part.type === 'text')?.text ?? ''

      if (!text) {
        yield { content: [{ type: 'text', text: 'No input provided.' }] }
        return
      }

      let streamed = ''
      startRun()

      try {
        for await (const event of askEvents(text, {
          disabledModes: getDisabledModes(),
          threadId: getThreadId(),
          signal: abortSignal,
        })) {
          if (event.type === 'done') {
            // The validated answer, which supersedes whatever streamed: markers
            // have been checked and unissued ones stripped by now.
            yield {
              content: [
                { type: 'text', text: event.data.answer },
                ...event.data.citations.map(citationToSourcePart),
              ],
            }
            return
          }

          if (event.type === 'text_delta') {
            streamed += event.data.text
            yield { content: [{ type: 'text', text: provisional(streamed) }] }
            continue
          }

          // Lane events drive the thinking indicator, not the message. They used
          // to be yielded as assistant text, which meant a debounced save firing
          // mid-run could persist "Checking Dining…" as somebody's answer.
          if (event.type === 'mode_start') {
            laneStarted(event.data.mode)
            // The model went off to look something up, so what it had written
            // was preamble to that, not an answer.
            streamed = ''
            yield { content: [{ type: 'text', text: '' }] }
          }
          if (event.type === 'mode_end') laneEnded(event.data.mode)
        }

        // Fell out of the loop without a `done` — the connection dropped
        // mid-answer. Say so, rather than leaving the indicator up forever.
        // Unless the user stopped it themselves, which needs no explaining.
        if (!abortSignal.aborted) {
          yield {
            content: [{ type: 'text', text: 'The answer was cut off before it arrived.' }],
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'The assistant failed to respond.'
        yield { content: [{ type: 'text', text: message }] }
      } finally {
        // Whatever happened — answered, aborted, threw — the lanes are not
        // running any more, and a stuck indicator outlives the turn.
        endRun()
      }
    },
  }
}
