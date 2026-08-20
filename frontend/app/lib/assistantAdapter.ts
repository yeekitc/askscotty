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
import { clearRun, detachRun, startRun, tailRun } from './runs'
import type { Citation, Mode } from './types'

const PROVIDER_KEY = 'askscotty'

export function citationToSourcePart(citation: Citation, index: number): SourceMessagePart {
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
  rooms: 'Rooms',
  handshake: 'Handshake',
  fce: 'FCE',
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
 * All accessors are read at request time rather than closed over once, so the
 * adapter sees the current Sources filter, the current conversation, and the
 * current concise setting without being recreated on every change.
 *
 * `getThreadId` is what lets a follow-up continue where the last answer left
 * off: the backend keys the thread's planner session on it, so "is that still
 * current?" reuses the previous turn's lookups instead of starting over.
 */
export function createHttpAdapter(
  getDisabledModes: () => Mode[] | undefined,
  getThreadId: () => string | undefined,
  getConcise: () => boolean | undefined,
): ChatModelAdapter {
  return {
    async *run({ messages, abortSignal }) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user')
      const text = lastUser?.content.find((part) => part.type === 'text')?.text ?? ''

      if (!text) {
        yield { content: [{ type: 'text', text: 'No input provided.' }] }
        return
      }

      // Undefined only before the first thread exists, which cannot happen from
      // the composer — but the id keys the run, so it cannot be optional here.
      const threadId = getThreadId() ?? ''

      // The stream belongs to lib/runs.ts, not to this generator. That is what
      // lets an answer outlive the conversation being closed: this loop is only
      // a reader, and abandoning it does not stop the run.
      startRun(threadId, text, getDisabledModes(), getConcise())

      try {
        for await (const run of tailRun(threadId)) {
          if (abortSignal.aborted) return

          if (run.result) {
            // The validated answer, which supersedes whatever streamed: markers
            // have been checked and unissued ones stripped by now.
            yield {
              content: [
                { type: 'text', text: run.result.answer },
                ...run.result.citations.map(citationToSourcePart),
              ],
            }
            // Delivered — so nothing downstream should write it a second time.
            clearRun(threadId)
            return
          }

          if (run.error) {
            yield { content: [{ type: 'text', text: run.error }] }
            clearRun(threadId)
            return
          }

          yield { content: [{ type: 'text', text: provisional(run.text) }] }
        }
      } finally {
        // The real detach hook, and it has to be `finally`: when the reader
        // closes the conversation the runtime breaks its own `for await`, which
        // calls `.return()` on this generator rather than resuming it — so the
        // aborted check above never runs. A no-op after a delivered answer,
        // because that path cleared the run first.
        detachRun(threadId)
      }
    },
  }
}
