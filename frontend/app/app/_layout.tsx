/**
 * Root layout — wraps every screen.
 *
 * Expo Router turns the files in this `app/` folder into screens automatically:
 * `app/index.tsx` is "/", `app/settings.tsx` would be "/settings", and so on.
 * Add a new file here and it becomes a new screen on phone and web at once.
 */

import { Stack } from 'expo-router'
import { StatusBar } from 'expo-status-bar'
import { SafeAreaProvider } from 'react-native-safe-area-context'

export default function RootLayout() {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Stack screenOptions={{ headerShown: false }} />
    </SafeAreaProvider>
  )
}
