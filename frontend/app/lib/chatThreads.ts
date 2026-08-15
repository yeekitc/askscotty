/**
 * Multi-thread history for the sidebar, built by hand.
 *
 * `useLocalRuntime` runs a single live thread and its built-in thread-list
 * throws "Method not implemented" for switching/creating/deleting — real
 * multi-thread support expects a remote adapter. So each thread is snapshotted
 * here via `thread.subscribe(...)`, and switching calls `thread.reset(messages)`
 * to load another one back into the single live runtime.
 */

import type { ThreadMessageLike } from '@assistant-ui/react-native'

import { deleteThread, fetchThreads, saveThread } from './api'
import type { StoredMessage } from './types'

export type ChatThread = {
  id: string
  messages: ThreadMessageLike[]
  updatedAt: number
}

export function createEmptyThread(id: string): ChatThread {
  return { id, messages: [], updatedAt: Date.now() }
}

// --- Persistence --------------------------------------------------------------
//
// Threads are saved to our Django backend, not assistant-ui's hosted Cloud (see
// backend/apps/core/models.py). This replaces a localStorage cache that only
// worked on web — `window` does not exist on a phone, so native builds lost
// every conversation on restart.

/**
 * The wire format and assistant-ui's format are the same JSON, but the server
 * round-trips `content` as opaque `unknown[]`. These two functions are the one
 * place that gap is asserted away, rather than at every call site.
 */
function toStored(thread: ChatThread): StoredMessage[] {
  return thread.messages.map((message) => ({
    role: message.role === 'assistant' ? 'assistant' : 'user',
    content: (Array.isArray(message.content)
      ? message.content
      : [{ type: 'text', text: String(message.content) }]) as unknown[],
  }))
}

function fromStored(messages: StoredMessage[]): ThreadMessageLike[] {
  return messages.map(
    (message) =>
      ({
        role: message.role,
        content: message.content,
      }) as ThreadMessageLike,
  )
}

/** Throws when the backend is unreachable; the caller decides what to show. */
export async function loadThreads(): Promise<ChatThread[]> {
  const stored = await fetchThreads()
  return stored.map((thread) => ({
    id: thread.id,
    messages: fromStored(thread.messages),
    updatedAt: Date.parse(thread.updated_at) || Date.now(),
  }))
}

export async function persistThread(thread: ChatThread): Promise<void> {
  await saveThread(thread.id, toStored(thread))
}

export async function removeThread(id: string): Promise<void> {
  await deleteThread(id)
}

/** Derived from the first user message — there is no stored title to keep in sync. */
export function threadTitle(thread: ChatThread): string {
  const firstUser = thread.messages.find((m) => m.role === 'user')
  if (!firstUser) return 'New chat'

  const text =
    typeof firstUser.content === 'string'
      ? firstUser.content
      : firstUser.content.find((part) => part.type === 'text')?.text ?? ''

  return text.trim() || 'New chat'
}
