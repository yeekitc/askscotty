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
  ActivityIndicator,
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
import { createHttpAdapter } from '../lib/assistantAdapter'
import { type ChatThread, createEmptyThread, threadTitle } from '../lib/chatThreads'
import { colors, radius, shadows, spacing } from '../lib/theme'
import { useCurrentUser } from '../lib/user'

/** The PRD's signature multi-hop demo query, pre-filled so demos are one tap. */
const DEMO_QUERY =
  'I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then ' +
  'an interesting startup or AI event before 8.'

const THREADS_KEY = 'askscotty.threads'
const SOURCES_KEY = 'askscotty.sources'
const DEFAULT_SOURCES = ['Course Catalog', 'Directory', 'Piazza', 'Canvas']
const SIDEBAR_WIDTH = 280
const WIDE_BREAKPOINT = 900

// Thread history and the source filter are per-device UI state, not app
// data, so plain localStorage is fine — but it only exists on web, hence
// the Platform guard (see CLAUDE.md: never touch browser-only APIs on native).
const canPersist = Platform.OS === 'web' && typeof window !== 'undefined' && !!window.localStorage

function loadPersisted<T>(key: string, fallback: T): T {
  if (!canPersist) return fallback
  try {
    const raw = window.localStorage.getItem(key)
    return raw ? JSON.parse(raw) : fallback
  } catch (e) {
    return fallback
  }
}

function savePersisted(key: string, value: unknown) {
  if (!canPersist) return
  try {
    window.localStorage.setItem(key, JSON.stringify(value))
  } catch (e) {
    // ignore storage errors (private browsing, quota, etc.)
  }
}

function loadInitialThreads(): { threads: ChatThread[]; activeThreadId: string } {
  const stored = loadPersisted<{ threads: ChatThread[]; activeThreadId: string } | null>(
    THREADS_KEY,
    null,
  )
  if (stored && stored.threads.length) return stored
  const first = createEmptyThread(generateId())
  return { threads: [first], activeThreadId: first.id }
}

export default function AskScreen() {
  const insets = useSafeAreaInsets()
  const { width } = useWindowDimensions()
  const isWide = width >= WIDE_BREAKPOINT
  const user = useCurrentUser()

  const [sources, setSources] = useState<string[]>(() => loadPersisted(SOURCES_KEY, DEFAULT_SOURCES))
  useEffect(() => savePersisted(SOURCES_KEY, sources), [sources])
  const sourcesRef = useRef(sources)
  useEffect(() => {
    sourcesRef.current = sources
  }, [sources])

  // `null` means "no explicit choice yet" — follow the width-based default
  // until the user actually taps the toggle, so resizing the window doesn't
  // fight a stale manual override.
  const [sidebarOpen, setSidebarOpen] = useState<boolean | null>(null)
  const sidebarEffectiveOpen = sidebarOpen ?? isWide
  const [searchQuery, setSearchQuery] = useState('')

  const initial = useMemo(loadInitialThreads, [])
  const [threads, setThreads] = useState<ChatThread[]>(initial.threads)
  const [activeThreadId, setActiveThreadId] = useState(initial.activeThreadId)
  const activeThreadIdRef = useRef(activeThreadId)

  useEffect(() => {
    savePersisted(THREADS_KEY, { threads, activeThreadId })
  }, [threads, activeThreadId])

  const initialActiveThread =
    initial.threads.find((t) => t.id === initial.activeThreadId) ?? initial.threads[0]

  const adapter = useMemo(() => createHttpAdapter(() => sourcesRef.current), [])
  const runtime = useLocalRuntime(adapter, { initialMessages: initialActiveThread.messages })

  // Whether to show the empty-state hero or the thread. Driven by our own
  // state (set from the same subscription that mirrors messages below)
  // rather than two separate <Thread.If> instances — those each subscribe
  // to the runtime independently, and letting Thread.MessagesFlatList's own
  // internal item list shrink to zero out from under it via thread.reset()
  // raced its FlatList's index bookkeeping and crashed. One state value
  // driving one conditional makes the empty/active swap atomic.
  const [isEmpty, setIsEmpty] = useState(initialActiveThread.messages.length === 0)

  // Mirrors the live thread's messages back into whichever thread is
  // currently active, so switching away and back doesn't lose anything.
  // Reads activeThreadIdRef (not the `activeThreadId` state) because this
  // subscription is set up once — a ref is what stays current.
  useEffect(() => {
    return runtime.thread.subscribe(() => {
      const messages = runtime.thread.getState().messages
      setIsEmpty(messages.length === 0)
      const snapshot: ThreadMessageLike[] = messages.map((m) => ({ role: m.role, content: m.content }))
      setThreads((prev) =>
        prev.map((t) =>
          t.id === activeThreadIdRef.current ? { ...t, messages: snapshot, updatedAt: Date.now() } : t,
        ),
      )
    })
  }, [runtime])

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

/** "Scotty is thinking…" — shown while a request is in flight. */
function RunningIndicator() {
  return (
    <Thread.If running>
      <View style={styles.thinkingRow}>
        <ActivityIndicator color={colors.textMuted} />
        <Text style={styles.thinkingText}>Scotty is thinking…</Text>
      </View>
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
  thinkingRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: spacing.sm,
    paddingVertical: spacing.sm,
  },
  thinkingText: {
    color: colors.textMuted,
    fontSize: 14,
  },
})
