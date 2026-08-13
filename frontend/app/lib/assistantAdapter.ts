/**
 * Bridges assistant-ui's runtime to our POST /api/ask/ endpoint.
 *
 * Citations ride along as assistant-ui "source" message parts — its built-in
 * part type for "this bit of the answer came from a link" — instead of a
 * bespoke shape, so the standard MessagePrimitive.Content renderSource slot
 * can pick them up. The extra fields the PRD requires on a citation (source
 * name, indexed_at/verified_at, is_mock) don't fit assistant-ui's SourcePart,
 * so they travel in `providerMetadata` under an "askscotty" key and get
 * unpacked again in `sourcePartToCitation`, which the message renderer uses
 * to feed the existing CitationCard component.
 */

import type { ChatModelAdapter, SourceMessagePart } from '@assistant-ui/react-native'
import { ask } from './api'
import type { Citation } from './types'

const PROVIDER_KEY = 'askscotty'

function citationToSourcePart(citation: Citation, index: number): SourceMessagePart {
  const providerMetadata = {
    [PROVIDER_KEY]: {
      source: citation.source,
      indexed_at: citation.indexed_at ?? null,
      verified_at: citation.verified_at ?? null,
      is_mock: citation.is_mock ?? false,
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

  // Citations without a live URL (mocks, PRD refs) are treated as opaque
  // documents — the "document" variant requires mediaType instead of a url.
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
    title: part.title || 'Source',
    url: part.url,
    source: typeof meta.source === 'string' ? meta.source : 'Unknown',
    indexed_at: typeof meta.indexed_at === 'string' ? meta.indexed_at : undefined,
    verified_at: typeof meta.verified_at === 'string' ? meta.verified_at : undefined,
    is_mock: Boolean(meta.is_mock),
  }
}

/**
 * `getSources` and `onQuerySent` are read at request time rather than closed
 * over once, so the adapter always sees the screen's current source filter
 * and recents list without needing to be recreated on every state change.
 */
export function createHttpAdapter(
  getSources: () => string[] | undefined,
  onQuerySent?: (query: string) => void,
): ChatModelAdapter {
  return {
    async *run({ messages }) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user')
      const text = lastUser?.content.find((part) => part.type === 'text')?.text ?? ''

      if (!text) {
        yield { content: [{ type: 'text', text: 'No input provided.' }] }
        return
      }

      onQuerySent?.(text)

      try {
        const res = await ask(text, getSources())
        yield {
          content: [
            { type: 'text', text: res.answer },
            ...res.citations.map(citationToSourcePart),
          ],
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : 'The assistant failed to respond.'
        yield { content: [{ type: 'text', text: message }] }
      }
    },
  }
}
