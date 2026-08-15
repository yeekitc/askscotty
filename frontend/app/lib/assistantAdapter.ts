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
 * Placeholder for the real progress UI (tasklist F1), which wants mode chips
 * rather than a line of text. The events are what matter here; this only makes
 * them visible in the meantime.
 */
function progressText(running: Set<Mode>): string {
  if (running.size === 0) return 'Working…'
  return `Checking ${[...running].map((mode) => MODE_LABELS[mode]).join(', ')}…`
}

/**
 * `getSources` is read at request time rather than closed over once, so the
 * adapter sees the current Sources filter without being recreated on every
 * change to it.
 */
export function createHttpAdapter(getSources: () => string[] | undefined): ChatModelAdapter {
  return {
    async *run({ messages, abortSignal }) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user')
      const text = lastUser?.content.find((part) => part.type === 'text')?.text ?? ''

      if (!text) {
        yield { content: [{ type: 'text', text: 'No input provided.' }] }
        return
      }

      const running = new Set<Mode>()

      try {
        for await (const event of askEvents(text, {
          sources: getSources(),
          signal: abortSignal,
        })) {
          if (event.type === 'done') {
            yield {
              content: [
                { type: 'text', text: event.data.answer },
                ...event.data.citations.map(citationToSourcePart),
              ],
            }
            return
          }

          if (event.type === 'mode_start') running.add(event.data.mode)
          if (event.type === 'mode_end') running.delete(event.data.mode)
          yield { content: [{ type: 'text', text: progressText(running) }] }
        }

        // Fell out of the loop without a `done` — the connection dropped
        // mid-answer. Say so, rather than leaving the progress line up forever.
        // Unless the user stopped it themselves, which needs no explaining.
        if (!abortSignal.aborted) {
          yield {
            content: [{ type: 'text', text: 'The answer was cut off before it arrived.' }],
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'The assistant failed to respond.'
        yield { content: [{ type: 'text', text: message }] }
      }
    },
  }
}
