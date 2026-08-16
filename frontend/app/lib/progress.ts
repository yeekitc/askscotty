/**
 * Which planner lanes are running right now, for the thinking indicator.
 *
 * A module-level store rather than React state because the writer is the chat
 * adapter, which is a plain async generator outside the component tree, and the
 * reader is a component. `useSyncExternalStore` is the sanctioned bridge.
 *
 * This exists because progress used to travel as *message text* — the adapter
 * yielded "Checking Dining…" as the assistant's answer, which meant a save
 * firing mid-run could persist a status line as somebody's answer, and the
 * markdown renderer had to render it. Progress is not an answer; it gets its own
 * channel.
 */

import type { Mode } from './types'

export type RunProgress = {
  /** `Date.now()` when the run began, or 0 when nothing is running. */
  startedAt: number
  /** Lanes currently in flight, in the order they started. */
  running: Mode[]
}

const IDLE: RunProgress = { startedAt: 0, running: [] }

let current: RunProgress = IDLE
const listeners = new Set<() => void>()

/**
 * Replaces the snapshot and notifies. Always a fresh object on a real change,
 * never on a no-op: `useSyncExternalStore` compares by identity, so returning a
 * new object every read would re-render forever.
 */
function set(next: RunProgress): void {
  current = next
  for (const listener of listeners) listener()
}

export function subscribeToProgress(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getProgress(): RunProgress {
  return current
}

/** Server snapshot for react-native-web's SSR path, which never has a live run. */
export function getIdleProgress(): RunProgress {
  return IDLE
}

export function startRun(now = Date.now()): void {
  set({ startedAt: now, running: [] })
}

export function laneStarted(mode: Mode): void {
  if (current.running.includes(mode)) return
  set({ ...current, running: [...current.running, mode] })
}

export function laneEnded(mode: Mode): void {
  if (!current.running.includes(mode)) return
  set({ ...current, running: current.running.filter((lane) => lane !== mode) })
}

export function endRun(): void {
  if (current === IDLE) return
  set(IDLE)
}
