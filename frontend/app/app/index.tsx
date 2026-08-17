/**
 * The ask screen — the whole app right now.
 *
 * Chat state (messages, composer text, send/streaming) belongs to assistant-ui's
 * runtime. Our own multi-thread history is layered on top of it, because
 * assistant-ui's thread list needs a runtime we don't use — see lib/chatThreads.ts.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
  useWindowDimensions,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import Animated, { useAnimatedStyle, useSharedValue, withTiming } from 'react-native-reanimated'
import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  AssistantRuntimeProvider,
  ThreadPrimitive as Thread,
  generateId,
  useAuiState,
  useLocalRuntime,
  type ThreadMessageLike,
} from '@assistant-ui/react-native'

import type { Mode } from '../lib/types'
import { AskComposer } from '../components/AskComposer'
import { ChatMessage } from '../components/ChatMessage'
import { useCitationOverlay } from '../components/CitationOverlay'
import { HoverPressable } from '../components/HoverPressable'
import { TypingIndicator } from '../components/TypingIndicator'
import { createHttpAdapter } from '../lib/assistantAdapter'
import {
  type ChatThread,
  createEmptyThread,
  loadThreads,
  persistThread,
  removeThread,
  threadTitle,
} from '../lib/chatThreads'
import { durations, easing, offsets, useReducedMotion } from '../lib/motion'
import { colors, radius, shadows, spacing, WIDE_BREAKPOINT } from '../lib/theme'
import { useCurrentUser } from '../lib/user'

/** The PRD's signature multi-hop demo query, pre-filled so demos are one tap. */
const DEMO_QUERY =
  'I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then ' +
  'an interesting startup or AI event before 8.'

const DISABLED_MODES_KEY = 'askscotty.disabledModes'
// Everything on until someone unchecks it — an empty deny list.
const DEFAULT_DISABLED_MODES: Mode[] = []
const SIDEBAR_WIDTH = 280

const SAVE_DEBOUNCE_MS = 600

/** Matches `Thread.title`'s column width in backend/apps/core/models.py. */
const TITLE_MAX = 120

/**
 * What counts as "this thread changed" for the save debounce. Covers the title
 * as well as the messages, or renaming without sending a message would compare
 * equal to the last save and never persist.
 */
function fingerprintOf(thread: ChatThread): string {
  return JSON.stringify([thread.title, thread.messages])
}

/**
 * The sidebar stays mounted when closed so the closing half of the animation
 * has something to play on, which otherwise leaves it reachable by tab and by
 * screen reader while it is off-screen.
 */
function hiddenWhenClosed(open: boolean) {
  return {
    pointerEvents: open ? ('auto' as const) : ('none' as const),
    accessibilityElementsHidden: !open,
    importantForAccessibility: open ? ('auto' as const) : ('no-hide-descendants' as const),
  }
}

// The source filter is per-device UI state, so it stays on the device — in
// AsyncStorage, not localStorage, because `window` does not exist on a phone.
// Conversations are not stored here: they live in the backend, scoped to this
// session (see lib/chatThreads.ts).
async function loadDisabledModes(): Promise<Mode[]> {
  try {
    const raw = await AsyncStorage.getItem(DISABLED_MODES_KEY)
    return raw ? (JSON.parse(raw) as Mode[]) : DEFAULT_DISABLED_MODES
  } catch (e) {
    return DEFAULT_DISABLED_MODES
  }
}

async function saveDisabledModes(modes: Mode[]): Promise<void> {
  try {
    await AsyncStorage.setItem(DISABLED_MODES_KEY, JSON.stringify(modes))
  } catch (e) {
    // Storage full or unavailable — a forgotten filter is not worth an error.
  }
}

