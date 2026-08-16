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

import { ApiError, deleteThread, fetchThreads, saveThread } from './api'
import type { StoredMessage } from './types'

export type ChatThread = {
  id: string
  messages: ThreadMessageLike[]
  /** Empty until somebody renames it; `threadTitle` falls back to the first message. */
  title: string
  updatedAt: number
}

export function createEmptyThread(id: string): ChatThread {
  return { id, messages: [], title: '', updatedAt: Date.now() }
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
    // Tolerated as missing so an app build newer than the backend still loads.
    title: thread.title ?? '',
    updatedAt: Date.parse(thread.updated_at) || Date.now(),
  }))
}

export async function persistThread(thread: ChatThread): Promise<void> {
  await saveThread(thread.id, toStored(thread), thread.title)
}

/**
 * Deleting a thread nobody ever sent a message in is a no-op rather than a
 * failure: `persistThread` skips empty threads, so there is no server row and
 * the backend's not_found is the expected answer.
 */
export async function removeThread(id: string): Promise<void> {
  try {
    await deleteThread(id)
  } catch (err) {
    if (!(err instanceof ApiError) || err.code !== 'not_found') throw err
  }
}

/**
 * An explicit rename wins; otherwise the title is derived from the first user
 * message, so a thread nobody has renamed keeps naming itself as it grows.
 */
export function threadTitle(thread: ChatThread): string {
  if (thread.title) return thread.title

  const firstUser = thread.messages.find((m) => m.role === 'user')
  if (!firstUser) return 'New chat'

  const text =
    typeof firstUser.content === 'string'
      ? firstUser.content
      : firstUser.content.find((part) => part.type === 'text')?.text ?? ''

  return text.trim() || 'New chat'
}
