/**
 * Client-side smoothing for a streamed answer.
 *
 * The API does not stream a word at a time. Measured on one short answer it sent
 * eight pieces of 15/16/19/13/17/**205/163/74** chars (docs/b4-planner.md), so a
 * whole paragraph lands in a single frame and nothing upstream makes it finer.
 * A steady reveal can only come from here.
 *
 * The shape is assistant-ui's `StreamingText` element ported off the DOM: a
 * *controlled* word count, which is what separates arrival rate from display
 * rate. Their leading edge is tinted blue; ours fades up from `textFaint`,
 * because the palette has no blue and a coloured band moving through dark prose
 * reads as noise rather than as arrival.
 */

import { useEffect, useState } from 'react'

import { useReducedMotion } from './motion'
import { colors } from './theme'

/** How often the reveal advances. Fast enough that words read as continuous. */
const TICK_MS = 40

/**
 * Words per tick is the backlog over this, so a large chunk drains quickly and
 * the tail still arrives one word at a time. A fixed rate cannot do both: slow
 * enough to read makes that 205-char chunk take seconds, fast enough to keep up
 * is a flicker.
 */
const CATCH_UP = 8

/** After the run ends there is nothing left to pace against, so finish sooner. */
const CATCH_UP_FINAL = 3

/** Platform text cursors blink at roughly this rate. */
const BLINK_MS = 530

/** How many words behind the edge are still fading up to full colour. */
export const FADE_WORDS = 5

/**
 * Words carrying their own surrounding whitespace, so any prefix rejoins into
 * exactly the text it came from.
 *
 * A whitespace-only string becomes one chunk rather than none — it costs a word
 * of budget, but `lib/markdown.ts` guarantees nothing ever drops text and a
 * silently eaten space between two spans would break that.
 */
export function splitWords(text: string): string[] {
  const chunks = text.match(/\s*\S+\s*/g)
  if (chunks) return chunks
  return text ? [text] : []
}

/** `#rrggbb` blend, `t` running 0 → `from`, 1 → `to`. */
function mix(from: string, to: string, t: number): string {
  const channel = (offset: number) => {
    const a = parseInt(from.slice(offset, offset + 2), 16)
    const b = parseInt(to.slice(offset, offset + 2), 16)
    return Math.round(a + (b - a) * t)
      .toString(16)
      .padStart(2, '0')
  }
  return `#${channel(1)}${channel(3)}${channel(5)}`
}

/**
 * Colour per word behind the edge — index 0 is the newest. Precomputed rather
 * than animated: the reveal already re-renders every tick, so stepping the
 * colour costs nothing where five per-word animation drivers would not.
 */
export const FADE_RAMP = Array.from({ length: FADE_WORDS }, (_, index) =>
  mix(colors.textFaint, colors.text, index / (FADE_WORDS - 1)),
)

/**
 * How many of `total` words to show right now.
 *
 * Returns `total` outright when the user asked for less motion, and whenever the
 * message is not streaming — a thread reloaded from storage must render whole
 * rather than replay itself.
 */
export function useSmoothReveal(total: number, streaming: boolean): number {
  const reduceMotion = useReducedMotion()
  const [revealed, setRevealed] = useState(streaming ? 0 : total)

  // The budget has to be able to come back down. A `mode_start` throws away what
  // streamed (it was preamble to a lookup) and `done` swaps in a validated
  // answer that can be shorter than the draft; either way a reveal left past the
  // end of the text renders nothing at all.
  useEffect(() => {
    setRevealed((current) => Math.min(current, total))
  }, [total])

  const caughtUp = revealed >= total

  useEffect(() => {
    if (reduceMotion) {
      setRevealed(total)
      return
    }
    // Idle once the text is fully shown and no more is coming. Staying mounted
    // and ticking would keep every finished message in the thread re-rendering.
    if (caughtUp && !streaming) return

    const divisor = streaming ? CATCH_UP : CATCH_UP_FINAL
    const timer = setInterval(() => {
      setRevealed((current) => {
        const backlog = total - current
        if (backlog <= 0) return current
        return current + Math.max(1, Math.round(backlog / divisor))
      })
    }, TICK_MS)
    return () => clearInterval(timer)
  }, [total, streaming, reduceMotion, caughtUp])

  return Math.min(revealed, total)
}

/** Whether the caret is lit this frame. */
export function useBlink(active: boolean): boolean {
  const [on, setOn] = useState(true)

  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => setOn((current) => !current), BLINK_MS)
    return () => {
      clearInterval(timer)
      // So the next run starts lit rather than wherever the last one stopped.
      setOn(true)
    }
  }, [active])

  return active && on
}
