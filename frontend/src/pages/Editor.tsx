/**
 * The editor — IMPLEMENTATION_PLAN §3.
 *
 * "Nothing about the editor knows which pipeline created the document; that is the
 * payoff of the single schema." Everything here operates on `DesignDoc` alone.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import { Inspector } from '../components/Inspector'
import { LayerPanel } from '../components/LayerPanel'
import { DrawListStage, type TransformResult } from '../editor/DrawListStage'
import { loadAll } from '../editor/fonts'
import { findLayer, useDocument } from '../editor/useDocument'
import { api } from '../lib/api'
import type { Layer } from '../lib/types'

const ZOOM_STEPS = [0.1, 0.15, 0.25, 0.35, 0.5, 0.75, 1, 1.5, 2]

export function EditorPage() {
  const { docId } = useParams<{ docId: string }>()
  const navigate = useNavigate()
  const [viewScale, setViewScale] = useState(0.35)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null)
  const [fontFamilies, setFontFamilies] = useState<string[]>([])
  const [motifs, setMotifs] = useState<string[]>([])
  const [rerollable, setRerollable] = useState<string[]>([])
  const [editingText, setEditingText] = useState<{ layerId: string; value: string } | null>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  const {
    doc, drawList, violations, loading, saving, error,
    canUndo, canRedo, mutate, updateLayer, undo, redo, replaceDoc, refreshDrawList, setError,
  } = useDocument(docId, viewScale)

  // Load the exact faces the server shaped with (ADR 0001).
  useEffect(() => {
    api.fonts()
      .then(async (response) => {
        setFontFamilies(response.families)
        await loadAll(response.faces)
        refreshDrawList()
      })
      .catch(() => setFontFamilies([]))
  }, [refreshDrawList])

  useEffect(() => {
    api.motifs()
      .then((r) => { setMotifs(r.motifs); setRerollable(r.rerollable) })
      .catch(() => { setMotifs([]); setRerollable([]) })
  }, [])

  useEffect(() => {
    if (!toast) return
    const timer = window.setTimeout(() => setToast(null), 3600)
    return () => window.clearTimeout(timer)
  }, [toast])

  useEffect(() => {
    if (error) { setToast({ message: error, error: true }); setError(null) }
  }, [error, setError])

  // Fit the canvas to the viewport on first load.
  useEffect(() => {
    if (!doc || !wrapRef.current) return
    const { clientWidth, clientHeight } = wrapRef.current
    const fit = Math.min((clientWidth - 64) / doc.canvas.width, (clientHeight - 64) / doc.canvas.height)
    setViewScale(Math.max(0.1, Math.min(1, Number(fit.toFixed(2)))))
  }, [doc?.id, doc])

  const selectedLayer = useMemo(
    () => (doc && selectedId ? findLayer(doc.layers, selectedId) : null),
    [doc, selectedId],
  )

  /* ---- keyboard (§3.2) --------------------------------------------------------- */
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') return

      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        event.shiftKey ? redo() : undo()
        return
      }
      if (!selectedId || !doc) return
      const nudge = event.shiftKey ? 10 : 1
      const moves: Record<string, [number, number]> = {
        ArrowLeft: [-nudge, 0], ArrowRight: [nudge, 0],
        ArrowUp: [0, -nudge], ArrowDown: [0, nudge],
      }
      if (moves[event.key]) {
        event.preventDefault()
        const [dx, dy] = moves[event.key]
        updateLayer(selectedId, (layer) => { layer.frame.x += dx; layer.frame.y += dy })
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault()
        deleteLayer(selectedId)
      } else if (event.key === 'Escape') {
        setSelectedId(null)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [selectedId, doc, undo, redo, updateLayer])

  /* ---- layer operations -------------------------------------------------------- */

  const deleteLayer = useCallback((layerId: string) => {
    mutate((draft) => {
      const remove = (layers: Layer[]): boolean => {
        const index = layers.findIndex((layer) => layer.id === layerId)
        if (index >= 0) { layers.splice(index, 1); return true }
        return layers.some((layer) => layer.type === 'group' && remove(layer.children))
      }
      remove(draft.layers)
    })
    setSelectedId(null)
  }, [mutate])

  const reorder = useCallback((layerId: string, direction: 1 | -1) => {
    mutate((draft) => {
      const index = draft.layers.findIndex((layer) => layer.id === layerId)
      const next = index + direction
      if (index < 0 || next < 0 || next >= draft.layers.length) return
      const [moved] = draft.layers.splice(index, 1)
      draft.layers.splice(next, 0, moved)
    })
  }, [mutate])

  /** Canvas transform -> document frame. Draw-list pixels are document pixels × scale. */
  const onTransformEnd = useCallback((layerId: string, box: TransformResult) => {
    if (!drawList) return
    const s = drawList.scale || 1
    updateLayer(layerId, (layer) => {
      layer.frame.x = box.x / s
      layer.frame.y = box.y / s
      layer.frame.w = Math.max(1, box.width / s)
      layer.frame.h = Math.max(1, box.height / s)
      layer.frame.rotation = box.rotation
    }, { solve: true })
  }, [drawList, updateLayer])

  const runAiOperation = useCallback(async (key: string, work: () => Promise<void>, done: string) => {
    setBusy(key)
    try {
      await work()
      setToast({ message: done })
    } catch (caught) {
      setToast({ message: caught instanceof Error ? caught.message : String(caught), error: true })
    } finally {
      setBusy(null)
    }
  }, [])

  const onRegenerate = (layerId: string) => runAiOperation(
    `regenerate:${layerId}`,
    async () => {
      await api.regenerateLayer(docId!, layerId)
      const { doc: fresh } = await api.getDoc(docId!)
      replaceDoc(fresh)
    },
    'Layer regenerated',
  )

  const onReshape = (layerId: string, body: { motif?: string; density?: number }) =>
    runAiOperation(
      `reshape:${layerId}`,
      async () => {
        await api.reshapeLayer(docId!, layerId, body)
        const { doc: fresh } = await api.getDoc(docId!)
        replaceDoc(fresh)
      },
      body.motif ? `Motif changed to ${body.motif}` : 'Motif re-rolled',
    )

  const onRemoveBackground = (layerId: string) => runAiOperation(
    `removebg:${layerId}`,
    async () => {
      await api.removeBackground(docId!, layerId)
      const { doc: fresh } = await api.getDoc(docId!)
      replaceDoc(fresh)
    },
    'Background removed',
  )

  const onRewrite = (layerIds: string[], instruction: string) => runAiOperation(
    'rewrite',
    async () => {
      const result = await api.rewriteCopy(docId!, layerIds, instruction)
      replaceDoc(result.doc, result.violations)
    },
    'Copy rewritten',
  )

  const onExport = (format: string, scale: number) => runAiOperation(
    'export',
    async () => {
      const result = await api.exportDoc(docId!, format, scale)
      if (result.url) window.open(result.url, '_blank', 'noopener')
    },
    'Export ready',
  )

  const onResize = (width: number, height: number) => runAiOperation(
    'resize',
    async () => {
      const result = await api.resize(docId!, width, height)
      navigate(`/d/${result.docId}`)
    },
    'Resized into a new document',
  )

  if (loading) {
    return (
      <div className="app">
        <header className="topbar"><span className="brand">Layered Design</span></header>
        <div className="empty" style={{ marginTop: 60 }}><span className="spinner" /> Loading…</div>
      </div>
    )
  }

  if (!doc || !drawList) {
    return (
      <div className="app">
        <header className="topbar">
          <button className="ghost" onClick={() => navigate('/')}>← Back</button>
        </header>
        <div className="empty" style={{ marginTop: 60 }}>Document not found.</div>
      </div>
    )
  }

  return (
    <div className="app">
      <header className="topbar">
        <button className="ghost" onClick={() => navigate('/')}>←</button>
        <input
          value={doc.title}
          onChange={(event) => mutate((draft) => { draft.title = event.target.value }, { history: false })}
          style={{ width: 260, background: 'transparent', border: '1px solid transparent', fontWeight: 600 }}
        />
        <span className="badge">{doc.canvas.width}×{doc.canvas.height}</span>
        <span className="spacer" />
        <button onClick={undo} disabled={!canUndo} title="Undo (⌘Z)">↶</button>
        <button onClick={redo} disabled={!canRedo} title="Redo (⇧⌘Z)">↷</button>
        <button onClick={() => setViewScale((s) => prevZoom(s))} title="Zoom out">−</button>
        <span className="badge">{Math.round(viewScale * 100)}%</span>
        <button onClick={() => setViewScale((s) => nextZoom(s))} title="Zoom in">+</button>
        {saving && <span className="badge"><span className="spinner" /> saving</span>}
        {violations.length > 0 && (
          <span className="badge warn">{violations.length} layout issue{violations.length > 1 ? 's' : ''}</span>
        )}
      </header>

      <div className="editor">
        <LayerPanel
          layers={doc.layers}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onToggleVisible={(id) => updateLayer(id, (layer) => { layer.visible = !layer.visible })}
          onToggleLocked={(id) => updateLayer(id, (layer) => { layer.locked = !layer.locked })}
          onReorder={reorder}
          onDelete={deleteLayer}
        />

        <div className="canvas-wrap" ref={wrapRef}>
          <div className="canvas-frame" style={{ position: 'relative' }}>
            <DrawListStage
              drawList={drawList}
              selectedLayerId={selectedId}
              onSelect={setSelectedId}
              onTransformEnd={onTransformEnd}
              showSafeMargin={doc.canvas.safeMargin}
              onDoubleClick={(layerId) => {
                const layer = findLayer(doc.layers, layerId)
                if (layer?.type === 'text') setEditingText({ layerId, value: layer.content })
              }}
            />
            {editingText && (
              <div className="text-editor" style={{ left: 16, top: 16 }}>
                <textarea
                  autoFocus
                  value={editingText.value}
                  onChange={(event) => setEditingText({ ...editingText, value: event.target.value })}
                  onKeyDown={(event) => {
                    if (event.key === 'Escape') setEditingText(null)
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                      updateLayer(editingText.layerId, (layer) => {
                        if (layer.type === 'text') layer.content = editingText.value
                      }, { solve: true })
                      setEditingText(null)
                    }
                  }}
                />
                <div className="actions">
                  <button onClick={() => setEditingText(null)}>Cancel</button>
                  <button
                    className="primary"
                    onClick={() => {
                      updateLayer(editingText.layerId, (layer) => {
                        if (layer.type === 'text') layer.content = editingText.value
                      }, { solve: true })
                      setEditingText(null)
                    }}
                  >Apply</button>
                </div>
              </div>
            )}
          </div>
        </div>

        <Inspector
          doc={doc}
          layer={selectedLayer}
          violations={violations}
          fontFamilies={fontFamilies}
          busy={busy}
          onUpdate={(layerId, recipe, options) => {
            if (layerId) updateLayer(layerId, recipe, options)
          }}
          onRegenerate={onRegenerate}
          onReshape={onReshape}
          motifs={motifs}
          rerollable={rerollable}
          onRemoveBackground={onRemoveBackground}
          onRewrite={onRewrite}
          onExport={onExport}
          onResize={onResize}
        />
      </div>

      {toast && <div className={`toast ${toast.error ? 'error' : ''}`}>{toast.message}</div>}
    </div>
  )
}

function nextZoom(current: number): number {
  return ZOOM_STEPS.find((step) => step > current + 0.001) ?? ZOOM_STEPS[ZOOM_STEPS.length - 1]
}

function prevZoom(current: number): number {
  return [...ZOOM_STEPS].reverse().find((step) => step < current - 0.001) ?? ZOOM_STEPS[0]
}
