/**
 * Shared colours and spacing. Add a token here rather than hardcoding a value
 * in a component.
 */

export const colors = {
  background: '#eef3f7',
  surface: 'rgba(255, 255, 255, 0.85)',
  border: '#9bb0bf',
  // For dividers that shouldn't read as a hard edge, where hierarchy already
  // comes from spacing and shadow.
  borderSoft: '#e1e8ee',
  text: '#12202b',
  textMuted: '#4a6273',
  textFaint: '#6b8090',
  accent: '#12202b',
  accentText: '#f7fafc',
  error: '#8a1f1f',
  mockBadge: '#8a5a1f',
  // Lighter than `background` so the sidebar reads as its own surface without
  // needing a border.
  sidebar: '#f9fafb',
  sidebarHover: '#eef1f4',
  // Backdrop behind the sidebar when it opens as a drawer on narrow screens.
  overlay: 'rgba(12, 20, 28, 0.35)',
}

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
}

export const radius = {
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  pill: 999,
}

/** iOS and web read the shadow* props, Android reads `elevation`. Set both. */
export const shadows = {
  soft: {
    shadowColor: '#0f1a24',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.08,
    shadowRadius: 20,
    elevation: 3,
  },
  sidebar: {
    shadowColor: '#0f1a24',
    shadowOffset: { width: 2, height: 0 },
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 4,
  },
}

/** Keeps the web layout from stretching to 2000px on a desktop monitor. */
export const MAX_CONTENT_WIDTH = 720
