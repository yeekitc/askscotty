import { FormEvent, useState } from 'react'
import './App.css'

type Citation = {
  title: string
  url?: string
  source: string
  indexed_at?: string
  verified_at?: string
}

type AskResponse = {
  answer: string
  citations: Citation[]
  modes_used: string[]
  note: string
}

const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000'

export default function App() {
  const [query, setQuery] = useState(
    'I get out of 15-213 at 4:20 tomorrow. Find somewhere nearby to eat and then an interesting startup or AI event before 8.',
  )
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<AskResponse | null>(null)

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
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

      const data = (await response.json()) as AskResponse
      setResult(data)
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="page">
      <header className="header">
        <p className="brand">AskScotty</p>
        <p className="tagline">Ask Scotty anything about CMU — get a cited, multi-hop answer.</p>
      </header>

      <main className="main">
        <form className="ask-form" onSubmit={onSubmit}>
          <label htmlFor="query">Your question</label>
          <textarea
            id="query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            rows={4}
            required
          />
          <button type="submit" disabled={loading || !query.trim()}>
            {loading ? 'Asking…' : 'Ask'}
          </button>
        </form>

        {error ? <p className="error">{error}</p> : null}

        {result ? (
          <section className="result" aria-live="polite">
            <h2>Answer</h2>
            <p>{result.answer}</p>
            <p className="meta">Modes: {result.modes_used.join(', ')} · {result.note}</p>
            <h3>Citations</h3>
            <ul>
              {result.citations.map((citation) => (
                <li key={`${citation.source}-${citation.title}`}>
                  <strong>{citation.title}</strong> ({citation.source})
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </main>

      <footer className="footer">
        Uses publicly available CMU web pages and public campus APIs. Not affiliated with ScottyLabs.
      </footer>
    </div>
  )
}
