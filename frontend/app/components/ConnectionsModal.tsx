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

import { router } from 'expo-router'
import * as ImagePicker from 'expo-image-picker'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import {
  ActivityIndicator,
  Image,
  Keyboard,
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
import Animated, {
  runOnJS,
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated'
import { useSafeAreaInsets } from 'react-native-safe-area-context'

import { ApiError, connect, disconnect, fetchConnections } from '../lib/api'
import { type SavedAccount, getSavedAccounts, removeAccount, saveAccount } from '../lib/accounts'
import { durations, easing, offsets, useReducedMotion } from '../lib/motion'
import { getSessionId, resetSessionId, setSessionId } from '../lib/session'
import { colors, radius, shadows, spacing, WIDE_BREAKPOINT } from '../lib/theme'
import type { Connection, Provider } from '../lib/types'
import { setDisplayName, setProfilePicture, useCurrentUser } from '../lib/user'
import { HoverPressable } from './HoverPressable'

const AnimatedPressable = Animated.createAnimatedComponent(Pressable)

/**
 * Height-and-fade reveal for a connect form — the "dropdown opening" motion.
 * Measures its content once, invisibly and out of flow, then animates a clipped
 * wrapper from zero to that height so the row grows into the form rather than
 * snapping open. Same reanimated primitives the rest of the app uses (lib/motion).
 */
function Collapsible({ children }: { children: ReactNode }) {
  const reduceMotion = useReducedMotion()
  const [measured, setMeasured] = useState<number | null>(null)
  const progress = useSharedValue(0)

  useEffect(() => {
    if (measured == null) return
    progress.value = reduceMotion ? 1 : withTiming(1, { duration: durations.base, easing })
  }, [measured, reduceMotion, progress])

  const style = useAnimatedStyle(() => ({
    opacity: progress.value,
    height: measured == null ? 0 : progress.value * measured,
  }))

  return (
    <Animated.View style={[styles.collapsible, style]}>
      <View
        // Measured absolutely and invisibly first, so the wrapper starts at 0
        // instead of flashing full height before it collapses.
        style={measured == null ? styles.measure : undefined}
        onLayout={(event) => {
          if (measured == null) setMeasured(event.nativeEvent.layout.height)
        }}
      >
        {children}
      </View>
    </Animated.View>
  )
}

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
  const reduceMotion = useReducedMotion()
  const { displayName, profilePicture } = useCurrentUser()

  // The card pulls up and the backdrop fades in on open, and reverses on close.
  // `mounted` keeps the Modal in the tree through the exit so it can animate out
  // before unmounting — Modal drops its children instantly otherwise.
  const enter = useSharedValue(0)
  const [mounted, setMounted] = useState(visible)
  useEffect(() => {
    if (visible) {
      setMounted(true)
      enter.value = reduceMotion ? 1 : withTiming(1, { duration: durations.entrance, easing })
    } else if (mounted) {
      if (reduceMotion) {
        setMounted(false)
        return
      }
      enter.value = withTiming(0, { duration: durations.base, easing }, (finished) => {
        if (finished) runOnJS(setMounted)(false)
      })
    }
  }, [visible, mounted, reduceMotion, enter])

  const rise = isWide ? offsets.view : 40
  const backdropStyle = useAnimatedStyle(() => ({ opacity: enter.value }))
  const cardStyle = useAnimatedStyle(() => ({
    opacity: enter.value,
    transform: [{ translateY: (1 - enter.value) * rise }],
  }))

  // null while the first load is in flight; [] is a real "nothing connected".
  const [connections, setConnections] = useState<Connection[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [openForm, setOpenForm] = useState<Provider | null>(null)
  const [confirmOff, setConfirmOff] = useState<Provider | null>(null)
  const [busy, setBusy] = useState<Provider | null>(null)
  const [rowError, setRowError] = useState<Partial<Record<Provider, string>>>({})

  const [nameInput, setNameInput] = useState(displayName)
  const [pictureInput, setPictureInput] = useState(profilePicture ?? '')
  const [savedAccounts, setSavedAccounts] = useState<SavedAccount[]>([])
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)

  // Pre-fill with the saved name/picture each time the modal opens.
  // Intentionally excludes displayName/profilePicture from deps — we don't want
  // to overwrite in-progress edits while the modal is already open.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (visible) { setNameInput(displayName); setPictureInput(profilePicture ?? '') } }, [visible])

  const handleSaveName = async () => {
    const sid = await getSessionId()
    await setDisplayName(nameInput.trim())
    await saveAccount(sid, nameInput.trim(), pictureInput)
    Keyboard.dismiss()
  }

  const handlePickPhoto = async () => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ImagePicker.MediaTypeOptions.Images,
      allowsEditing: true,
      aspect: [1, 1],
      quality: 0.6,
      base64: true,
    })
    if (!result.canceled && result.assets[0]) {
      const uri = `data:image/jpeg;base64,${result.assets[0].base64}`
      setPictureInput(uri)
      await setProfilePicture(uri)
    }
  }

  const handleNewAccount = async () => {
    const sid = await getSessionId()
    await saveAccount(sid, displayName, pictureInput)
    await resetSessionId()
    await setDisplayName('')
    await setProfilePicture('')
    setNameInput('')
    setPictureInput('')
    close()
    router.replace('/')
  }

  const handleSwitchToAccount = async (account: SavedAccount) => {
    const sid = await getSessionId()
    await saveAccount(sid, displayName, pictureInput)
    await setSessionId(account.sessionId)
    await setDisplayName(account.displayName)
    await setProfilePicture(account.profilePicture ?? '')
    close()
    router.replace('/')
  }

  const handleRemoveAccount = async (account: SavedAccount) => {
    await removeAccount(account.sessionId)
    setSavedAccounts((prev) => prev.filter((a) => a.sessionId !== account.sessionId))
  }

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
      .then((list) => { if (!cancelled) setConnections(list) })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof ApiError ? err.message : 'Could not load connections.')
      })

    Promise.all([getSavedAccounts(), getSessionId()]).then(([accounts, sid]) => {
      if (cancelled) return
      setSavedAccounts(accounts)
      setCurrentSessionId(sid)
    })

    return () => { cancelled = true }
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
    <Modal visible={mounted} transparent animationType="none" onRequestClose={close}>
      <View style={styles.root}>
        {/* Reanimated drives the entrance rather than Modal's animationType, so
            the backdrop fade and the card rise share the app's motion tokens. */}
        <AnimatedPressable
          style={[StyleSheet.absoluteFill, styles.backdrop, backdropStyle]}
          onPress={close}
          accessibilityLabel="Close connections"
        />

        <Animated.View
          style={[
            styles.card,
            isWide ? styles.cardWide : styles.cardSheet,
            !isWide && { paddingBottom: insets.bottom + spacing.lg },
            cardStyle,
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

          <View style={styles.profileSection}>
            <View style={styles.avatarWrap}>
              {pictureInput ? (
                <Image source={{ uri: pictureInput }} style={styles.photoAvatar} />
              ) : (
                <View style={[styles.photoAvatar, styles.photoAvatarPlaceholder]}>
                  <Text style={styles.photoAvatarInitial}>
                    {(nameInput || displayName).slice(0, 1).toUpperCase() || '?'}
                  </Text>
                </View>
              )}
              <Pressable onPress={handlePickPhoto} style={styles.photoEditBtn} accessibilityRole="button">
                <Text style={styles.photoEditBtnText}>Edit photo</Text>
              </Pressable>
            </View>
            <Text style={styles.fieldLabel}>Display name</Text>
            <View style={styles.profileRow}>
              <TextInput
                style={[styles.input, styles.nameInput]}
                value={nameInput}
                onChangeText={setNameInput}
                placeholder="Your name"
                placeholderTextColor={colors.textFaint}
                autoCapitalize="words"
                autoCorrect={false}
                returnKeyType="done"
                onSubmitEditing={handleSaveName}
              />
              <HoverPressable
                style={({ hovered, pressed }) => [
                  styles.action,
                  (hovered || pressed) && styles.actionActive,
                ]}
                onPress={handleSaveName}
                accessibilityRole="button"
              >
                <Text style={styles.actionText}>Save</Text>
              </HoverPressable>
            </View>
          </View>
          <View style={styles.divider} />

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
                      <Collapsible>
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
                              secureTextEntry
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
                      </Collapsible>
                    ) : null}

                    {error ? <Text style={styles.rowError}>{error}</Text> : null}
                  </View>
                )
              })}
            </ScrollView>
          )}

          <View style={styles.divider} />
          <Text style={styles.accountsLabel}>Accounts</Text>

          {/* Current session row */}
          <View style={styles.accountRow}>
            {pictureInput ? (
              <Image source={{ uri: pictureInput }} style={styles.photoAvatarSmall} />
            ) : (
              <View style={[styles.photoAvatarSmall, styles.photoAvatarPlaceholder]}>
                <Text style={styles.photoAvatarSmallInitial}>
                  {(displayName || '?').slice(0, 1).toUpperCase()}
                </Text>
              </View>
            )}
            <Text style={[styles.accountName, { marginLeft: spacing.sm }]}>
              {displayName || 'Unnamed account'}{' '}
              <Text style={styles.accountYou}>(you)</Text>
            </Text>
          </View>

          {/* Saved accounts (excluding the current session) */}
          {savedAccounts
            .filter((a) => a.sessionId !== currentSessionId)
            .map((account) => (
              <View key={account.sessionId} style={styles.accountRow}>
                {account.profilePicture ? (
                  <Image source={{ uri: account.profilePicture }} style={styles.photoAvatarSmall} />
                ) : (
                  <View style={[styles.photoAvatarSmall, styles.photoAvatarPlaceholder]}>
                    <Text style={styles.photoAvatarSmallInitial}>
                      {(account.displayName || '?').slice(0, 1).toUpperCase()}
                    </Text>
                  </View>
                )}
                <Text style={[styles.accountName, { marginLeft: spacing.sm }]}>{account.displayName || 'Unnamed account'}</Text>
                <View style={styles.accountActions}>
                  <Pressable
                    onPress={() => handleRemoveAccount(account)}
                    accessibilityRole="button"
                  >
                    <Text style={styles.linkMuted}>Remove</Text>
                  </Pressable>
                  <HoverPressable
                    style={({ hovered, pressed }) => [
                      styles.action,
                      (hovered || pressed) && styles.actionActive,
                    ]}
                    onPress={() => handleSwitchToAccount(account)}
                    accessibilityRole="button"
                  >
                    <Text style={styles.actionText}>Switch</Text>
                  </HoverPressable>
                </View>
              </View>
            ))}

          <HoverPressable
            style={({ hovered, pressed }) => [
              styles.switchRow,
              (hovered || pressed) && styles.actionActive,
            ]}
            onPress={handleNewAccount}
            accessibilityRole="button"
          >
            <Text style={styles.switchText}>+ New account</Text>
          </HoverPressable>
        </Animated.View>
      </View>
    </Modal>
  )
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  // The overlay tint lives here, not on root, so its opacity can animate in.
  backdrop: {
    backgroundColor: colors.overlay,
  },
  collapsible: {
    overflow: 'hidden',
  },
  measure: {
    position: 'absolute',
    left: 0,
    right: 0,
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
  profileSection: {
    gap: spacing.xs,
  },
  avatarWrap: {
    alignItems: 'center',
    marginBottom: spacing.md,
  },
  photoAvatar: {
    width: 80,
    height: 80,
    borderRadius: 40,
  },
  photoAvatarPlaceholder: {
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
  },
  photoAvatarInitial: {
    color: colors.accentText,
    fontSize: 32,
    fontWeight: '700',
  },
  photoAvatarSmall: {
    width: 28,
    height: 28,
    borderRadius: 14,
    flexShrink: 0,
  },
  photoAvatarSmallInitial: {
    color: colors.accentText,
    fontSize: 12,
    fontWeight: '700',
  },
  photoEditBtn: {
    marginTop: spacing.xs,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
  },
  photoEditBtnText: {
    fontSize: 12,
    color: colors.accent,
    fontWeight: '600',
  },
  profileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
  },
  nameInput: {
    flex: 1,
  },
  divider: {
    height: 1,
    backgroundColor: colors.borderSoft,
    marginVertical: spacing.md,
  },
  accountsLabel: {
    fontSize: 11,
    fontWeight: '600',
    letterSpacing: 0.5,
    color: colors.textFaint,
    textTransform: 'uppercase',
    marginBottom: spacing.xs,
  },
  accountRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: spacing.xs,
  },
  accountName: {
    fontSize: 13,
    color: colors.text,
    fontWeight: '500',
    flex: 1,
  },
  accountYou: {
    color: colors.textMuted,
    fontWeight: '400',
  },
  accountActions: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.md,
  },
  switchRow: {
    paddingVertical: spacing.xs,
    marginTop: spacing.xs,
  },
  switchText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.accent,
  },
})
