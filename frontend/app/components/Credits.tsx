/**
 * Required credits footer.
 *
 * The wording below is specified verbatim by PRD.md §8 (Credits). Do not
 * paraphrase or shorten it — the "not affiliated with ScottyLabs" line is a
 * hard requirement, and it must appear in the app and in the submission.
 */

import { StyleSheet, Text } from 'react-native'

import { colors, spacing } from '../lib/theme'

export const CREDITS_TEXT =
  'Uses publicly available CMU web pages and public campus APIs, including open ' +
  'APIs published by ScottyLabs (e.g. Courses). We are not affiliated with ScottyLabs.'

export function Credits() {
  return <Text style={styles.credits}>{CREDITS_TEXT}</Text>
}

const styles = StyleSheet.create({
  credits: {
    fontSize: 12,
    lineHeight: 18,
    color: colors.textMuted,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: spacing.md,
    marginTop: spacing.xl,
  },
})
