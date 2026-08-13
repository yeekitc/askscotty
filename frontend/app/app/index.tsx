/**
 * The ask screen — this is the whole app right now.
 *
 * THIS ONE FILE RENDERS ON iOS, ANDROID, AND THE BROWSER.
 * Edit it and all three change. There is no separate web version.
 *
 * Chat state (messages, composer text, send/streaming) is owned by
 * assistant-ui's runtime (see AssistantRuntimeProvider below), not by this
 * component. We only own screen-level state: the source filter and the
 * recents list, both of which live outside any one message.
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
  View,
  useWindowDimensions,
} from 'react-native'
import { useSafeAreaInsets } from 'react-native-safe-area-context'
import {
  AssistantRuntimeProvider,
  ThreadPrimitive as Thread,
  useLocalRuntime,
} from '@assistant-ui/react-native'

import { AskComposer } from '../components/AskComposer'
import { ChatMessage } from '../components/ChatMessage'
import { Credits } from '../components/Credits'
import { createHttpAdapter } from '../lib/assistantAdapter'
import { MAX_CONTENT_WIDTH, colors, spacing } from '../lib/theme'
import { useCurrentUser } from '../lib/user'

/** The PRD's signature multi-hop demo query, pre-filled so demos are one tap. */
const DEMO_QUERY =
  'I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then ' +
  'an interesting startup or AI event before 8.'

const RECENTS_KEY = 'askscotty.recents'
const SOURCES_KEY = 'askscotty.sources'
const DEFAULT_SOURCES = ['Course Catalog', 'Directory', 'Piazza', 'Canvas']

// Recents/sources are small UI-preference blobs, not app data, so plain
// localStorage is fine — but it only exists on web, hence the Platform
// guard (see CLAUDE.md: never touch browser-only APIs on native).
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

export default function AskScreen() {
  const insets = useSafeAreaInsets()
  const { width } = useWindowDimensions()
  const isWide = width >= 900
  const user = useCurrentUser()

  const [sources, setSources] = useState<string[]>(() => loadPersisted(SOURCES_KEY, DEFAULT_SOURCES))
  const [recents, setRecents] = useState<string[]>(() => loadPersisted<string[]>(RECENTS_KEY, []))

  useEffect(() => {
    savePersisted(SOURCES_KEY, sources)
  }, [sources])

  const recordQuery = useCallback((query: string) => {
    setRecents((prev) => {
      const next = [query, ...prev.filter((r) => r !== query)].slice(0, 10)
      savePersisted(RECENTS_KEY, next)
      return next
    })
  }, [])

  // Read through a ref rather than depending on `sources` directly, so the
  // adapter (and the runtime built from it) is created exactly once and
  // still always sees the current Sources menu selection.
  const sourcesRef = useRef(sources)
  useEffect(() => {
    sourcesRef.current = sources
  }, [sources])

  const adapter = useMemo(
    () => createHttpAdapter(() => sourcesRef.current, recordQuery),
    [recordQuery],
  )
  const runtime = useLocalRuntime(adapter)

  useEffect(() => {
    runtime.thread.composer.setText(DEMO_QUERY)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <View style={[styles.screen, { paddingTop: insets.top }]}>
        <View style={[styles.row, isWide ? styles.rowWide : undefined]}>
          {isWide ? (
            <View style={styles.sidebar}>
              <Text style={styles.brandSidebar}>AskScotty</Text>
              <Text style={styles.recentHeading}>Recents</Text>
              <View style={styles.recents}>
                {recents.length ? (
                  recents.map((t) => (
                    <Pressable key={t} onPress={() => runtime.thread.composer.setText(t)}>
                      <Text style={styles.recentItem} numberOfLines={1}>
                        {t}
                      </Text>
                    </Pressable>
                  ))
                ) : (
                  <Text style={styles.recentEmpty}>No recent searches</Text>
                )}
              </View>
              <View style={{ flex: 1 }} />
              <Credits />
            </View>
          ) : null}

          <KeyboardAvoidingView
            style={styles.mainColumn}
            behavior={Platform.OS === 'ios' ? 'padding' : undefined}
            keyboardVerticalOffset={insets.top}
          >
            {/* Empty state: hero + composer centered together. Active state:
                thread fills the height and the composer pins to the bottom.
                Only one of these two is ever mounted at a time. */}
            <Thread.If empty>
              <View style={styles.emptyState}>
                <Text style={styles.hero}>Ask Scotty, {user.displayName}!</Text>
                <AskComposer sources={sources} onSourcesChange={setSources} />
              </View>
            </Thread.If>

            <Thread.If empty={false}>
              <View style={styles.activeThread}>
                <Thread.MessagesFlatList
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
            </Thread.If>
          </KeyboardAvoidingView>
        </View>
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
  },
  row: {
    flex: 1,
    width: '100%',
    maxWidth: MAX_CONTENT_WIDTH + 280,
    alignSelf: 'center',
  },
  rowWide: {
    flexDirection: 'row',
  },
  sidebar: {
    width: 280,
    padding: spacing.lg,
    borderRightWidth: 1,
    borderRightColor: colors.border,
  },
  brandSidebar: {
    fontSize: 20,
    fontWeight: '700',
    color: colors.text,
    marginBottom: spacing.md,
  },
  recentHeading: {
    fontSize: 12,
    color: colors.textMuted,
    marginBottom: spacing.sm,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  recents: {
    gap: spacing.sm,
  },
  recentEmpty: {
    fontSize: 14,
    color: colors.textFaint,
    fontStyle: 'italic',
  },
  recentItem: {
    fontSize: 14,
    color: colors.textMuted,
    marginBottom: 6,
  },
  mainColumn: {
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
    borderTopWidth: 1,
    borderTopColor: colors.border,
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
