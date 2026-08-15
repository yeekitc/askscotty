/**
 * Local multi-thread history for the sidebar.
 *
 * assistant-ui's `useLocalRuntime` only ever runs a single live thread — its
 * built-in thread-list (the thing `<ThreadList />` is normally backed by)
 * throws "Method not implemented" for switching/creating/deleting threads,
 * because real multi-thread support expects a remote adapter talking to a
 * backend that persists threads (assistant-ui Cloud, or your own — see
 * https://www.assistant-ui.com/docs/architecture). We don't have that backend
 * yet (no Thread/Message models in Django today), so "New Chat" / switching
 * between past conversations is built here instead: each thread's message
 * list is snapshotted into this array via `thread.subscribe(...)`, and
 * switching calls `thread.reset(messages)` to load a different one back into
 * the one live runtime. It's a real, working multi-thread sidebar — just
 * backed by this device's storage rather than a server.
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
// Threads are saved to our Django backend (see backend/apps/core/models.py for
// why we run our own storage rather than assistant-ui's hosted Cloud). This
// replaces a localStorage cache that only ever worked on web — on a phone,
// `window` does not exist, so every conversation was lost on restart.

/**
 * The wire format and assistant-ui's format are the same JSON, but TypeScript
 * cannot know that: the server round-trips `content` as opaque JSON, so it
 * comes back as `unknown[]`. These two functions are where that is asserted,
 * deliberately in one place rather than at every call site.
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

/**
 * Load this session's threads.
 *
 * Returns an empty list rather than throwing when the backend is unreachable —
 * a student with no network should still get a usable app with a fresh chat,
 * not an error screen. The caller decides what to show.
 */
export async function loadThreads(): Promise<ChatThread[]> {
  const stored = await fetchThreads()
  return stored.map((thread) => ({
    id: thread.id,
    messages: fromStored(thread.messages),
    updatedAt: Date.parse(thread.updated_at) || Date.now(),
  }))
}

/** Persist one thread. Creates it server-side on first call. */
export async function persistThread(thread: ChatThread): Promise<void> {
  await saveThread(thread.id, toStored(thread))
}

/** Remove a thread from the server. */
export async function removeThread(id: string): Promise<void> {
  await deleteThread(id)
}

/** Derives a display title from the first user message — there's no separate title field to keep in sync. */
export function threadTitle(thread: ChatThread): string {
  const firstUser = thread.messages.find((m) => m.role === 'user')
  if (!firstUser) return 'New chat'

  const text =
    typeof firstUser.content === 'string'
      ? firstUser.content
      : firstUser.content.find((part) => part.type === 'text')?.text ?? ''

  return text.trim() || 'New chat'
}
