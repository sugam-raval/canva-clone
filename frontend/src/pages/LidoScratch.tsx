/**
 * The scratch flow — `POST /v1/lido/scratch`.
 *
 * Where `LidoFlow` retrieves a template out of the corpus and rewrites its slots, this
 * hits the endpoint that designs the page outright: the model picks the palette, the
 * type scale, the composition and the copy, and the result is saved to
 * `lido_generated/` rather than into the curated corpus.
 *
 * The spec panel is the point of the page — it shows what the model decided and what
 * the layout engine then had to correct, which is the only way to tell a bad design
 * from a bad layout repair. Preview is the same throwaway SVG as the corpus flow.
 */

import { useCallback, useEffect, useState } from 'react'

import { api, ApiError } from '../lib/api'
import { LidoPreview } from '../lib/lidoRender'
import type { LidoLayer, LidoScratchResponse, LidoScratchSummary } from '../lib/lidoTypes'

const KINDS = ['', 'post', 'story', 'poster', 'banner', 'thumbnail', 'ad', 'flyer']

const EXAMPLES = [
  'Minimal ceramics exhibition poster, lots of whitespace, "Form & Fire", opens 12 March',
  'Bold gym promo post, high-contrast, headline "GET STRONG", call 98765 43210',
  'Warm coffee shop story, "Morning Magic", freshly roasted daily, beanbrew.example',
  'Clean fintech LinkedIn banner 1500x500 for a startup called Ledgerly',
]

/** Loose but useful: the model's own element list, so a thin design is visible as a
 * thin design rather than as a preview that just looks empty. */
