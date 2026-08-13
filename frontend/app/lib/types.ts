/**
 * Shape of the data the backend sends back.
 *
 * This file is the single source of truth for the API shape. If you change
 * `AskResponse` here, TypeScript will tell you everywhere in the app that
 * needs updating — on phone AND web at the same time.
 *
 * The matching backend definition lives in backend/apps/core/serializers.py.
 * Keep the two in sync.
 */

export type Citation = {
  title: string
  /** Link to the source page. May be empty for mock/stub sources. */
  url?: string
  /** Where this came from, e.g. "Courses", "CMU Eats", "TartanConnect". */
  source: string
  /** When our index last crawled it (PRD requires showing this). */
  indexed_at?: string
  /** When we last confirmed it live (PRD requires showing this). */
  verified_at?: string
  /** True when this came from mock data — the PRD requires labelling mocks. */
  is_mock?: boolean
}

export type AskResponse = {
  answer: string
  citations: Citation[]
  modes_used: string[]
  note: string
}
