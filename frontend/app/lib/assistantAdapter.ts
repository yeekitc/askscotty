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
import { ask } from './api'
import type { Citation } from './types'

const PROVIDER_KEY = 'askscotty'

function citationToSourcePart(citation: Citation, index: number): SourceMessagePart {
  const providerMetadata = {
    [PROVIDER_KEY]: {
      source: citation.source,
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
    title: part.title || 'Source',
    // Document parts carry no url, and a reloaded thread has been through JSON
    // both ways, so every field defaults to the Citation contract in types.ts.
    url: typeof part.url === 'string' ? part.url : '',
    source: typeof meta.source === 'string' ? meta.source : 'Unknown',
    indexed_at: typeof meta.indexed_at === 'string' ? meta.indexed_at : null,
    verified_at: typeof meta.verified_at === 'string' ? meta.verified_at : null,
    is_mock: Boolean(meta.is_mock),
  }
}

/**
 * `getSources` is read at request time rather than closed over once, so the
 * adapter sees the current Sources filter without being recreated on every
 * change to it.
 */
export function createHttpAdapter(getSources: () => string[] | undefined): ChatModelAdapter {
  return {
    async *run({ messages }) {
      const lastUser = [...messages].reverse().find((m) => m.role === 'user')
      const text = lastUser?.content.find((part) => part.type === 'text')?.text ?? ''

      if (!text) {
        yield { content: [{ type: 'text', text: 'No input provided.' }] }
        return
      }

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
