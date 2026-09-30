/**
 * "Design a new template": `POST /v1/lido/drafts` — the AI designs a brand-new template
 * (layout, decoration, colours, fonts and copy) from a prompt and saves it as a draft in
 * lidojs_templates/drafts/. Shows the result and every draft for review. Photos are
 * placeholders from the corpus until image generation is added.
 */

import { useCallback, useEffect, useState } from 'react'

import { api, ApiError } from '../lib/api'
import { LidoPreview } from '../lib/lidoRender'
import type { LidoDraftInfo } from '../lib/lidoTypes'

const EXAMPLES = [
  {
    label: 'PC launch ad',
    prompt: `Premium, modern launch ad for a new high-performance desktop PC, sleek futuristic tower as the hero, blue and white tech look with elegant geometric elements.
Headline: NEW PC HAS ARRIVED
Subheadline: Power. Speed. Performance. Built for What's Next.
Features: Latest Generation Processor, 16GB High-Speed RAM, 1TB SSD Storage, Powerful Graphics
Price: Starting at ₹59,999
Offer: Free Wireless Keyboard & Mouse
CTA: ORDER NOW
Contact: +91 98765 43210, www.techworld.com`,
  },
  {
    label: 'Café opening',
    prompt: 'Warm, cosy grand opening post for a neighbourhood specialty coffee café. Headline "Now Brewing", opening day Saturday 12 October, first coffee free, address 42 Main Street. Earthy browns and cream, friendly and inviting.',
  },
  {
    label: 'Yoga studio',
    prompt: 'Calm, minimal post for a yoga studio launching morning classes. Headline "Find Your Balance", 3 class types: Hatha, Vinyasa, Meditation. Soft sage green and off-white, lots of breathing room. Book at www.calmyoga.com',
  },
  {
    label: 'Fitness sale',
    prompt: 'Bold, high-energy gym membership sale. Headline "NO EXCUSES", 40% off annual membership, this week only, call 98765 43210. Black with a neon accent, strong and aggressive.',
  },
]

function Swatches({ colors }: { colors: Record<string, string> }) {
  const roles = ['bg', 'ink', 'accent', 'on_accent', 'soft'].filter((r) => colors[r])
  if (roles.length === 0) return null
  return (
    <span style={{ display: 'inline-flex', gap: 4, verticalAlign: 'middle' }}>
      {roles.map((role) => (
        <span key={role} title={`${role} ${colors[role]}`} style={{
          width: 16, height: 16, borderRadius: 4, background: colors[role],
          border: '1px solid var(--line)', display: 'inline-block',
        }} />
      ))}
    </span>
  )
}

function Preview({ draft, big }: { draft: LidoDraftInfo; big?: boolean }) {
  if (draft.previewUrl) {
    return <img src={draft.previewUrl} alt={draft.name ?? draft.id}
      style={{ width: '100%', display: 'block', borderRadius: big ? 6 : 0 }} />
  }
  const layers = draft.document?.[0]?.layers
  if (layers) return <LidoPreview layers={layers} />
  return <span style={{ color: 'var(--muted)', fontSize: 11 }}>no preview</span>
}

function download(draft: LidoDraftInfo) {
  if (!draft.document) return
  const blob = new Blob([JSON.stringify(draft.document, null, 2)], { type: 'application/json' })
  const link = document.createElement('a')
  link.href = URL.createObjectURL(blob)
  link.download = `${draft.id}.json`
  link.click()
  URL.revokeObjectURL(link.href)
}

function DraftDetail({ draft, onDelete }: { draft: LidoDraftInfo; onDelete: () => void }) {
  const passed = draft.problems.length === 0
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 320px', gap: 20, marginTop: 16 }}>
      <div className="canvas-wrap" style={{ borderRadius: 10 }}>
        <div className="canvas-frame" style={{ width: '100%', maxWidth: 620 }}>
          <Preview draft={draft} big />
        </div>
      </div>
      <div>
        <div className="progress" style={{ marginTop: 0 }}>
          <div style={{ fontWeight: 600 }}>{draft.name || draft.layout || draft.id}</div>
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            {draft.id} · {draft.source}{draft.attempts ? ` · ${draft.attempts} attempt(s)` : ''}
          </div>
          {draft.idea && <div style={{ fontSize: 13, marginTop: 8 }}>{draft.idea}</div>}
          {draft.direction && (
            <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 6 }}>
              Direction: {draft.direction}
            </div>
          )}
          <div style={{ fontSize: 12, marginTop: 10, display: 'grid', gap: 4 }}>
            {Object.keys(draft.colors).length > 0 && (
              <div><strong>Colours:</strong> <Swatches colors={draft.colors} /></div>
            )}
            {draft.fonts && <div><strong>Fonts:</strong> {draft.fonts}</div>}
            {draft.textCount != null && <div><strong>Text boxes:</strong> {draft.textCount}</div>}
          </div>
          <div style={{ marginTop: 10 }}>
            <span className={`badge ${passed ? 'ok' : 'warn'}`}>
              {passed ? 'passes all design checks' : `${draft.problems.length} check(s) failing`}
            </span>
          </div>
          {!passed && (
            <div className="log" style={{ marginTop: 6, fontSize: 11, color: 'var(--accent-2)' }}>
              {draft.problems.map((p) => <div key={p}>• {p}</div>)}
            </div>
          )}
        </div>

        {draft.photoSubjects.length > 0 && (
          <div className="progress">
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>
              Photo subjects (placeholder photos for now — these become the image prompts)
            </div>
            <div className="log">
              {draft.photoSubjects.map((s, i) => <div key={i}>{i + 1}. {s}</div>)}
            </div>
          </div>
        )}

        {draft.prompt && (
          <div className="progress">
            <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>Prompt</div>
            <div style={{ fontSize: 12, whiteSpace: 'pre-wrap', maxHeight: 140, overflowY: 'auto' }}>
              {draft.prompt}
            </div>
          </div>
        )}

        <div className="progress">
          <div style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 6 }}>Saved as</div>
          <code style={{ fontSize: 11 }}>lidojs_templates/drafts/{draft.id}.json</code>
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={() => download(draft)} disabled={!draft.document}>Download JSON</button>
            <button className="danger" onClick={onDelete}>Delete</button>
          </div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 8 }}>
            To use it: move the JSON into <code>lidojs_templates/</code> and its PNG into{' '}
            <code>lidojs_templates/previews/</code>, then{' '}
            <code>make lido-add TEMPLATE={draft.id} KIND=post</code>.
          </div>
        </div>
      </div>
    </div>
  )
}

