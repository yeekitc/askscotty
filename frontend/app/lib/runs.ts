/**
 * Answers in flight, keyed by the thread that asked.
 *
 * The runtime holds one conversation at a time, so a run that lives inside it
 * dies — or worse, writes somewhere else — the moment you open another. Runs
 * live here instead: starting one is not the same as watching one, and the
 * stream survives the watcher going away.
 *
 * A run is *attached* while the runtime is consuming it, and detached once the
 * reader switches threads. Either way it finishes; the difference is only who
 * writes the answer down. Attached, the runtime does it through the message
 * mirror in app/index.tsx. Detached, that same file writes it straight into the
 * stored thread when `done` lands.
 *
 * Lane progress lives on the run rather than in a module-level singleton, which
 * is what it used to be. With two answers generating at once a single slot shows
 * one thread's lanes under the other thread's question.
 *
 * A module-level store rather than React state because the writer is a plain
 * async loop outside the component tree and the reader is a component;
 * `useSyncExternalStore` is the sanctioned bridge.
 */

import { askEvents } from './api'
import type { AskResponse, Mode } from './types'

export type Run = {
  threadId: string
  /** The question, kept so a detached run can be written down without the runtime. */
  query: string
  /** `Date.now()` when the run began. */
  startedAt: number
  /** Provisional answer text, superseded by `result`. */
  text: string
  /** Lanes in flight, in the order they started. */
  lanes: Mode[]
  /** The validated payload, once it arrives. */
  result: AskResponse | null
  /** What to say instead, when the run failed or was cut off. */
  error: string | null
  /** Whether the runtime is still consuming this. */
  attached: boolean
  done: boolean
}

const runs = new Map<string, Run>()
const listeners = new Set<() => void>()

function notify(): void {
  // Copied, because a listener that resolves a waiter removes itself.
  for (const listener of [...listeners]) listener()
}

/** Replaces a run with a new object — `useSyncExternalStore` compares identity. */
function update(threadId: string, patch: Partial<Run>): void {
  const current = runs.get(threadId)
  if (!current) return
  runs.set(threadId, { ...current, ...patch })
  notify()
}

const controllers = new Map<string, AbortController>()

export function subscribeToRuns(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getRun(threadId: string): Run | undefined {
  return runs.get(threadId)
}

/** Server snapshot for react-native-web's SSR path, which never has a live run. */
export function getNoRun(): undefined {
  return undefined
}

export function listRuns(): Run[] {
  return [...runs.values()]
}

/** Stops watching, without stopping the answer. */
export function detachRun(threadId: string): void {
  if (runs.get(threadId)?.attached) update(threadId, { attached: false })
}

/** Forgets a finished run. The answer is in the thread by now. */
export function clearRun(threadId: string): void {
  if (!runs.delete(threadId)) return
  controllers.delete(threadId)
  notify()
}

/** Stops the answer as well. Deleting a thread is the only caller. */
export function cancelRun(threadId: string): void {
  controllers.get(threadId)?.abort()
  clearRun(threadId)
}

export function startRun(threadId: string, query: string, disabledModes: Mode[] | undefined): void {
  // One stream per thread. A second would race the first into the same slot.
  cancelRun(threadId)

  const controller = new AbortController()
  controllers.set(threadId, controller)
  runs.set(threadId, {
    threadId,
    query,
    startedAt: Date.now(),
    text: '',
    lanes: [],
    result: null,
    error: null,
    attached: true,
    done: false,
  })
  notify()

  void drain(threadId, query, disabledModes, controller.signal)
}

async function drain(
  threadId: string,
  query: string,
  disabledModes: Mode[] | undefined,
  signal: AbortSignal,
): Promise<void> {
  try {
    for await (const event of askEvents(query, { disabledModes, threadId, signal })) {
      const run = runs.get(threadId)
      if (!run) return // cancelled out from under us

      if (event.type === 'done') {
        update(threadId, { result: event.data, done: true })
        return
      }

      if (event.type === 'text_delta') {
        update(threadId, { text: run.text + event.data.text })
        continue
      }

      // The model narrates itself into a lookup ("let me check dining hours"),
      // and that text is discarded from the final answer — so a lane starting
      // means what came before it was preamble, not an answer.
      if (event.type === 'mode_start') {
        update(threadId, {
          text: '',
          lanes: run.lanes.includes(event.data.mode) ? run.lanes : [...run.lanes, event.data.mode],
        })
      }

      if (event.type === 'mode_end') {
        update(threadId, { lanes: run.lanes.filter((lane) => lane !== event.data.mode) })
      }
    }

    // Fell out of the loop without a `done` — the connection dropped mid-answer.
    // Say so, rather than leaving the thread looking like it is still thinking.
    if (!signal.aborted) {
      update(threadId, { error: 'The answer was cut off before it arrived.', done: true })
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : 'The assistant failed to respond.'
    update(threadId, { error: message, done: true })
  } finally {
    if (runs.get(threadId)?.done === false) update(threadId, { done: true })
  }
}

/**
 * Yields a run's state until it finishes, for the chat adapter.
 *
 * Waking on any run's change rather than this one's is deliberate: re-reading a
 * map entry costs nothing next to the bookkeeping of per-run waiter sets.
 */
export async function* tailRun(threadId: string): AsyncGenerator<Run> {
  for (;;) {
    const run = runs.get(threadId)
    if (!run) return

    yield run
    if (run.done) return

    await new Promise<void>((resolve) => {
      const listener = () => {
        listeners.delete(listener)
        resolve()
      }
      listeners.add(listener)
    })
  }
}
