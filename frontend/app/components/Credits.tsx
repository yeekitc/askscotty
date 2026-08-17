/**
 * The footer credit — attribution only, one line.
 *
 * **Known deviation.** PRD §9 quotes a two-sentence credits copy ending "We are
 * not affiliated with ScottyLabs.", and §1 makes not implying a partnership a
 * rule. That sentence is deliberately not shown in the app; it survives in
 * README.md, which covers the "submission" half of §1's "credit in app +
 * submission" but not the in-app half.
 */

import { StyleSheet, Text } from 'react-native'

import { colors, spacing } from '../lib/theme'

export const CREDITS_TEXT = "Public CMU pages and ScottyLabs' open APIs."

export function Credits({ style }: { style?: React.ComponentProps<typeof Text>['style'] }) {
  return <Text style={[styles.credits, style]}>{CREDITS_TEXT}</Text>
}

const styles = StyleSheet.create({
  credits: {
    fontSize: 12,
    lineHeight: 18,
    color: colors.textMuted,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
  },
})
