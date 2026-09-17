/**
 * Manual test page for `POST /v1/lido/generate` — the Lido-corpus pipeline
 * (retrieve -> compose copy -> generate assets -> fill), kept separate from the
 * DesignDoc engine's Home/Editor pages. Renders the result with the same throwaway
 * SVG approximation as `app/lido_corpus/preview.py` (see `lidoRender.tsx`) since there
 * is no real Lido.js editor wired in yet.
 */

import { useState } from 'react'

import { api, ApiError } from '../lib/api'
import { LidoPreview } from '../lib/lidoRender'
import type { LidoGenerateResponse } from '../lib/lidoTypes'

const KINDS = ['', 'post', 'story', 'poster', 'banner', 'thumbnail', 'ad', 'flyer']

const EXAMPLES = [
  'A cozy coffee shop poster, warm tones, headline "Morning Magic", phone +1 555-0123',
  'Gym promo post, bold and high-contrast, "GET STRONG", call 98765 43210',
  'Restaurant grand opening flyer, elegant, address 42 Main St, website example.com',
]

/** Just the content — no outer `.app`/topbar, so a parent page (e.g. Home) can host it
 * alongside a flow toggle without a duplicate header. */
export function LidoFlow() {
  const [prompt, setPrompt] = useState('')
  const [kind, setKind] = useState('')
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LidoGenerateResponse | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)

  const generate = async () => {
    if (!prompt.trim() || running) return
    setRunning(true)
    setError(null)
    setResult(null)
    const started = performance.now()
    try {
      const response = await api.lidoGenerate(prompt.trim(), kind || undefined)
      setResult(response)
      setElapsedMs(performance.now() - started)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    } finally {
      setRunning(false)
    }
  }

  const layers = result?.document?.[0]?.layers ?? null

  return (
    <div className="home">
      <div className="hero">
        <h1>Lido template generator</h1>
        <p>
          Describe a design. This hits <code>/v1/lido/generate</code>: retrieves the best-matching
          template out of your <code>lidojs_templates/</code> corpus, rewrites its copy, generates
          new background/photo assets, and returns the filled document.{' '}
          <span style={{ color: 'var(--accent-2)' }}>Throwaway SVG preview — not the real Lido.js editor.</span>
        </p>
      </div>

        <div className="prompt-box">
          <textarea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="e.g. A cozy coffee shop poster, warm tones, headline &quot;Morning Magic&quot;..."
            disabled={running}
          />
          <div className="prompt-row">
            <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={running} style={{ maxWidth: 160 }}>
              {KINDS.map((k) => (
                <option key={k} value={k}>{k || 'auto-detect kind'}</option>
              ))}
            </select>
            <button className="primary" onClick={generate} disabled={running || !prompt.trim()}>
              {running ? <span className="spinner" /> : 'Generate'}
            </button>
            {elapsedMs != null && !running && (
              <span className="badge">{(elapsedMs / 1000).toFixed(1)}s</span>
            )}
          </div>
          <div className="examples">
            {EXAMPLES.map((example) => (
              <button key={example} onClick={() => setPrompt(example)} disabled={running}>
                {example.length > 50 ? example.slice(0, 50) + '…' : example}
              </button>
            ))}
          </div>
        </div>

        {error && <div className="toast error" style={{ position: 'static', margin: '16px 0' }}>{error}</div>}

        {result && layers && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, marginTop: 20 }}>
            <div className="canvas-wrap" style={{ borderRadius: 10 }}>
              <div className="canvas-frame">
                <LidoPreview layers={layers} />
              </div>
            </div>

            <div>
              <div className="progress">
                <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Template chosen</div>
                <div style={{ fontWeight: 600 }}>{result.templateId}</div>
                <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                  score {result.templateScore.toFixed(3)}
                </div>
              </div>

              <div className="progress">
                <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                  Text fills ({result.textFills.length})
                </div>
                <div className="log">
                  {result.textFills.map((fill) => (
                    <div key={fill.layerId}>
                      <strong>{fill.role}</strong>: {fill.text}
                    </div>
                  ))}
                </div>
              </div>

              <div className="progress">
                <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
                  Generated assets ({result.imageFills.length})
                </div>
                <div className="log">
                  {result.imageFills.map((fill) => (
                    <div key={fill.layerId} style={{ wordBreak: 'break-all' }}>
                      {fill.layerId.slice(0, 8)}… → {fill.url.slice(0, 40)}…
                    </div>
                  ))}
                  {result.imageFills.length === 0 && <div>none generated</div>}
                </div>
              </div>
            </div>
          </div>
        )}
    </div>
  )
}
