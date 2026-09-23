/**
 * Prompt entry, live generation progress, and the document gallery.
 *
 * Progress rendering is the §0.9 contract made visible: the user sees `doc.skeleton`
 * within a few hundred milliseconds and watches each `layer.patch` land, rather than
 * waiting on a spinner until everything is finished.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { api, subscribeProgress } from '../lib/api'
import type { DocSummary, ProgressEvent } from '../lib/types'
import { LidoFlow } from './LidoTest'
import { LidoScratchFlow } from './LidoScratch'

type Flow = 'custom' | 'lido' | 'scratch'

const EXAMPLES = [
  'Instagram story for a new running shoe, minimal and premium, headline "Run Lighter"',
  'Bold YouTube thumbnail about cheap flights to Japan',
  'Square sale post for wireless headphones, 50% off, loud and high-contrast',
  'Minimal gallery poster, lots of whitespace, no photo',
  'LinkedIn banner 1500x500 for a fintech startup, clean tech feel',
  'Event flyer for a weekend farmers market, warm and natural',
]

const PLAN_LABELS: Record<string, string> = {
  'brief.parse': 'parse',
  'art.direct': 'art direction',
  'template.retrieve': 'retrieve',
  'compose.layout': 'compose',
  'asset.background': 'background',
  'asset.subject': 'subject',
  'harmonize.palette': 'palette',
  'harmonize.contrast': 'contrast',
  'harmonize.shadow': 'shadow',
  'layout.solve': 'solve',
  'doc.assemble': 'assemble',
  'doc.thumbnail': 'thumbnail',
}

export function HomePage() {
  const navigate = useNavigate()
  const [flow, setFlow] = useState<Flow>('custom')
  const [prompt, setPrompt] = useState('')
  const [running, setRunning] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const [stage, setStage] = useState<string>('')
  const [docs, setDocs] = useState<DocSummary[]>([])
  const [error, setError] = useState<string | null>(null)
  const [health, setHealth] = useState<{ openaiConfigured: boolean; adapters: Record<string, string> } | null>(null)
  const startedAt = useRef(0)
  const unsubscribe = useRef<(() => void) | null>(null)

  const refresh = useCallback(async () => {
    try { setDocs(await api.listDocs()) } catch { /* gallery is non-critical */ }
  }, [])

  useEffect(() => {
    refresh()
    api.health().then(setHealth).catch(() => setHealth(null))
    return () => unsubscribe.current?.()
  }, [refresh])

  const append = (line: string) => {
    const elapsed = ((performance.now() - startedAt.current) / 1000).toFixed(2)
    setLog((previous) => [...previous.slice(-60), `[${elapsed}s] ${line}`])
  }

  const generate = async () => {
    if (!prompt.trim() || running) return
    setRunning(true); setLog([]); setError(null); setStage('brief.parse')
    startedAt.current = performance.now()

    try {
      const { requestId } = await api.generate(prompt.trim(), 1)
      append(`request ${requestId.slice(0, 8)} started`)

      unsubscribe.current = subscribeProgress(requestId, (event: ProgressEvent) => {
        switch (event.t) {
          case 'brief.ready': {
            const brief = event.brief as { kind?: string; canvas?: { width: number; height: number } }
            append(`brief: ${brief.kind} ${brief.canvas?.width}×${brief.canvas?.height}`)
            setStage('compose.layout')
            break
          }
          case 'doc.skeleton':
            append(`skeleton ready — ${event.doc.layers.length} layers`)
            setStage('asset.background')
            break
          case 'layer.patch':
            append(`asset arrived for ${event.layerId}`)
            break
          case 'job.failed':
            append(`! ${event.type} failed: ${event.reason}`)
            break
          case 'doc.solved':
            append(`solved — ${event.violations.length} violation(s)`)
            setStage('doc.assemble')
            break
          case 'request.done':
            append(event.summary || 'done')
            setStage('')
            setRunning(false)
            refresh()
            if (event.docId) navigate(`/d/${event.docId}`)
            break
          case 'request.failed':
            setError(event.reason)
            setRunning(false)
            setStage('')
            break
          case 'request.clarify':
            append(`needs clarification: ${event.question}`)
            setRunning(false)
            break
          default:
            break
        }
      }, (streamError) => {
        setError(streamError.message)
        setRunning(false)
      })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
      setRunning(false)
    }
  }

  const plan = Object.keys(PLAN_LABELS)
  const stageIndex = plan.indexOf(stage)

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">Layered Design</span>
        <div className="flow-toggle">
          <button
            className={flow === 'custom' ? 'active' : ''}
            onClick={() => setFlow('custom')}
          >
            Custom (DesignDoc)
          </button>
          <button
            className={flow === 'lido' ? 'active' : ''}
            onClick={() => setFlow('lido')}
          >
            Lido.js (template)
          </button>
          <button
            className={flow === 'scratch' ? 'active' : ''}
            onClick={() => setFlow('scratch')}
          >
            Lido.js (scratch)
          </button>
        </div>
        <span className="spacer" />
        {health && (
          <span className={`badge ${health.openaiConfigured ? 'ok' : 'warn'}`}>
            {health.openaiConfigured ? 'OpenAI connected' : 'no API key — stub adapters'}
          </span>
        )}
      </header>

      {flow === 'lido' ? (
        <LidoFlow />
      ) : flow === 'scratch' ? (
        <LidoScratchFlow />
      ) : (
        <div className="home">
          <div className="hero">
            <h1>Describe a design</h1>
            <p>
              A prompt becomes a real multi-layer document: live text, transparent subjects,
              shapes and effects — all independently editable, never flattened.
            </p>
          </div>

          <div className="prompt-box">
            <textarea
              value={prompt}
              placeholder={'e.g. Instagram story for a new running shoe, minimal and premium, headline "Run Lighter"'}
              onChange={(event) => setPrompt(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) generate()
              }}
              disabled={running}
            />
            <div className="prompt-row">
              <button className="primary" onClick={generate} disabled={running || !prompt.trim()}>
                {running ? <><span className="spinner" /> Generating…</> : 'Generate design'}
              </button>
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>⌘↵ to generate</span>
            </div>
            <div className="examples">
              {EXAMPLES.map((example) => (
                <button key={example} onClick={() => setPrompt(example)} disabled={running}>
                  {example.length > 52 ? `${example.slice(0, 52)}…` : example}
                </button>
              ))}
            </div>
          </div>

          {(running || log.length > 0) && (
            <div className="progress">
              <div className="steps">
                {plan.map((step, index) => (
                  <span
                    key={step}
                    className={`step ${
                      stage === step ? 'active' : stageIndex > index || (!stage && log.length) ? 'done' : ''
                    }`}
                  >
                    {PLAN_LABELS[step]}
                  </span>
                ))}
              </div>
              <div className="log">
                {log.map((line, index) => <div key={index}>{line}</div>)}
              </div>
            </div>
          )}

          {error && <div className="toast error">{error}</div>}

          <h3 style={{ marginTop: 30, marginBottom: 0, fontSize: 13, color: 'var(--muted)' }}>
            Your designs
          </h3>
          {docs.length === 0 ? (
            <div className="empty">Nothing yet — generate your first design above.</div>
          ) : (
            <div className="gallery">
              {docs.map((doc) => (
                <div key={doc.id} className="card" onClick={() => navigate(`/d/${doc.id}`)}>
                  <div className="thumb">
                    {doc.thumbUrl
                      ? <img src={doc.thumbUrl} alt={doc.title} loading="lazy" />
                      : <span style={{ color: 'var(--muted)', fontSize: 11 }}>no preview</span>}
                  </div>
                  <div className="meta">
                    <div className="title">{doc.title}</div>
                    <div className="sub">
                      {doc.updatedAt ? new Date(doc.updatedAt).toLocaleString() : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