function SpecPanel({ result }: { result: LidoScratchResponse }) {
  return (
    <>
      <div className="progress">
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Design</div>
        <div style={{ fontWeight: 600 }}>{result.name}</div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>
          {result.kind} · {result.width}×{result.height} · {result.vibe} · {result.layoutStyle}
        </div>
        <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 2 }}>
          ground: {result.backgroundStyle}
          {result.decor.length > 0 && ` · ${result.decor.join(', ')}`}
        </div>
        <div style={{ display: 'flex', gap: 4, marginTop: 10, flexWrap: 'wrap' }}>
          {result.palette.map((color) => (
            <span
              key={color}
              title={color}
              style={{
                width: 22, height: 22, borderRadius: 5, background: color,
                border: '1px solid var(--line)',
              }}
            />
          ))}
        </div>
        <div style={{ marginTop: 10, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className={`badge ${result.llmDesigned ? 'ok' : 'warn'}`}>
            {result.llmDesigned ? 'AI-designed' : 'mechanical fallback'}
          </span>
          {result.fontScale < 1 && (
            <span className="badge warn" title="the page overflowed and the type was scaled to fit">
              type scaled {Math.round(result.fontScale * 100)}%
            </span>
          )}
        </div>
      </div>

      <div className="progress">
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>
          Elements ({result.elements.length})
        </div>
        <div className="log">
          {result.elements.map((element, index) => (
            <div key={index} style={{ display: 'flex', gap: 6, alignItems: 'baseline' }}>
              {element.color && (
                <span
                  style={{
                    width: 8, height: 8, borderRadius: 2, background: element.color,
                    flexShrink: 0, border: '1px solid var(--line)',
                  }}
                />
              )}
              <strong>
                {element.behind ? 'scrim' : element.cutout ? 'cutout' : element.role ?? element.kind}
              </strong>
              <span style={{ color: 'var(--muted)' }}>
                {element.size}
                {element.font !== 'auto' && ` · ${element.font}`}
                {element.tracking && element.tracking !== 'normal' && ` · ${element.tracking}`}
              </span>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {element.text ?? element.imagePrompt ?? ''}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="progress">
        <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 8 }}>Saved to</div>
        <div className="log">
          <div style={{ wordBreak: 'break-all' }}>{result.path}</div>
        </div>
      </div>
    </>
  )
}

export function LidoScratchFlow() {
  const [prompt, setPrompt] = useState('')
  const [kind, setKind] = useState('')
  const [withImages, setWithImages] = useState(true)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<LidoScratchResponse | null>(null)
  const [layers, setLayers] = useState<Record<string, LidoLayer> | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)
  const [saved, setSaved] = useState<LidoScratchSummary[]>([])

  const refresh = useCallback(async () => {
    try { setSaved(await api.lidoScratchList()) } catch { /* gallery is non-critical */ }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  const generate = async () => {
    if (!prompt.trim() || running) return
    setRunning(true)
    setError(null)
    setResult(null)
    setLayers(null)
    const started = performance.now()
    try {
      const response = await api.lidoScratch(prompt.trim(), {
        kind: kind || undefined,
        generateImages: withImages,
      })
      setResult(response)
      setLayers(response.document?.[0]?.layers ?? null)
      setElapsedMs(performance.now() - started)
      refresh()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    } finally {
      setRunning(false)
    }
  }

  const open = async (designId: string) => {
    setError(null)
    try {
      const response = await api.lidoScratchGet(designId)
      setLayers(response.document?.[0]?.layers ?? null)
      setResult(null)
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    }
  }

  return (
    <div className="home">
      <div className="hero">
        <h1>Design from scratch</h1>
        <p>
          Describe a design. This hits <code>/v1/lido/scratch</code>: no template is retrieved
          or referenced — the model composes the canvas, palette, type scale, layout and copy
          itself, the layout engine repairs the geometry, and the finished document is saved
          to <code>lido_generated/</code>.{' '}
          <span style={{ color: 'var(--accent-2)' }}>Throwaway SVG preview — not the real Lido.js editor.</span>
        </p>
      </div>

      <div className="prompt-box">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder='e.g. Minimal ceramics exhibition poster, lots of whitespace, "Form & Fire"'
          onKeyDown={(e) => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) generate() }}
          disabled={running}
        />
        <div className="prompt-row">
          <select value={kind} onChange={(e) => setKind(e.target.value)} disabled={running} style={{ maxWidth: 160 }}>
            {KINDS.map((k) => <option key={k} value={k}>{k || 'auto-detect kind'}</option>)}
          </select>
          <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--muted)' }}>
            <input
              type="checkbox"
              checked={withImages}
              onChange={(e) => setWithImages(e.target.checked)}
              disabled={running}
            />
            generate images
          </label>
          <button className="primary" onClick={generate} disabled={running || !prompt.trim()}>
            {running ? <span className="spinner" /> : 'Design it'}
          </button>
          {elapsedMs != null && !running && (
            <span className="badge">{(elapsedMs / 1000).toFixed(1)}s</span>
          )}
        </div>
        <div className="examples">
          {EXAMPLES.map((example) => (
            <button key={example} onClick={() => setPrompt(example)} disabled={running}>
              {example.length > 50 ? `${example.slice(0, 50)}…` : example}
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
          <div>{result && <SpecPanel result={result} />}</div>
        </div>
      )}

      <h3 style={{ marginTop: 30, marginBottom: 0, fontSize: 13, color: 'var(--muted)' }}>
        Generated designs
      </h3>
      {saved.length === 0 ? (
        <div className="empty">Nothing yet — design your first one above.</div>
      ) : (
        <div className="gallery">
          {saved.map((design) => (
            <div key={design.id} className="card" onClick={() => open(design.id)}>
              <div className="thumb">
                <span style={{ color: 'var(--muted)', fontSize: 11, padding: 10, textAlign: 'center' }}>
                  {design.kind} · {design.aspect}
                </span>
              </div>
              <div className="meta">
                <div className="title">{design.name || design.id}</div>
                <div className="sub">
                  {design.generatedAt ? new Date(design.generatedAt).toLocaleString() : design.prompt}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
