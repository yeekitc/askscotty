/**
 * The wording below is verbatim from PRD §8 and must not be paraphrased — the
 * "not affiliated with ScottyLabs" line is a hard requirement.
 */

import { StyleSheet, Text } from 'react-native'

import { colors, spacing } from '../lib/theme'

export const CREDITS_TEXT =
  'Uses publicly available CMU web pages and public campus APIs, including open ' +
  'APIs published by ScottyLabs (e.g. Courses). We are not affiliated with ScottyLabs.'

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