export function DraftStudio() {
  const [prompt, setPrompt] = useState('')
  const [variations, setVariations] = useState(1)
  const [running, setRunning] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [created, setCreated] = useState<LidoDraftInfo[]>([])
  const [selected, setSelected] = useState<LidoDraftInfo | null>(null)
  const [all, setAll] = useState<LidoDraftInfo[]>([])

  const refresh = useCallback(async () => {
    try { setAll(await api.lidoDrafts()) } catch { /* the gallery is non-critical */ }
  }, [])

  useEffect(() => { refresh() }, [refresh])

  useEffect(() => {
    if (!running) return
    const started = Date.now()
    const timer = setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [running])

  const design = async () => {
    if (prompt.trim().length < 3 || running) return
    setRunning(true)
    setElapsed(0)
    setError(null)
    setCreated([])
    try {
      const drafts = await api.lidoDraftCreate(prompt.trim(), variations)
      setCreated(drafts)
      setSelected(drafts[0] ?? null)
      refresh()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    } finally {
      setRunning(false)
    }
  }

  const open = async (id: string) => {
    setError(null)
    try {
      setSelected(await api.lidoDraft(id))
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    }
  }

  const remove = async (id: string) => {
    if (!window.confirm(`Delete draft ${id}? This removes its JSON and preview.`)) return
    try {
      await api.lidoDraftDelete(id)
      setCreated((list) => list.filter((d) => d.id !== id))
      setSelected((current) => (current?.id === id ? null : current))
      refresh()
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : String(caught))
    }
  }

  return (
    <div className="home">
      <div className="hero">
        <h1>Design a new template</h1>
        <p>
          Describe the design you want — the message, the mood and colours, the exact copy
          (headline, price, offer, contact). The AI designs a brand-new template from it:
          layout, decoration, colours, fonts and text, checked for fit and readability, and
          saves it as a draft for review. Photos are placeholders for now.
        </p>
      </div>

      <div className="prompt-box">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          placeholder={'e.g. Bold launch post for a new smartphone, dark with an electric blue accent.\nHeadline: MEET THE X1  ·  Price: from $699  ·  CTA: Pre-order now  ·  www.example.com'}
          disabled={running}
          style={{ minHeight: 130 }}
        />
        <div className="prompt-row">
          <select value={variations} onChange={(e) => setVariations(Number(e.target.value))}
            disabled={running} style={{ maxWidth: 190 }}
            title="Each variation is designed in a different creative direction">
            <option value={1}>1 design</option>
            <option value={2}>2 variations</option>
            <option value={3}>3 variations</option>
          </select>
          <button className="primary" onClick={design} disabled={running || prompt.trim().length < 3}>
            {running ? <span className="spinner" /> : 'Design template'}
          </button>
          {running && (
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              Designing with AI… {elapsed}s (usually 30–120 s; each variation runs in parallel)
            </span>
          )}
        </div>
        <div className="examples">
          {EXAMPLES.map((example) => (
            <button key={example.label} onClick={() => setPrompt(example.prompt)} disabled={running}>
              {example.label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="toast error" style={{ position: 'static', margin: '16px 0' }}>{error}</div>}

      {created.length > 1 && (
        <div style={{ display: 'flex', gap: 10, marginTop: 16 }}>
          {created.map((d) => (
            <div key={d.id} className="card" onClick={() => setSelected(d)}
              style={{ width: 150, borderColor: selected?.id === d.id ? 'var(--accent)' : undefined }}>
              <div className="thumb" style={{ aspectRatio: '1' }}><Preview draft={d} /></div>
              <div className="meta"><div className="title">{d.name || d.id}</div></div>
            </div>
          ))}
        </div>
      )}

      {selected && <DraftDetail draft={selected} onDelete={() => remove(selected.id)} />}

      <h3 style={{ marginTop: 30, marginBottom: 0, fontSize: 13, color: 'var(--muted)' }}>
        Drafts ({all.length})
      </h3>
      {all.length === 0 ? (
        <div className="empty">No drafts yet — describe a design above.</div>
      ) : (
        <div className="gallery">
          {all.map((d) => (
            <div key={d.id} className="card" onClick={() => open(d.id)}
              style={{ borderColor: selected?.id === d.id ? 'var(--accent)' : undefined }}>
              <div className="thumb" style={{ aspectRatio: '1' }}><Preview draft={d} /></div>
              <div className="meta">
                <div className="title">{d.name || d.layout || d.id}</div>
                <div className="sub">
                  {d.id} · {d.source}{d.problems.length ? ` · ${d.problems.length} issue(s)` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
