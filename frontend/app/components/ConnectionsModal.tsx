/**
 * The "Your connections" modal — link a personal source so the planner can
 * answer from the student's own courses and deadlines (B5 / F4).
 *
 * The forms mirror the backend's CREDENTIAL_FIELDS (apps/personal/models.py):
 * Canvas and Ed take one revocable token; Piazza and Gradescope take a real CMU
 * email and password, which the row says plainly rather than dressing up as a
 * token (PRD §7, docs/b5-piazza-gradescope.md); Stellic is a labelled mock and
 * connects with nothing.
 *
 * A credential only ever travels one way — into `connect()`. Nothing here reads
 * one back, because no response carries one; the modal shows provider, status
 * and freshness only.
 */

import { useEffect, useMemo, useState } from 'react'
import {
  ActivityIndicator,
  Linking,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  useWindowDimensions,
  View,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { ApiError, connect, disconnect, fetchConnections } from '../lib/api'
import { colors, radius, shadows, spacing, WIDE_BREAKPOINT } from '../lib/theme'
import type { Connection, Provider } from '../lib/types'
import { HoverPressable } from './HoverPressable'

type AuthKind = 'token' | 'password' | 'none'

type ProviderMeta = {
  provider: Provider
  label: string
  icon: string
  kind: AuthKind
  blurb: string
  help?: { text: string; url: string }
  mock?: boolean
}

/** Order and copy of the source list. Kinds mirror the backend's credential shapes. */
const PROVIDERS: ProviderMeta[] = [
  {
    provider: 'canvas',
    label: 'Canvas',
    icon: '🎓',
    kind: 'token',
    blurb: 'Courses, assignments and due dates',
    help: {
      text: 'Canvas → Account → Settings → + New Access Token',
      url: 'https://canvas.cmu.edu/profile/settings',
    },
  },
  {
    provider: 'ed',
    label: 'Ed Discussion',
    icon: '💬',
    kind: 'token',
    blurb: 'Course threads and staff answers',
    help: { text: 'edstem.org → Settings → API tokens', url: 'https://edstem.org/us/settings/api-tokens' },
  },
  {
    provider: 'gradescope',
    label: 'Gradescope',
    icon: '📄',
    kind: 'password',
    blurb: 'Assignments, submissions and grades',
  },
  {
    provider: 'piazza',
    label: 'Piazza',
    icon: '🗣️',
    kind: 'password',
    blurb: 'Your class Q&A',
  },
  {
    provider: 'stellic',
    label: 'Stellic',
    icon: '🎯',
    kind: 'none',
    blurb: 'Degree-audit progress',
    mock: true,
  },
]

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (seconds < 60) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

type Props = {
  visible: boolean
  onClose: () => void
  /** So the profile row can show "N linked" without its own fetch. */
  onCountChange?: (count: number) => void
}

export function ConnectionsModal({ visible, onClose, onCountChange }: Props) {
  const { width } = useWindowDimensions()
  const insets = useSafeAreaInsets()
  const isWide = width >= WIDE_BREAKPOINT

  // null while the first load is in flight; [] is a real "nothing connected".
  const [connections, setConnections] = useState<Connection[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [openForm, setOpenForm] = useState<Provider | null>(null)
  const [confirmOff, setConfirmOff] = useState<Provider | null>(null)
  const [busy, setBusy] = useState<Provider | null>(null)
  const [rowError, setRowError] = useState<Partial<Record<Provider, string>>>({})

  // Credential fields, cleared whenever a different form opens or the modal closes
  // — a password should never outlive the row that asked for it.
  const [token, setToken] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')

  const byProvider = useMemo(() => {
    const map = new Map<Provider, Connection>()
    for (const connection of connections ?? []) map.set(connection.provider, connection)
    return map
  }, [connections])

  useEffect(() => {
    if (!visible) return
    let cancelled = false
    setLoadError(null)
    setConnections(null)
    fetchConnections()
      .then((list) => {
        if (!cancelled) setConnections(list)
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Could not load connections.')
      })
    return () => {
      cancelled = true
    }
  }, [visible])

  useEffect(() => {
    if (connections) onCountChange?.(connections.length)
  }, [connections, onCountChange])

  const resetForm = () => {
    setToken('')
    setEmail('')
    setPassword('')
    setConfirmOff(null)
  }

  const startForm = (provider: Provider) => {
    resetForm()
    setRowError((prev) => ({ ...prev, [provider]: undefined }))
    setOpenForm((current) => (current === provider ? null : provider))
  }

  const applyResult = (updated: Connection) => {
    setConnections((current) => {
      const rest = (current ?? []).filter((c) => c.provider !== updated.provider)
      return [...rest, updated]
    })
  }

  const handleConnect = async (meta: ProviderMeta) => {
    const credential: Record<string, string> =
      meta.kind === 'token'
        ? { token }
        : meta.kind === 'password'
          ? { email, password }
          : {}
    setBusy(meta.provider)
    setRowError((prev) => ({ ...prev, [meta.provider]: undefined }))
    try {
      const result = await connect(meta.provider, credential)
      applyResult(result)
      setOpenForm(null)
      resetForm()
    } catch (err) {
      setRowError((prev) => ({
        ...prev,
        [meta.provider]: err instanceof ApiError ? err.message : 'Could not connect.',
      }))
    } finally {
      setBusy(null)
    }
  }

  const handleDisconnect = async (provider: Provider) => {
    setBusy(provider)
    setRowError((prev) => ({ ...prev, [provider]: undefined }))
    try {
      await disconnect(provider)
      setConnections((current) => (current ?? []).filter((c) => c.provider !== provider))
      setConfirmOff(null)
    } catch (err) {
      setRowError((prev) => ({
        ...prev,
        [provider]: err instanceof ApiError ? err.message : 'Could not disconnect.',
      }))
    } finally {
      setBusy(null)
    }
  }

  const canSubmit = (meta: ProviderMeta): boolean => {
    if (meta.kind === 'token') return token.trim().length > 0
    if (meta.kind === 'password') return email.trim().length > 0 && password.length > 0
    return true
  }

  const close = () => {
    setOpenForm(null)
    resetForm()
    setRowError({})
    onClose()
  }

  return (
    <Modal visible={visible} transparent animationType={isWide ? 'fade' : 'slide'} onRequestClose={close}>
      <View style={styles.root}>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="Close connections" />

        <View
          style={[
            styles.card,
            isWide ? styles.cardWide : styles.cardSheet,
            !isWide && { paddingBottom: insets.bottom + spacing.lg },
          ]}
        >
          <View style={styles.header}>
            <Text style={styles.title}>Your connections</Text>
            <Pressable onPress={close} accessibilityRole="button" accessibilityLabel="Close">
              <Text style={styles.close}>✕</Text>
            </Pressable>
          </View>
          <Text style={styles.subtitle}>
            Link an account so Scotty can answer from your own courses, deadlines and grades.
            Credentials are encrypted and never shown again.
          </Text>

          {connections === null && !loadError ? (
            <View style={styles.loading}>
              <ActivityIndicator color={colors.accent} />
            </View>
          ) : loadError ? (
            <Text style={styles.loadError}>{loadError}</Text>
          ) : (
            <ScrollView style={styles.list} contentContainerStyle={styles.listContent}>
              {PROVIDERS.map((meta) => {
                const connection = byProvider.get(meta.provider)
                const isOpen = openForm === meta.provider
                const isBusy = busy === meta.provider
                const error = rowError[meta.provider]

                return (
                  <View key={meta.provider} style={styles.row}>
                    <View style={styles.rowTop}>
                      <Text style={styles.icon}>{meta.icon}</Text>
                      <View style={styles.rowText}>
                        <View style={styles.nameLine}>
                          <Text style={styles.name}>{meta.label}</Text>
                          {meta.mock ? (
                            <Text style={styles.mockBadge}>MOCK</Text>
                          ) : null}
                        </View>
                        <Text style={styles.status}>
                          {connection
                            ? connection.last_sync_at
                              ? `Connected · synced ${relativeTime(connection.last_sync_at)}`
                              : 'Connected'
                            : meta.blurb}
                        </Text>
                      </View>

                      {connection ? (
                        confirmOff === meta.provider ? null : (
                          <HoverPressable
                            style={({ hovered, pressed }) => [
                              styles.actionGhost,
                              (hovered || pressed) && styles.actionGhostActive,
                            ]}
                            onPress={() => setConfirmOff(meta.provider)}
                            accessibilityRole="button"
                          >
                            <Text style={styles.actionGhostText}>Disconnect</Text>
                          </HoverPressable>
                        )
                      ) : (
                        <HoverPressable
                          style={({ hovered, pressed }) => [
                            styles.action,
                            (hovered || pressed) && styles.actionActive,
                          ]}
                          onPress={() => startForm(meta.provider)}
                          accessibilityRole="button"
                        >
                          <Text style={styles.actionText}>{isOpen ? 'Cancel' : 'Connect'}</Text>
                        </HoverPressable>
                      )}
                    </View>

                    {/* Inline disconnect confirmation — cross-platform, unlike a
                        native Alert which does not render on web. */}
                    {confirmOff === meta.provider ? (
                      <View style={styles.confirm}>
                        <Text style={styles.confirmText}>
                          Remove {meta.label} and everything synced from it?
                        </Text>
                        <View style={styles.confirmActions}>
                          <Pressable onPress={() => setConfirmOff(null)} accessibilityRole="button">
                            <Text style={styles.linkMuted}>Cancel</Text>
                          </Pressable>
                          <HoverPressable
                            style={({ hovered, pressed }) => [
                              styles.danger,
                              (hovered || pressed) && styles.dangerActive,
                            ]}
                            onPress={() => handleDisconnect(meta.provider)}
                            disabled={isBusy}
                            accessibilityRole="button"
                          >
                            <Text style={styles.dangerText}>{isBusy ? 'Removing…' : 'Remove'}</Text>
                          </HoverPressable>
                        </View>
                      </View>
                    ) : null}

                    {isOpen && !connection ? (
                      <View style={styles.form}>
                        {meta.kind === 'password' ? (
                          <Text style={styles.warn}>
                            ⚠ This signs in with your real CMU email and password and stores them
                            (encrypted) — not a revocable token. {meta.label} issues no token, so
                            this is the only way in.
                          </Text>
                        ) : null}

                        {meta.kind === 'token' ? (
                          <>
                            <Text style={styles.fieldLabel}>Access token</Text>
                            <TextInput
                              style={styles.input}
                              value={token}
                              onChangeText={setToken}
                              placeholder="Paste your token"
                              placeholderTextColor={colors.textFaint}
                              autoCapitalize="none"
                              autoCorrect={false}
                              editable={!isBusy}
                            />
                            {meta.help ? (
                              <Pressable onPress={() => Linking.openURL(meta.help!.url)}>
                                <Text style={styles.help}>{meta.help.text} ↗</Text>
                              </Pressable>
                            ) : null}
                          </>
                        ) : null}

                        {meta.kind === 'password' ? (
                          <>
                            <Text style={styles.fieldLabel}>CMU email</Text>
                            <TextInput
                              style={styles.input}
                              value={email}
                              onChangeText={setEmail}
                              placeholder="you@andrew.cmu.edu"
                              placeholderTextColor={colors.textFaint}
                              autoCapitalize="none"
                              autoCorrect={false}
                              keyboardType="email-address"
                              editable={!isBusy}
                            />
                            <Text style={styles.fieldLabel}>Password</Text>
                            <TextInput
                              style={styles.input}
                              value={password}
                              onChangeText={setPassword}
                              placeholder="Your CMU password"
                              placeholderTextColor={colors.textFaint}
                              secureTextEntry
                              autoCapitalize="none"
                              autoCorrect={false}
                              editable={!isBusy}
                            />
                          </>
                        ) : null}

                        {meta.kind === 'none' ? (
                          <Text style={styles.warn}>
                            Stellic connects with placeholder data — every answer from it is
                            labelled a mock, not your real record.
                          </Text>
                        ) : null}

                        <View style={styles.formActions}>
                          <Pressable
                            onPress={() => {
                              setOpenForm(null)
                              resetForm()
                            }}
                            accessibilityRole="button"
                          >
                            <Text style={styles.linkMuted}>Cancel</Text>
                          </Pressable>
                          <HoverPressable
                            style={({ hovered, pressed }) => [
                              styles.submit,
                              (hovered || pressed) && styles.submitActive,
                              (!canSubmit(meta) || isBusy) && styles.submitDisabled,
                            ]}
                            onPress={() => handleConnect(meta)}
                            disabled={!canSubmit(meta) || isBusy}
                            accessibilityRole="button"
                          >
                            <Text style={styles.submitText}>{isBusy ? 'Connecting…' : 'Connect'}</Text>
                          </HoverPressable>
                        </View>
                      </View>
                    ) : null}

                    {error ? <Text style={styles.rowError}>{error}</Text> : null}
                  </View>
                )
              })}
            </ScrollView>
          )}
        </View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: colors.overlay,
    justifyContent: 'center',
    alignItems: 'center',
  },
  card: {
    backgroundColor: colors.background,
    ...shadows.soft,
  },
  cardWide: {
    width: 440,
    maxHeight: '82%',
    borderRadius: radius.xl,
    padding: spacing.xl,
  },
  cardSheet: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    maxHeight: '88%',
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.xl,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  close: {
    fontSize: 16,
    color: colors.textMuted,
    padding: spacing.xs,
  },
  subtitle: {
    fontSize: 13,
    lineHeight: 19,
    color: colors.textMuted,
    marginTop: spacing.xs,
    marginBottom: spacing.lg,
  },
  loading: {
    paddingVertical: spacing.xl,
    alignItems: 'center',
  },
  loadError: {
    fontSize: 13,
    color: colors.error,
    paddingVertical: spacing.lg,
  },
  list: {
    flexGrow: 0,
  },
  listContent: {
    gap: spacing.sm,
  },
  row: {
    borderWidth: 1,
    borderColor: colors.borderSoft,
    borderRadius: radius.lg,
    backgroundColor: colors.surface,
    padding: spacing.md,
  },
  rowTop: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  icon: {
    fontSize: 22,
  },
  rowText: {
    flex: 1,
  },
  nameLine: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  name: {
    fontSize: 15,
    fontWeight: '600',
    color: colors.text,
  },
  mockBadge: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
    color: colors.mockBadge,
    borderWidth: 1,
    borderColor: colors.mockBadge,
    borderRadius: radius.sm,
    paddingHorizontal: 4,
    paddingVertical: 1,
    overflow: 'hidden',
  },
  status: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 2,
  },
  action: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  actionActive: {
    opacity: 0.85,
  },
  actionText: {
    color: colors.accentText,
    fontSize: 13,
    fontWeight: '600',
  },
  actionGhost: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  actionGhostActive: {
    backgroundColor: colors.sidebarHover,
  },
  actionGhostText: {
    color: colors.textMuted,
    fontSize: 13,
    fontWeight: '600',
  },
  form: {
    marginTop: spacing.md,
    gap: spacing.xs,
  },
  warn: {
    fontSize: 12,
    lineHeight: 18,
    color: colors.mockBadge,
    backgroundColor: 'rgba(138, 90, 31, 0.08)',
    borderRadius: radius.sm,
    padding: spacing.sm,
    marginBottom: spacing.xs,
  },
  fieldLabel: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: spacing.xs,
  },
  input: {
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    fontSize: 14,
    color: colors.text,
  },
  help: {
    fontSize: 12,
    color: colors.textFaint,
    marginTop: spacing.xs,
  },
  formActions: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: spacing.lg,
    marginTop: spacing.sm,
  },
  linkMuted: {
    fontSize: 13,
    color: colors.textMuted,
    fontWeight: '600',
  },
  submit: {
    backgroundColor: colors.accent,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.lg,
  },
  submitActive: {
    opacity: 0.85,
  },
  submitDisabled: {
    opacity: 0.4,
  },
  submitText: {
    color: colors.accentText,
    fontSize: 13,
    fontWeight: '600',
  },
  confirm: {
    marginTop: spacing.md,
    gap: spacing.sm,
  },
  confirmText: {
    fontSize: 13,
    color: colors.text,
  },
  confirmActions: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: spacing.lg,
  },
  danger: {
    backgroundColor: colors.error,
    borderRadius: radius.md,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  dangerActive: {
    opacity: 0.85,
  },
  dangerText: {
    color: colors.accentText,
    fontSize: 13,
    fontWeight: '600',
  },
  rowError: {
    fontSize: 12,
    color: colors.error,
    marginTop: spacing.sm,
  },
})
