/**
 * The ask screen — this is the whole app right now.
 *
 * THIS ONE FILE RENDERS ON iOS, ANDROID, AND THE BROWSER.
 * Edit it and all three change. There is no separate web version.
 *
 * Chat state (messages, composer text, send/streaming) is owned by
 * assistant-ui's runtime (see AssistantRuntimeProvider below). We layer our
 * own local multi-thread history on top of it — see lib/chatThreads.ts for
 * why (assistant-ui's own thread list needs a backend we don't have yet).
 *
 * Note the components come from 'react-native', not HTML:
 *   <View>  instead of <div>
 *   <Text>  instead of <p> / <span>   (all text MUST be inside a <Text>)
 *   <Pressable> instead of <button>
 * Styles are objects in StyleSheet.create at the bottom, not CSS files.
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
import AsyncStorage from '@react-native-async-storage/async-storage'
import {
  AssistantRuntimeProvider,
  ThreadPrimitive as Thread,
  generateId,
  useLocalRuntime,
  type ThreadMessageLike,
} from '@assistant-ui/react-native'

import { AskComposer } from '../components/AskComposer'
import { ChatMessage } from '../components/ChatMessage'
import { HoverPressable } from '../components/HoverPressable'
import { TypingIndicator } from '../components/TypingIndicator'
import { createHttpAdapter } from '../lib/assistantAdapter'
import {
  type ChatThread,
  createEmptyThread,
  loadThreads,
  persistThread,
  threadTitle,
} from '../lib/chatThreads'
import { colors, radius, shadows, spacing } from '../lib/theme'
import { useCurrentUser } from '../lib/user'

/** The PRD's signature multi-hop demo query, pre-filled so demos are one tap. */
const DEMO_QUERY =
  'I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then ' +
  'an interesting startup or AI event before 8.'

const SOURCES_KEY = 'askscotty.sources'
const DEFAULT_SOURCES = ['Course Catalog', 'Directory', 'Piazza', 'Canvas']
const SIDEBAR_WIDTH = 280
const WIDE_BREAKPOINT = 900

/** How long to wait after the last change before saving a thread. */
const SAVE_DEBOUNCE_MS = 600

// The source filter is per-device UI state, so it stays on the device — but in
// AsyncStorage, not localStorage, because `window` does not exist on a phone
// (CLAUDE.md). Conversations themselves are *not* stored here: they live in the
// backend now, scoped to this session (see lib/chatThreads.ts).
async function loadSources(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(SOURCES_KEY)
    return raw ? (JSON.parse(raw) as string[]) : DEFAULT_SOURCES
  } catch (e) {
    return DEFAULT_SOURCES
  }
}

async function saveSources(sources: string[]): Promise<void> {
  try {
    await AsyncStorage.setItem(SOURCES_KEY, JSON.stringify(sources))
  } catch (e) {
    // Storage full or unavailable — a forgotten filter is not worth an error.
  }
}