export default function AskScreen() {
  const insets = useSafeAreaInsets()
  const { width } = useWindowDimensions()
  const isWide = width >= WIDE_BREAKPOINT
  const user = useCurrentUser()
  const { close: closeCitation } = useCitationOverlay()

  const [disabledModes, setDisabledModes] = useState<Mode[]>(DEFAULT_DISABLED_MODES)
  const disabledModesRef = useRef(disabledModes)
  useEffect(() => {
    disabledModesRef.current = disabledModes
  }, [disabledModes])

  // Without the flag, the write effect would immediately save back whatever the
  // read just returned — harmless, but confusing to follow in the storage log.
  const disabledModesLoaded = useRef(false)
  useEffect(() => {
    loadDisabledModes().then((stored) => {
      disabledModesLoaded.current = true
      setDisabledModes(stored)
    })
  }, [])
  useEffect(() => {
    if (disabledModesLoaded.current) void saveDisabledModes(disabledModes)
  }, [disabledModes])

  // `null` means "no explicit choice yet": follow the width-based default until
  // the toggle is tapped, so resizing doesn't fight a stale manual override.
  const [sidebarOpen, setSidebarOpen] = useState<boolean | null>(null)
  const sidebarEffectiveOpen = sidebarOpen ?? isWide
  const [searchQuery, setSearchQuery] = useState('')

  const reduceMotion = useReducedMotion()

  // One 0→1 value drives both layouts: the track's width when the sidebar is
  // inline, the panel's offset when it is a drawer.
  const sidebarProgress = useSharedValue(sidebarEffectiveOpen ? 1 : 0)
  useEffect(() => {
    const target = sidebarEffectiveOpen ? 1 : 0
    sidebarProgress.value = reduceMotion
      ? target
      : withTiming(target, { duration: durations.sidebar, easing })
  }, [sidebarEffectiveOpen, reduceMotion, sidebarProgress])

  // Width rather than a transform, because the main column is flex:1 — animating
  // the track is what makes the thread area follow the sidebar instead of
  // snapping across once it lands.
  const sidebarTrackStyle = useAnimatedStyle(() => ({
    width: sidebarProgress.value * SIDEBAR_WIDTH,
  }))

  // The panel keeps its full width and slides, so its contents never reflow
  // mid-animation. What overhangs is off the left edge of the screen.
  const sidebarPanelStyle = useAnimatedStyle(() => ({
    transform: [{ translateX: (sidebarProgress.value - 1) * SIDEBAR_WIDTH }],
  }))

  const drawerBackdropStyle = useAnimatedStyle(() => ({
    opacity: sidebarProgress.value,
  }))

  // Which row's "..." menu is open, and which row is being renamed in place.
  // Both are hand-rolled: @assistant-ui/react-native ships no menu primitive
  // (ThreadListItemMorePrimitive is web-only), and its ThreadListItem.Delete
  // is wired to a local-runtime stub that throws.
  const [menuThreadId, setMenuThreadId] = useState<string | null>(null)
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameDraft, setRenameDraft] = useState('')

  // The app opens on a fresh chat every time. Saved conversations arrive a
  // moment later and fill the sidebar rather than yanking the runtime out from
  // under someone who has already started typing.
  const firstThread = useMemo(() => createEmptyThread(generateId()), [])
  const [threads, setThreads] = useState<ChatThread[]>([firstThread])
  const [activeThreadId, setActiveThreadId] = useState(firstThread.id)
  const activeThreadIdRef = useRef(activeThreadId)

  // The runtime subscription below is set up once, so it needs a ref to read
  // the current title rather than the one from its first render.
  const threadsRef = useRef(threads)
  useEffect(() => {
    threadsRef.current = threads
  }, [threads])

  // Both read through refs at request time rather than closed over once, so the
  // adapter sees the current filter and the current conversation without being
  // rebuilt — which would drop the in-flight answer.
  const adapter = useMemo(
    () => createHttpAdapter(() => disabledModesRef.current, () => activeThreadIdRef.current),
    [],
  )
  const runtime = useLocalRuntime(adapter, { initialMessages: [] })

  // Debounced because the runtime fires its subscription on every status change,
  // not just a finished turn — unthrottled, that PUTs the whole thread several
  // times per answer. Pending threads sit in a map rather than one slot so
  // switching conversations mid-debounce cannot drop the one being left behind.
  const pendingSaves = useRef(new Map<string, ChatThread>())
  const lastSaved = useRef(new Map<string, string>())
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flushSaves = useCallback(() => {
    const batch = [...pendingSaves.current.values()]
    pendingSaves.current.clear()

    for (const thread of batch) {
      const fingerprint = fingerprintOf(thread)
      lastSaved.current.set(thread.id, fingerprint)
      persistThread(thread).catch(() => {
        // Dropping the fingerprint makes the next change retry this thread. A
        // silent retry beats a red banner mid-demo over a network blip.
        lastSaved.current.delete(thread.id)
      })
    }
  }, [])

  const schedulePersist = useCallback(
    (thread: ChatThread) => {
      // Never persist an empty thread, or "New Chat" would create a server row
      // for a conversation that never happened. Renaming one therefore stays
      // local until it has a first message, which then carries the title up.
      if (thread.messages.length === 0) return
      if (lastSaved.current.get(thread.id) === fingerprintOf(thread)) return

      pendingSaves.current.set(thread.id, thread)
      if (saveTimer.current) clearTimeout(saveTimer.current)
      saveTimer.current = setTimeout(flushSaves, SAVE_DEBOUNCE_MS)
    },
    [flushSaves],
  )

  // Closing the tab mid-debounce should still save.
  useEffect(() => {
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current)
      flushSaves()
    }
  }, [flushSaves])

  useEffect(() => {
    let cancelled = false

    loadThreads()
      .then((saved) => {
        if (cancelled || saved.length === 0) return
        setThreads((prev) => {
          // Keep the chat we opened with only while it is untouched, or the
          // user loses whatever they typed during the load.
          const current = prev.find((t) => t.id === activeThreadIdRef.current)
          const keepCurrent = current && current.messages.length === 0 ? [current] : []
          return [...keepCurrent, ...saved]
        })
      })
      .catch(() => {
        // No history is a usable app; a blocked one is not. The fresh chat
        // stays, and the next save retries.
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Hero-or-thread, driven by one state value rather than two <Thread.If>
  // instances: those subscribe to the runtime independently, and letting
  // Thread.MessagesFlatList's item list shrink to zero under it via
  // thread.reset() raced the FlatList's index bookkeeping and crashed.
  const [isEmpty, setIsEmpty] = useState(true)

  // The hero-to-thread swap is a hard cut on the app's most-watched moment, the
  // first send. Only the arriving side is animated: crossfading would mean two
  // AskComposers mounted at once, both bound to the same runtime composer.
  const threadEnter = useSharedValue(0)
  useEffect(() => {
    if (isEmpty) {
      threadEnter.value = 0
      return
    }
    threadEnter.value = reduceMotion ? 1 : withTiming(1, { duration: durations.entrance, easing })
  }, [isEmpty, reduceMotion, threadEnter])

  const threadEnterStyle = useAnimatedStyle(() => ({
    opacity: threadEnter.value,
    transform: [{ translateY: (1 - threadEnter.value) * offsets.view }],
  }))

  // Mirrors the live thread back into whichever thread is active, so switching
  // away and back loses nothing. Reads activeThreadIdRef rather than the state,
  // because this subscription is set up once and a ref is what stays current.
  useEffect(() => {
    return runtime.thread.subscribe(() => {
      const messages = runtime.thread.getState().messages
      setIsEmpty(messages.length === 0)
      const snapshot: ThreadMessageLike[] = messages.map((m) => ({ role: m.role, content: m.content }))
      const id = activeThreadIdRef.current
      const updatedAt = Date.now()
      // Carried through rather than defaulted, or every answer would overwrite
      // a rename with an empty title.
      const title = threadsRef.current.find((t) => t.id === id)?.title ?? ''

      setThreads((prev) =>
        prev.map((t) => (t.id === id ? { ...t, messages: snapshot, updatedAt } : t)),
      )
      // Outside the state updater on purpose: React may run an updater more
      // than once, and a save is a side effect that should happen once.
      schedulePersist({ id, messages: snapshot, title, updatedAt })
    })
  }, [runtime, schedulePersist])

  useEffect(() => {
    runtime.thread.composer.setText(DEMO_QUERY)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startNewChat = useCallback(() => {
    setMenuThreadId(null)
    setRenamingId(null)
    const current = threads.find((t) => t.id === activeThreadIdRef.current)
    if (current && current.messages.length === 0) return // already on a fresh chat
    const next = createEmptyThread(generateId())
    setThreads((prev) => [next, ...prev])
    activeThreadIdRef.current = next.id
    setActiveThreadId(next.id)
    runtime.thread.reset([])
    if (!isWide) setSidebarOpen(false)
  }, [threads, runtime, isWide])

  const startRename = useCallback((thread: ChatThread) => {
    setMenuThreadId(null)
    setRenamingId(thread.id)
    // Seeded with what the row currently shows, so renaming a never-renamed
    // thread starts from its derived title rather than an empty box.
    setRenameDraft(threadTitle(thread))
  }, [])

  const commitRename = useCallback(
    (id: string) => {
      setRenamingId(null)

      const title = renameDraft.trim().slice(0, TITLE_MAX)
      const current = threadsRef.current.find((t) => t.id === id)
      // Also the guard that makes a blur-then-submit double fire harmless.
      if (!current || current.title === title) return

      const renamed = { ...current, title }
      setThreads((prev) => prev.map((t) => (t.id === id ? renamed : t)))
      // The runtime subscription only fires on message changes, so a rename
      // has to schedule its own save.
      schedulePersist(renamed)
    },
    [renameDraft, schedulePersist],
  )

  const deleteThreadById = useCallback(
    (id: string) => {
      setMenuThreadId(null)

      // Drop the queued save before deleting, or a debounce still in flight
      // would PUT the thread straight back and recreate the row.
      pendingSaves.current.delete(id)
      lastSaved.current.delete(id)

      const remaining = threads.filter((t) => t.id !== id)

      // Deleting the conversation you are reading has to put something else in
      // the runtime, or the thread area keeps rendering messages that no longer
      // belong to any thread.
      if (id === activeThreadIdRef.current) {
        const mostRecent = [...remaining].sort((a, b) => b.updatedAt - a.updatedAt)[0]
        const next = mostRecent ?? createEmptyThread(generateId())
        if (!mostRecent) remaining.push(next) // deleted the last one — fall back to a fresh chat
        activeThreadIdRef.current = next.id
        setActiveThreadId(next.id)
        runtime.thread.reset(next.messages)
      }

      setThreads(remaining)

      removeThread(id).catch(() => {
        // The row is already gone locally and there is no undo to offer, so a
        // failed delete reappears on the next load rather than as a banner.
      })
    },
    [threads, runtime],
  )

  const switchToThread = useCallback(
    (id: string) => {
      setMenuThreadId(null)
      setRenamingId(null)
      if (id === activeThreadIdRef.current) {
        if (!isWide) setSidebarOpen(false)
        return
      }
      const target = threads.find((t) => t.id === id)
      activeThreadIdRef.current = id
      setActiveThreadId(id)
      runtime.thread.reset(target?.messages ?? [])
      if (!isWide) setSidebarOpen(false)
    },
    [threads, runtime, isWide],
  )

  const visibleThreads = useMemo(() => {
    const q = searchQuery.trim().toLowerCase()
    return [...threads]
      .sort((a, b) => b.updatedAt - a.updatedAt)
      .filter((t) => !q || threadTitle(t).toLowerCase().includes(q))
  }, [threads, searchQuery])

  const sidebar = (
    <>
      {/* Dismisses the "..." menu on a tap anywhere in the sidebar that isn't
          another control. Rendered first so every sibling paints above it:
          react-native-web gives every View position:relative, so paint order
          follows source order rather than promoting this above the rows. */}
      {menuThreadId ? (
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={() => setMenuThreadId(null)}
          accessibilityLabel="Close menu"
        />
      ) : null}

      <View style={styles.sidebarHeader}>
        <Text style={styles.brandSidebar}>AskScotty</Text>
        {!isWide ? (
          <Pressable onPress={() => setSidebarOpen(false)} accessibilityRole="button" accessibilityLabel="Close sidebar">
            <Text style={styles.closeIcon}>✕</Text>
          </Pressable>
        ) : null}
      </View>

      <HoverPressable
        style={({ pressed, hovered }) => [
          styles.newChatButton,
          (pressed || hovered) && styles.newChatButtonActive,
        ]}
        onPress={startNewChat}
        accessibilityRole="button"
      >
        <Text style={styles.newChatText}>+ New Chat</Text>
      </HoverPressable>

      <TextInput
        style={styles.searchInput}
        value={searchQuery}
        onChangeText={setSearchQuery}
        placeholder="Search chats"
        placeholderTextColor={colors.textFaint}
        accessibilityLabel="Search chats"
      />

      <Text style={styles.recentHeading}>Recents</Text>
      <View style={styles.recents}>
        {visibleThreads.length ? (
          visibleThreads.map((t) => {
            const active = t.id === activeThreadId
            const menuOpen = t.id === menuThreadId

            // The row is the menu's anchor, so it owns the positioning context.
            return (
              <View key={t.id} style={[styles.recentRow, menuOpen && styles.recentRowRaised]}>
                {t.id === renamingId ? (
                  <TextInput
                    style={styles.renameInput}
                    value={renameDraft}
                    onChangeText={setRenameDraft}
                    onSubmitEditing={() => commitRename(t.id)}
                    onBlur={() => commitRename(t.id)}
                    onKeyPress={(e) => {
                      // Escape abandons the edit; blur would otherwise commit it.
                      if (e.nativeEvent.key === 'Escape') setRenamingId(null)
                    }}
                    autoFocus
                    selectTextOnFocus
                    maxLength={TITLE_MAX}
                    accessibilityLabel="Thread name"
                  />
                ) : (
                  <HoverPressable
                    onPress={() => switchToThread(t.id)}
                    style={({ pressed, hovered }) => [
                      styles.recentItem,
                      active && styles.recentItemActive,
                      (pressed || hovered) && !active && styles.recentItemHovered,
                    ]}
                  >
                    {({ hovered }) => (
                      <>
                        <Text
                          style={[styles.recentItemText, active && styles.recentItemTextActive]}
                          numberOfLines={1}
                        >
                          {threadTitle(t)}
                        </Text>

                        {/* Always mounted, and only faded — mounting this on
                            hover instead loses the press, because the pointer
                            landing on it re-renders the row and the button is
                            replaced between mousedown and mouseup. Opacity
                            keeps hit-testing stable; on touch there is no
                            hover to fade in from, so it just stays visible. */}
                        <Pressable
                          onPress={(e) => {
                            // On web the press bubbles to the row behind it,
                            // which would switch threads in the same tap.
                            e.stopPropagation?.()
                            setMenuThreadId(menuOpen ? null : t.id)
                          }}
                          hitSlop={6}
                          accessibilityRole="button"
                          accessibilityLabel={`Options for ${threadTitle(t)}`}
                          style={
                            hovered || active || menuOpen || Platform.OS !== 'web'
                              ? undefined
                              : styles.menuTriggerHidden
                          }
                        >
                          <Text style={styles.menuIcon}>⋯</Text>
                        </Pressable>
                      </>
                    )}
                  </HoverPressable>
                )}

                {menuOpen ? (
                  <View style={styles.menu}>
                    <HoverPressable
                      onPress={() => startRename(t)}
                      style={({ pressed, hovered }) => [
                        styles.menuItem,
                        (pressed || hovered) && styles.menuItemActive,
                      ]}
                      accessibilityRole="button"
                    >
                      <Text style={styles.menuItemText}>Rename</Text>
                    </HoverPressable>
                    <HoverPressable
                      onPress={() => deleteThreadById(t.id)}
                      style={({ pressed, hovered }) => [
                        styles.menuItem,
                        (pressed || hovered) && styles.menuItemActive,
                      ]}
                      accessibilityRole="button"
                    >
                      <Text style={[styles.menuItemText, styles.menuItemDestructive]}>Delete</Text>
                    </HoverPressable>
                  </View>
                ) : null}
              </View>
            )
          })
        ) : (
          <Text style={styles.recentEmpty}>
            {searchQuery ? 'No matching chats' : 'No recent searches'}
          </Text>
        )}
      </View>
    </>
  )

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <View style={[styles.screen, { paddingTop: insets.top }]}>
        <View style={styles.row}>
          {isWide ? (
            <Animated.View
              style={[styles.sidebarTrack, sidebarTrackStyle]}
              {...hiddenWhenClosed(sidebarEffectiveOpen)}
            >
              <Animated.View style={[styles.sidebar, sidebarPanelStyle]}>{sidebar}</Animated.View>
            </Animated.View>
          ) : null}

          <View style={styles.mainColumn}>
            <View style={styles.topBar}>
              <Pressable
                onPress={() => setSidebarOpen(!sidebarEffectiveOpen)}
                accessibilityRole="button"
                accessibilityLabel={sidebarEffectiveOpen ? 'Hide sidebar' : 'Show sidebar'}
                style={styles.sidebarToggle}
              >
                <Text style={styles.sidebarToggleIcon}>☰</Text>
              </Pressable>
              {!sidebarEffectiveOpen ? <Text style={styles.topBarBrand}>AskScotty</Text> : null}
            </View>

            <KeyboardAvoidingView
              style={styles.threadArea}
              behavior={Platform.OS === 'ios' ? 'padding' : undefined}
              keyboardVerticalOffset={insets.top}
            >
              {/* Only one of these is ever mounted: hero + composer centered
                  together, or the thread with the composer pinned below it. */}
              {isEmpty ? (
                <View style={styles.emptyState}>
                  <Text style={styles.hero}>Ask Scotty, {user.displayName}!</Text>
                  <AskComposer disabledModes={disabledModes} onDisabledModesChange={setDisabledModes} />
                </View>
              ) : (
                <Animated.View style={[styles.activeThread, threadEnterStyle]}>
                  <Thread.MessagesFlatList
                    // Forces a full remount per thread switch: the previous
                    // thread's messages are a different list, not an edit.
                    key={activeThreadId}
                    style={styles.messageList}
                    contentContainerStyle={styles.messageListContent}
                    keyboardShouldPersistTaps="handled"
                    // The preview is placed against a measurement of where its
                    // chip was, so it has to go the moment that stops being true.
                    onScroll={closeCitation}
                    scrollEventThrottle={16}
                    ListFooterComponent={RunningIndicator}
                    children={() => <ChatMessage />}
                  />
                  <View style={[styles.pinnedComposer, { paddingBottom: insets.bottom + spacing.sm }]}>
                    <AskComposer disabledModes={disabledModes} onDisabledModesChange={setDisabledModes} />
                  </View>
                </Animated.View>
              )}
            </KeyboardAvoidingView>
          </View>
        </View>

        {!isWide ? (
          <>
            <Animated.View
              style={[styles.drawerBackdrop, drawerBackdropStyle]}
              {...hiddenWhenClosed(sidebarEffectiveOpen)}
            >
              <Pressable
                style={StyleSheet.absoluteFill}
                onPress={() => setSidebarOpen(false)}
                accessibilityLabel="Close sidebar"
              />
            </Animated.View>
            <Animated.View
              style={[
                styles.sidebar,
                styles.sidebarDrawer,
                { paddingTop: insets.top + spacing.md },
                sidebarPanelStyle,
              ]}
              {...hiddenWhenClosed(sidebarEffectiveOpen)}
            >
              {sidebar}
            </Animated.View>
          </>
        ) : null}
      </View>
    </AssistantRuntimeProvider>
  )
}

/**
 * Dots until the answer starts arriving, then nothing.
 *
 * Not `Thread.If running`, which is what this used to be: `isRunning` stays true
 * for the whole turn, so once the answer streams you get dots *underneath* text
 * that is already being written. The handoff is the first chunk, not the end of
 * the run.
 */
function RunningIndicator() {
  const waiting = useAuiState((state) => {
    if (!state.thread.isRunning) return false

    // The runtime creates the assistant message the moment the run starts, so
    // its existence says nothing about whether there is anything to read yet.
    const last = state.thread.messages[state.thread.messages.length - 1]
    if (!last || last.role !== 'assistant') return true
    return !last.content.some((part) => part.type !== 'text' || part.text.length > 0)
  })

  const reduceMotion = useReducedMotion()

  // Outlives `waiting` by the length of the fade, so the dots hand over to the
  // answer rather than blinking out the frame it arrives. ChatMessage fades the
  // card in on the same signal, which is what makes the two overlap.
  const [mounted, setMounted] = useState(waiting)
  const opacity = useSharedValue(waiting ? 1 : 0)

  useEffect(() => {
    if (waiting) {
      setMounted(true)
      opacity.value = reduceMotion ? 1 : withTiming(1, { duration: durations.fast, easing })
      return
    }
    if (reduceMotion) {
      opacity.value = 0
      setMounted(false)
      return
    }
    opacity.value = withTiming(0, { duration: durations.base, easing })
    // A timer, not withTiming's completion callback. That callback still fires
    // after a new wait has begun — superseding an animation does not reliably
    // report `finished: false` — and unmounted the indicator that had just come
    // back, leaving the dots gone for the whole run. Effect cleanup cancels this
    // the instant `waiting` flips back.
    const timer = setTimeout(() => setMounted(false), durations.base)
    return () => clearTimeout(timer)
  }, [waiting, reduceMotion, opacity])

  const style = useAnimatedStyle(() => ({ opacity: opacity.value }))

  if (!mounted) return null

  return (
    <Animated.View style={style}>
      <TypingIndicator />
    </Animated.View>
  )
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.background,
    position: 'relative',
  },
  row: {
    flex: 1,
    flexDirection: 'row',
    width: '100%',
  },
  sidebar: {
    width: SIDEBAR_WIDTH,
    padding: spacing.lg,
    backgroundColor: colors.sidebar,
    // Fills the track, which is the flex child that stretches to the row. The
    // drawer ignores this — absolute children are not flex items — and gets its
    // height from top/bottom instead.
    flex: 1,
  },
  // The shadow lives on whichever element bounds the visible sidebar. Inline
  // that is the track, whose width is the animated one; on the panel it would
  // travel off-screen with the slide.
  sidebarTrack: {
    ...shadows.sidebar,
  },
  sidebarDrawer: {
    position: 'absolute',
    top: 0,
    left: 0,
    bottom: 0,
    zIndex: 60,
    ...shadows.sidebar,
  },
  drawerBackdrop: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: colors.overlay,
    zIndex: 55,
  },
  sidebarHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: spacing.lg,
  },
  brandSidebar: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
  },
  closeIcon: {
    fontSize: 16,
    color: colors.textMuted,
    padding: spacing.xs,
  },
  newChatButton: {
    backgroundColor: colors.sidebarHover,
    borderRadius: radius.lg,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  newChatButtonActive: {
    backgroundColor: colors.border,
  },
  newChatText: {
    color: colors.text,
    fontSize: 14,
    fontWeight: '600',
  },
  searchInput: {
    backgroundColor: colors.background,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    fontSize: 14,
    color: colors.text,
    marginBottom: spacing.lg,
  },
  recentHeading: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: spacing.sm,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  recents: {
    gap: 2,
  },
  recentEmpty: {
    fontSize: 13,
    color: colors.textFaint,
    fontStyle: 'italic',
  },
  recentItem: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    // Reserve the row height the ✕ needs, so rows don't jump as it appears
    // and disappears on hover.
    minHeight: 32,
  },
  recentItemHovered: {
    backgroundColor: colors.sidebarHover,
  },
  recentItemActive: {
    backgroundColor: colors.sidebarHover,
  },
  recentItemText: {
    // Shrinks so a long title truncates rather than pushing the delete
    // control past the edge of the sidebar.
    flexShrink: 1,
    fontSize: 13,
    color: colors.textMuted,
  },
  recentRow: {
    // The positioning context the "..." menu anchors to.
    position: 'relative',
  },
  recentRowRaised: {
    // Later rows paint over earlier ones, so the row holding an open menu has
    // to be lifted or the menu renders behind the next thread down.
    zIndex: 10,
  },
  menuTriggerHidden: {
    opacity: 0,
  },
  menuIcon: {
    fontSize: 16,
    lineHeight: 16,
    color: colors.textFaint,
    paddingHorizontal: spacing.xs,
  },
  menu: {
    position: 'absolute',
    top: '100%',
    right: 0,
    marginTop: 2,
    minWidth: 132,
    paddingVertical: spacing.xs,
    borderRadius: radius.md,
    // Against the near-white sidebar a plain fill would not read as a separate
    // surface, so this leans on the border as much as the shadow.
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.borderSoft,
    ...shadows.soft,
  },
  menuItem: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
  },
  menuItemActive: {
    backgroundColor: colors.sidebarHover,
  },
  menuItemText: {
    fontSize: 13,
    color: colors.text,
  },
  menuItemDestructive: {
    color: colors.error,
  },
  renameInput: {
    minHeight: 32,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
    backgroundColor: colors.background,
    borderWidth: 1,
    borderColor: colors.border,
    fontSize: 13,
    color: colors.text,
  },
  recentItemTextActive: {
    color: colors.text,
    fontWeight: '600',
  },
  mainColumn: {
    flex: 1,
  },
  topBar: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingHorizontal: spacing.lg,
    paddingTop: spacing.md,
  },
  sidebarToggle: {
    padding: spacing.xs,
  },
  sidebarToggleIcon: {
    fontSize: 18,
    color: colors.textMuted,
  },
  topBarBrand: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.text,
  },
  threadArea: {
    flex: 1,
  },
  emptyState: {
    flex: 1,
    justifyContent: 'center',
    paddingHorizontal: spacing.xl,
    gap: spacing.lg,
  },
  hero: {
    fontSize: 36,
    fontWeight: '700',
    color: colors.text,
    textAlign: 'center',
  },
  activeThread: {
    flex: 1,
  },
  messageList: {
    flex: 1,
  },
  messageListContent: {
    padding: spacing.lg,
  },
  pinnedComposer: {
    paddingHorizontal: spacing.xl,
    paddingTop: spacing.sm,
    backgroundColor: colors.background,
  },
})
