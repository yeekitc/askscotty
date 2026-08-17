/**
 * Root layout — wraps every screen. Expo Router turns each file in this folder
 * into a route: `index.tsx` is "/", `settings.tsx` would be "/settings".
 */

import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'

import { CitationProvider } from '../components/CitationOverlay'

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      {/* Above the router, not inside a screen: a citation preview is anchored
          to the window, and one rendered within the message list would be
          clipped by its row and scroll away with it. */}
      <CitationProvider>
        <Stack screenOptions={{ headerShown: false }} />
      </CitationProvider>
    </SafeAreaProvider>
  )
}
