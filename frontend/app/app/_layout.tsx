/**
 * Root layout — wraps every screen. Expo Router turns each file in this folder
 * into a route: `index.tsx` is "/", `settings.tsx` would be "/settings".
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