export default function AskScreen() {
  const insets = useSafeAreaInsets()
  const { width } = useWindowDimensions()
  const isWide = width >= WIDE_BREAKPOINT
  const user = useCurrentUser()

  const [sources, setSources] = useState<string[]>(DEFAULT_SOURCES)
  const sourcesRef = useRef(sources)
  useEffect(() => {
    sourcesRef.current = sources
  }, [sources])

  // Read the saved filter once, then write on every later change. Without the
  // flag, the write effect would immediately save back whatever the read just
  // returned — harmless, but it makes the storage log confusing to follow.
  const sourcesLoaded = useRef(false)
  useEffect(() => {
    loadSources().then((stored) => {
      sourcesLoaded.current = true
      setSources(stored)
    })
  }, [])
  useEffect(() => {
    if (sourcesLoaded.current) void saveSources(sources)
  }, [sources])

  // `null` means "no explicit choice yet" — follow the width-based default
  // until the user actually taps the toggle, so resizing the window doesn't
  // fight a stale manual override.
  const [sidebarOpen, setSidebarOpen] = useState<boolean | null>(null)
  const sidebarEffectiveOpen = sidebarOpen ?? isWide
  const [searchQuery, setSearchQuery] = useState('')

  // The app opens on a fresh chat, every time. Saved conversations arrive from
  // the backend a moment later and fill the sidebar — they do not yank the
  // runtime out from under someone who has already started typing.
  const firstThread = useMemo(() => createEmptyThread(generateId()), [])
  const [threads, setThreads] = useState<ChatThread[]>([firstThread])
  const [activeThreadId, setActiveThreadId] = useState(firstThread.id)
  const activeThreadIdRef = useRef(activeThreadId)

  const adapter = useMemo(() => createHttpAdapter(() => sourcesRef.current), [])
  const runtime = useLocalRuntime(adapter, { initialMessages: [] })

  // Saving is debounced because the runtime fires its subscription on every
  // status change, not just on a finished turn — an unthrottled save would PUT
  // the whole thread several times per answer.
  //
  // Pending threads are held in a map rather than a single slot so switching
  // conversations mid-debounce cannot drop the one being left behind.
  const pendingSaves = useRef(new Map<string, ChatThread>())
  const lastSaved = useRef(new Map<string, string>())
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const flushSaves = useCallback(() => {
    const batch = [...pendingSaves.current.values()]
    pendingSaves.current.clear()

    for (const thread of batch) {
      const fingerprint = JSON.stringify(thread.messages)
      lastSaved.current.set(thread.id, fingerprint)
      persistThread(thread).catch(() => {
        // Drop the fingerprint so the next change retries this thread. A failed
        // save should not cost the user their conversation, and a red banner
        // mid-demo over a transient network blip is worse than a silent retry.
        lastSaved.current.delete(thread.id)
      })
    }
  }, [])

  const schedulePersist = useCallback(
    (thread: ChatThread) => {
      // Never persist an empty thread: tapping "New Chat" would otherwise
      // create a server row for a conversation that never happened.
      if (thread.messages.length === 0) return
      if (lastSaved.current.get(thread.id) === JSON.stringify(thread.messages)) return

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

  // Pull this session's saved conversations into the sidebar.
  useEffect(() => {
    let cancelled = false

    loadThreads()
      .then((saved) => {
        if (cancelled || saved.length === 0) return
        setThreads((prev) => {
          // Keep the chat we opened with only while it is still untouched;
          // otherwise the user would lose whatever they typed during the load.
          const current = prev.find((t) => t.id === activeThreadIdRef.current)
          const keepCurrent = current && current.messages.length === 0 ? [current] : []
          return [...keepCurrent, ...saved]
        })
      })
      .catch(() => {
        // No history is a usable app; a blocked one is not. The fresh chat the
        // screen already mounted with stays, and the next save will retry.
      })

    return () => {
      cancelled = true
    }
  }, [])

  // Whether to show the empty-state hero or the thread. Driven by our own
  // state (set from the same subscription that mirrors messages below)
  // rather than two separate <Thread.If> instances — those each subscribe
  // to the runtime independently, and letting Thread.MessagesFlatList's own
  // internal item list shrink to zero out from under it via thread.reset()
  // raced its FlatList's index bookkeeping and crashed. One state value
  // driving one conditional makes the empty/active swap atomic.
  const [isEmpty, setIsEmpty] = useState(true)

  // Mirrors the live thread's messages back into whichever thread is
  // currently active, so switching away and back doesn't lose anything.
  // Reads activeThreadIdRef (not the `activeThreadId` state) because this
  // subscription is set up once — a ref is what stays current.
  useEffect(() => {
    return runtime.thread.subscribe(() => {
      const messages = runtime.thread.getState().messages
      setIsEmpty(messages.length === 0)
      const snapshot: ThreadMessageLike[] = messages.map((m) => ({ role: m.role, content: m.content }))
      const id = activeThreadIdRef.current
      const updatedAt = Date.now()

      setThreads((prev) =>
        prev.map((t) => (t.id === id ? { ...t, messages: snapshot, updatedAt } : t)),
      )
      // Queued outside the state updater on purpose: React may run an updater
      // more than once, and a save is a side effect that should happen once.
      schedulePersist({ id, messages: snapshot, updatedAt })
    })
  }, [runtime, schedulePersist])

  useEffect(() => {
    runtime.thread.composer.setText(DEMO_QUERY)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const startNewChat = useCallback(() => {
    const current = threads.find((t) => t.id === activeThreadIdRef.current)
    if (current && current.messages.length === 0) return // already on a fresh chat
    const next = createEmptyThread(generateId())
    setThreads((prev) => [next, ...prev])
    activeThreadIdRef.current = next.id
    setActiveThreadId(next.id)
    runtime.thread.reset([])
    if (!isWide) setSidebarOpen(false)
  }, [threads, runtime, isWide])

  const switchToThread = useCallback(
    (id: string) => {
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
            return (
              <HoverPressable
                key={t.id}
                onPress={() => switchToThread(t.id)}
                style={({ pressed, hovered }) => [
                  styles.recentItem,
                  active && styles.recentItemActive,
                  (pressed || hovered) && !active && styles.recentItemHovered,
                ]}
              >
                <Text
                  style={[styles.recentItemText, active && styles.recentItemTextActive]}
                  numberOfLines={1}
                >
                  {threadTitle(t)}
                </Text>
              </HoverPressable>
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
          {isWide && sidebarEffectiveOpen ? <View style={styles.sidebar}>{sidebar}</View> : null}

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
              {/* Empty state: hero + composer centered together. Active state:
                  thread fills the height and the composer pins to the bottom.
                  Only one of these two is ever mounted at a time. */}
              {isEmpty ? (
                <View style={styles.emptyState}>
                  <Text style={styles.hero}>Ask Scotty, {user.displayName}!</Text>
                  <AskComposer sources={sources} onSourcesChange={setSources} />
                </View>
              ) : (
                <View style={styles.activeThread}>
                  <Thread.MessagesFlatList
                    // Forces a full remount on every thread switch instead of
                    // reconciling in place — the previous thread's messages
                    // are a different list, not an edit of this one.
                    key={activeThreadId}
                    style={styles.messageList}
                    contentContainerStyle={styles.messageListContent}
                    keyboardShouldPersistTaps="handled"
                    ListFooterComponent={RunningIndicator}
                    children={() => <ChatMessage />}
                  />
                  <View style={[styles.pinnedComposer, { paddingBottom: insets.bottom + spacing.sm }]}>
                    <AskComposer sources={sources} onSourcesChange={setSources} />
                  </View>
                </View>
              )}
            </KeyboardAvoidingView>
          </View>
        </View>

        {!isWide && sidebarEffectiveOpen ? (
          <>
            <Pressable
              style={styles.drawerBackdrop}
              onPress={() => setSidebarOpen(false)}
              accessibilityLabel="Close sidebar"
            />
            <View style={[styles.sidebar, styles.sidebarDrawer, { paddingTop: insets.top + spacing.md }]}>
              {sidebar}
            </View>
          </>
        ) : null}
      </View>
    </AssistantRuntimeProvider>
  )
}

/**
 * Bouncing dots at the foot of the thread while a request is in flight.
 *
 * `Thread.If running` is assistant-ui's own loading primitive — the runtime
 * sets `isRunning` for as long as the adapter's run() is pending, so we never
 * track "is a request open?" ourselves. /api/ask/ is non-streaming, which
 * means this stays up for the whole round trip.
 */
function RunningIndicator() {
  return (
    <Thread.If running>
      <TypingIndicator />
    </Thread.If>
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
    ...shadows.sidebar,
  },
  sidebarDrawer: {
    position: 'absolute',
    top: 0,
    left: 0,
    bottom: 0,
    zIndex: 60,
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
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.sm,
    borderRadius: radius.sm,
  },
  recentItemHovered: {
    backgroundColor: colors.sidebarHover,
  },
  recentItemActive: {
    backgroundColor: colors.sidebarHover,
  },
  recentItemText: {
    fontSize: 13,
    color: colors.textMuted,
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
