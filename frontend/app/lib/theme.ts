/**
 * Shared colours and spacing.
 *
 * Change a value here and it updates on phone AND web. Prefer adding a token
 * here over hardcoding a hex code in a component.
 */

export const colors = {
  background: '#eef3f7',
  surface: 'rgba(255, 255, 255, 0.85)',
  border: '#9bb0bf',
  text: '#12202b',
  textMuted: '#4a6273',
  textFaint: '#6b8090',
  accent: '#12202b',
  accentText: '#f7fafc',
  error: '#8a1f1f',
  mockBadge: '#8a5a1f',
}

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
}

/** Keeps the web layout from stretching to 2000px on a desktop monitor. */
export const MAX_CONTENT_WIDTH = 720
