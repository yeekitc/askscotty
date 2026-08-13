import { StatusBar } from 'expo-status-bar'
import { useState } from 'react'
import {
  ActivityIndicator,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native'

type AskResponse = {
  answer: string
  citations: { title: string; source: string }[]
  modes_used: string[]
  note: string
}

const API_URL = process.env.EXPO_PUBLIC_API_URL ?? 'http://localhost:8000'

export default function App() {
  const [query, setQuery] = useState(
    'Open after 8:20 near Wean',
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AskResponse | null>(null)

  async function ask() {
    setLoading(true)
    setError(null)
    try {
      const response = await fetch(`${API_URL}/api/ask/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }),
      })
      if (!response.ok) {
        throw new Error(`API error ${response.status}`)
      }
      setResult((await response.json()) as AskResponse)
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.brand}>AskScotty</Text>
        <Text style={styles.tagline}>Ask Scotty anything about CMU — cited answers.</Text>

        <Text style={styles.label}>Your question</Text>
        <TextInput
          style={styles.input}
          multiline
          value={query}
          onChangeText={setQuery}
          placeholder="Ask a campus question"
        />

        <Pressable style={styles.button} onPress={ask} disabled={loading || !query.trim()}>
          {loading ? <ActivityIndicator color="#f7fafc" /> : <Text style={styles.buttonText}>Ask</Text>}
        </Pressable>

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {result ? (
          <View style={styles.result}>
            <Text style={styles.heading}>Answer</Text>
            <Text style={styles.body}>{result.answer}</Text>
            <Text style={styles.meta}>
              Modes: {result.modes_used.join(', ')} · {result.note}
            </Text>
          </View>
        ) : null}
      </ScrollView>
    </SafeAreaView>
  )
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#eef3f7',
  },
  container: {
    padding: 24,
    gap: 12,
  },
  brand: {
    fontSize: 34,
    fontWeight: '700',
    color: '#12202b',
  },
  tagline: {
    fontSize: 16,
    color: '#3d5363',
    marginBottom: 8,
  },
  label: {
    fontSize: 12,
    letterSpacing: 1,
    textTransform: 'uppercase',
    color: '#4a6273',
  },
  input: {
    minHeight: 110,
    borderWidth: 1,
    borderColor: '#9bb0bf',
    backgroundColor: 'rgba(255,255,255,0.8)',
    padding: 12,
    textAlignVertical: 'top',
    fontSize: 16,
  },
  button: {
    alignSelf: 'flex-start',
    backgroundColor: '#12202b',
    paddingHorizontal: 18,
    paddingVertical: 12,
  },
  buttonText: {
    color: '#f7fafc',
    fontSize: 16,
    fontWeight: '600',
  },
  error: {
    color: '#8a1f1f',
  },
  result: {
    marginTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#9bb0bf',
    paddingTop: 12,
    gap: 8,
  },
  heading: {
    fontSize: 18,
    fontWeight: '700',
    color: '#12202b',
  },
  body: {
    fontSize: 16,
    color: '#12202b',
    lineHeight: 24,
  },
  meta: {
    fontSize: 13,
    color: '#4a6273',
  },
})
