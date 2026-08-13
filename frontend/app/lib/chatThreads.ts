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

export type ChatThread = {
  id: string
  messages: ThreadMessageLike[]
  updatedAt: number
}

export function createEmptyThread(id: string): ChatThread {
  return { id, messages: [], updatedAt: Date.now() }
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
