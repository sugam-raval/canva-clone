/**
 * The app's one page: `POST /v1/lido/generate` — pick the best template (or one by id,
 * or a random one), fill it, and show the result, the match explanation and the saved
 * history. Renders with the SVG approximation in `lidoRender.tsx` (no Lido.js editor
 * is wired in yet).
 */

import { useCallback, useEffect, useState } from 'react'

import { api, ApiError } from '../lib/api'
import { LidoPreview } from '../lib/lidoRender'
import type { LidoGenerateResponse, LidoGenerationSummary, LidoTemplateSummary } from '../lib/lidoTypes'

const KINDS = ['', 'post', 'story', 'poster', 'banner', 'thumbnail', 'ad', 'flyer']

const EXAMPLES = [
  'A cozy coffee shop poster, warm tones, headline "Morning Magic", phone +1 555-0123',
  'Gym promo post, bold and high-contrast, "GET STRONG", call 98765 43210',
  'Restaurant grand opening flyer, elegant, address 42 Main St, website example.com',
]

/** Which template to fill: the automatic match (docs/new_match_plan.md), an exact pick by
 * id, or a uniform pick across the whole catalog. */
type TemplateChoice = { mode: 'auto' } | { mode: 'random' } | { mode: 'id'; id: string }

/** The page content; `main.tsx` supplies the header. */
export function LidoFlow() {
  const [prompt, setPrompt] = useState('')
  const [kind, setKind] = useState('')
  const [templateChoice, setTemplateChoice] = useState<TemplateChoice>({ mode: 'auto' })
  const [templates, setTemplates] = useState<LidoTemplateSummary[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LidoGenerateResponse | null>(null)
  const [layers, setLayers] = useState<Record<string, any> | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  const [saved, setSaved] = useState<LidoGenerationSummary[]>([])

  useEffect(() => {
    api.lidoTemplates().then(setTemplates).catch(() => { /* picker is non-critical */ })
  }, [])

  const refreshSaved = useCallback(async () => {
    try { setSaved(await api.lidoGenerations()) } catch { /* non-critical */ }
  }, [])

  useEffect(() => { refreshSaved() }, [refreshSaved])

  const generate = async () => {
    if (!prompt.trim() || running) return
    setRunning(true)
    setError(null)
    setResult(null)
    setLayers(null)
    const started = performance.now()
    try {
      const response = await api.lidoGenerate(prompt.trim(), kind || undefined, {
        templateId: templateChoice.mode === 'id' ? templateChoice.id : undefined,
        randomTemplate: templateChoice.mode === 'random',
      })
      setResult(response)
      setLayers(response.document?.[0]?.layers ?? null)
      setElapsedMs(performance.now() - started)
      refreshSaved()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    } finally {
      setRunning(false)
    }
  }

  const open = async (designId: string) => {
    setError(null)
    try {
      const response = await api.lidoGeneration(designId)
      setLayers(response.document?.[0]?.layers ?? null)
      setResult(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    }
  }

  return (
    <div className="home">
      <div className="hero">
        <h1>Lido template generator</h1>
        <p>
          Describe a design. This hits <code>/v1/lido/generate</code>: picks a template
          (best-matching by default, or choose one yourself, or random), rewrites its copy,
          generates new background/photo assets, and saves the result to the database.{' '}
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
            <select
              value={templateChoice.mode === 'id' ? templateChoice.id : templateChoice.mode}
              onChange={(e) => {
                const v = e.target.value
                setTemplateChoice(v === 'auto' || v === 'random' ? { mode: v } : { mode: 'id', id: v })
              }}
              disabled={running}
              style={{ maxWidth: 220 }}
              title="Which template to fill"
            >
              <option value="auto">Auto (best match)</option>
              <option value="random">Random</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.id}{t.ready ? '' : ' (unreviewed)'}
                </option>
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

        {layers && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 320px', gap: 20, marginTop: 20 }}>
            <div className="canvas-wrap" style={{ borderRadius: 10 }}>
              <div className="canvas-frame">
                <LidoPreview layers={layers} />
              </div>
            </div>

            {result && (
              <div>
                <div className="progress">
                  <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Template chosen</div>
                  <div style={{ fontWeight: 600 }}>{result.templateId}</div>
                  <div style={{ fontSize: 12, color: 'var(--muted)' }}>
                    score {result.templateScore.toFixed(3)}
                  </div>
                  {result.match && (
                    <div style={{ fontSize: 12, marginTop: 8 }}>
                      <div style={{ color: 'var(--muted)' }}>
                        {result.match.path === 'holds_all'
                          ? 'Picked from templates that hold every detail you gave'
                          : 'No template holds every detail — best overall match'}
                      </div>
                      <div style={{ marginTop: 4 }}>
                        <strong>Topic:</strong> {result.match.topicLine}
                      </div>
                      <div>
                        <strong>Your details:</strong>{' '}
                        {result.match.requestDetails.length ? result.match.requestDetails.join(', ') : 'none'}
                      </div>
                      <div className="log" style={{ marginTop: 6 }}>
                        {result.match.candidates.map((c, i) => (
                          <div key={c.templateId}>
                            {i + 1}. <strong>{c.templateId}</strong> · {c.score.toFixed(2)}
                            {' '}(topic {c.topic.toFixed(2)}, details {c.details.toFixed(2)})
                            {c.missing.length > 0 && <> · no slot for {c.missing.join(', ')}</>}
                            {c.emptyContactSlots.length > 0 && <> · placeholder {c.emptyContactSlots.join(', ')}</>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
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
            )}
          </div>
        )}

        <h3 style={{ marginTop: 30, marginBottom: 0, fontSize: 13, color: 'var(--muted)' }}>
          Generated designs
        </h3>
        {saved.length === 0 ? (
          <div className="empty">Nothing yet — generate your first one above.</div>
        ) : (
          <div className="gallery">
            {saved.map((design) => (
              <div key={design.id} className="card" onClick={() => open(design.id)}>
                <div className="thumb">
                  {design.thumbnailUrl ? (
                    <img src={design.thumbnailUrl} alt="" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  ) : (
                    <span style={{ color: 'var(--muted)', fontSize: 11, padding: 10, textAlign: 'center' }}>
                      {design.kind} · {design.aspect}
                    </span>
                  )}
                </div>
                <div className="meta">
                  <div className="title">{design.name || design.id}</div>
                  <div className="sub">
                    {design.templateId ?? 'template'} · {new Date(design.createdAt).toLocaleString()}
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
    </div>
  )
}
