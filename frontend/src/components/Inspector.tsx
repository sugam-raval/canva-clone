/** Per-layer inspector — geometry, type, colour, effects, and AI operations (§3.2, §3.3). */

import { useState } from 'react'

import type { DesignDoc, Effect, Layer, Violation } from '../lib/types'

export interface InspectorProps {
  doc: DesignDoc
  layer: Layer | null
  violations: Violation[]
  fontFamilies: string[]
  busy: string | null
  onUpdate: (layerId: string, recipe: (layer: Layer) => void, options?: { solve?: boolean }) => void
  onRegenerate: (layerId: string) => void
  onReshape: (layerId: string, body: { motif?: string; density?: number }) => void
  motifs: string[]
  rerollable: string[]
  onRemoveBackground: (layerId: string) => void
  onRewrite: (layerIds: string[], instruction: string) => void
  onExport: (format: string, scale: number) => void
  onResize: (width: number, height: number) => void
}

const PRESETS: { label: string; width: number; height: number }[] = [
  { label: 'Story 9:16', width: 1080, height: 1920 },
  { label: 'Post 4:5', width: 1080, height: 1350 },
  { label: 'Square', width: 1080, height: 1080 },
  { label: 'Thumbnail 16:9', width: 1280, height: 720 },
  { label: 'Banner 3:1', width: 1500, height: 500 },
  { label: 'Ad 1.91:1', width: 1200, height: 628 },
]

export function Inspector({
  doc, layer, violations, fontFamilies, busy, motifs, rerollable,
  onUpdate, onRegenerate, onReshape, onRemoveBackground, onRewrite, onExport, onResize,
}: InspectorProps) {
  const [instruction, setInstruction] = useState('')
  const [exportFormat, setExportFormat] = useState('png')
  const [exportScale, setExportScale] = useState(1)

  const layerViolations = violations.filter((v) => !layer || v.layerId === layer.id)

  return (
    <div className="pane right">
      <h3>{layer ? `${layer.type} · ${layer.role}` : 'Document'}</h3>
      <div className="scroll">
        {!layer && (
          <>
            <div className="field">
              <label>Title</label>
              <input
                value={doc.title}
                onChange={(event) => {
                  const title = event.target.value
                  onUpdate('', () => {}, {})
                  // Title lives on the document, not a layer; handled by the page.
                  document.dispatchEvent(new CustomEvent('doc-title', { detail: title }))
                }}
              />
            </div>
            <div className="field">
              <label>Canvas</label>
              <div className="row">
                <span style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>
                  {doc.canvas.width} × {doc.canvas.height} @ {doc.canvas.dpi}dpi
                </span>
              </div>
            </div>
            <div className="field">
              <label>Palette</label>
              <div className="swatches">
                {doc.palette.map((color) => (
                  <button key={color} className="swatch" style={{ background: color }} title={color} />
                ))}
              </div>
            </div>
            <div className="field">
              <label>Resize to another format</label>
              <div className="swatches">
                {PRESETS.map((preset) => (
                  <button
                    key={preset.label}
                    style={{ fontSize: 11, padding: '4px 8px' }}
                    disabled={!!busy}
                    onClick={() => onResize(preset.width, preset.height)}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              <div className="hint" style={{ padding: '8px 0 0' }}>
                Creates a new document; constraints reflow the layout.
              </div>
            </div>
          </>
        )}

        {layer && (
          <>
            <div className="field">
              <label>Position &amp; size</label>
              <div className="row">
                <NumberInput label="X" value={layer.frame.x} onChange={(v) => onUpdate(layer.id, (l) => { l.frame.x = v })} />
                <NumberInput label="Y" value={layer.frame.y} onChange={(v) => onUpdate(layer.id, (l) => { l.frame.y = v })} />
              </div>
              <div className="row" style={{ marginTop: 6 }}>
                <NumberInput label="W" value={layer.frame.w} onChange={(v) => onUpdate(layer.id, (l) => { l.frame.w = Math.max(1, v) }, { solve: true })} />
                <NumberInput label="H" value={layer.frame.h} onChange={(v) => onUpdate(layer.id, (l) => { l.frame.h = Math.max(1, v) }, { solve: true })} />
              </div>
              <div className="row" style={{ marginTop: 6 }}>
                <NumberInput label="Rotation" value={layer.frame.rotation} onChange={(v) => onUpdate(layer.id, (l) => { l.frame.rotation = v })} />
              </div>
            </div>

            <div className="field">
              <label>Opacity — {Math.round(layer.opacity * 100)}%</label>
              <input
                type="range" min={0} max={1} step={0.01} value={layer.opacity}
                onChange={(event) => onUpdate(layer.id, (l) => { l.opacity = Number(event.target.value) })}
              />
            </div>

            <div className="field">
              <label>Blend mode</label>
              <select
                value={layer.blendMode}
                onChange={(event) => onUpdate(layer.id, (l) => { l.blendMode = event.target.value as Layer['blendMode'] })}
              >
                {['normal', 'multiply', 'screen', 'overlay', 'soft-light', 'darken', 'lighten', 'color-dodge', 'difference']
                  .map((mode) => <option key={mode} value={mode}>{mode}</option>)}
              </select>
            </div>

            <div className="field">
              <label>Drop shadow</label>
              <div className="row">
                <button
                  style={{ flex: 1 }}
                  onClick={() => onUpdate(layer.id, (l) => {
                    const at = l.effects.findIndex((e) => e.kind === 'shadow')
                    if (at >= 0) l.effects.splice(at, 1)
                    else l.effects.push({ kind: 'shadow', dx: 0, dy: 8, blur: 24, color: '#000000', opacity: 0.3 })
                  })}
                >{shadowOf(layer) ? 'Remove shadow' : 'Add shadow'}</button>
              </div>
              {(() => {
                const shadow = shadowOf(layer)
                if (!shadow) return null
                const edit = (recipe: (s: Extract<Effect, { kind: 'shadow' }>) => void) =>
                  onUpdate(layer.id, (l) => {
                    const found = l.effects.find((e) => e.kind === 'shadow')
                    if (found && found.kind === 'shadow') recipe(found)
                  })
                return (
                  <>
                    <div className="row" style={{ marginTop: 6 }}>
                      <NumberInput label="X" value={shadow.dx} onChange={(v) => edit((e) => { e.dx = v })} />
                      <NumberInput label="Y" value={shadow.dy} onChange={(v) => edit((e) => { e.dy = v })} />
                      <NumberInput label="Blur" value={shadow.blur} onChange={(v) => edit((e) => { e.blur = Math.max(0, v) })} />
                    </div>
                    <div className="row" style={{ marginTop: 6 }}>
                      <input
                        type="color" value={shadow.color}
                        onChange={(event) => edit((e) => { e.color = event.target.value })}
                      />
                      <label style={{ flex: 1, fontSize: 11, color: 'var(--muted)' }}>
                        Opacity — {Math.round(shadow.opacity * 100)}%
                        <input
                          type="range" min={0} max={1} step={0.01} value={shadow.opacity}
                          onChange={(event) => edit((e) => { e.opacity = Number(event.target.value) })}
                          style={{ marginTop: 3 }}
                        />
                      </label>
                    </div>
                  </>
                )
              })()}
            </div>

            {layer.type === 'text' && (
              <>
                <div className="field">
                  <label>Text</label>
                  <textarea
                    value={layer.content}
                    rows={3}
                    onChange={(event) => onUpdate(layer.id, (l) => {
                      if (l.type === 'text') l.content = event.target.value
                    }, { solve: true })}
                  />
                </div>
                <div className="field">
                  <label>Font</label>
                  <select
                    value={layer.fontFamily}
                    onChange={(event) => onUpdate(layer.id, (l) => {
                      if (l.type === 'text') l.fontFamily = event.target.value
                    }, { solve: true })}
                  >
                    {fontFamilies.map((family) => <option key={family} value={family}>{family}</option>)}
                  </select>
                  <div className="row" style={{ marginTop: 6 }}>
                    <NumberInput label="Size" value={layer.fontSize} onChange={(v) => onUpdate(layer.id, (l) => {
                      if (l.type === 'text') l.fontSize = Math.max(4, v)
                    }, { solve: true })} />
                    <NumberInput label="Weight" value={layer.fontWeight} step={100} onChange={(v) => onUpdate(layer.id, (l) => {
                      if (l.type === 'text') l.fontWeight = Math.min(900, Math.max(100, v))
                    }, { solve: true })} />
                  </div>
                  <div className="row" style={{ marginTop: 6 }}>
                    <NumberInput label="Tracking" value={layer.letterSpacing} step={0.5} onChange={(v) => onUpdate(layer.id, (l) => {
                      if (l.type === 'text') l.letterSpacing = v
                    }, { solve: true })} />
                    <NumberInput label="Leading" value={layer.lineHeight} step={0.02} onChange={(v) => onUpdate(layer.id, (l) => {
                      if (l.type === 'text') l.lineHeight = Math.max(0.6, v)
                    }, { solve: true })} />
                  </div>
                </div>
                <div className="field">
                  <label>Alignment</label>
                  <div className="row">
                    {(['left', 'center', 'right'] as const).map((align) => (
                      <button
                        key={align}
                        style={{ flex: 1, background: layer.type === 'text' && layer.align === align ? 'var(--accent)' : undefined,
                                 color: layer.type === 'text' && layer.align === align ? '#04121d' : undefined }}
                        onClick={() => onUpdate(layer.id, (l) => { if (l.type === 'text') l.align = align }, { solve: true })}
                      >{align}</button>
                    ))}
                  </div>
                  <div className="row" style={{ marginTop: 6 }}>
                    {(['none', 'uppercase', 'capitalize'] as const).map((transform) => (
                      <button
                        key={transform}
                        style={{ flex: 1, fontSize: 11,
                                 background: layer.type === 'text' && layer.textTransform === transform ? 'var(--accent)' : undefined,
                                 color: layer.type === 'text' && layer.textTransform === transform ? '#04121d' : undefined }}
                        onClick={() => onUpdate(layer.id, (l) => { if (l.type === 'text') l.textTransform = transform }, { solve: true })}
                      >{transform === 'none' ? 'Aa' : transform === 'uppercase' ? 'AA' : 'Aa·'}</button>
                    ))}
                  </div>
                </div>
                <div className="field">
                  <label>Colour</label>
                  <div className="row">
                    <input
                      type="color" value={layer.color}
                      onChange={(event) => onUpdate(layer.id, (l) => { if (l.type === 'text') l.color = event.target.value })}
                    />
                  </div>
                  <div className="swatches" style={{ marginTop: 6 }}>
                    {doc.palette.map((color) => (
                      <button
                        key={color}
                        className={`swatch ${layer.type === 'text' && layer.color.toUpperCase() === color.toUpperCase() ? 'active' : ''}`}
                        style={{ background: color }} title={color}
                        onClick={() => onUpdate(layer.id, (l) => { if (l.type === 'text') l.color = color })}
                      />
                    ))}
                  </div>
                  {typeof layer.meta.notes?.contrastRatio === 'number' && (
                    <div className="hint" style={{ padding: '8px 0 0' }}>
                      contrast {(layer.meta.notes.contrastRatio as number).toFixed(2)}:1
                      {layer.meta.notes.contrastFix ? ` · ${layer.meta.notes.contrastFix}` : ''}
                    </div>
                  )}
                </div>
                <div className="field">
                  <label>Outline</label>
                  <div className="row">
                    <button
                      style={{ flex: 1 }}
                      onClick={() => onUpdate(layer.id, (l) => {
                        if (l.type !== 'text') return
                        l.stroke = l.stroke ? null : { color: doc.palette[0] ?? '#000000', width: 2 }
                      })}
                    >{layer.stroke ? 'Remove outline' : 'Add outline'}</button>
                  </div>
                  {layer.stroke && (
                    <div className="row" style={{ marginTop: 6 }}>
                      <input
                        type="color" value={layer.stroke.color}
                        onChange={(event) => onUpdate(layer.id, (l) => {
                          if (l.type === 'text' && l.stroke) l.stroke.color = event.target.value
                        })}
                      />
                      <NumberInput
                        label="Width" value={layer.stroke.width} step={0.5}
                        onChange={(v) => onUpdate(layer.id, (l) => {
                          if (l.type === 'text' && l.stroke) l.stroke.width = Math.max(0, v)
                        })}
                      />
                    </div>
                  )}
                </div>

                <div className="field">
                  <label>Rewrite copy with AI</label>
                  <input
                    placeholder="e.g. make it punchier, under 4 words"
                    value={instruction}
                    onChange={(event) => setInstruction(event.target.value)}
                  />
                  <button
                    style={{ marginTop: 6, width: '100%' }}
                    disabled={!instruction.trim() || !!busy}
                    onClick={() => { onRewrite([layer.id], instruction); setInstruction('') }}
                  >
                    {busy === 'rewrite' ? <><span className="spinner" /> Rewriting…</> : 'Rewrite'}
                  </button>
                </div>
              </>
            )}

            {layer.type === 'shape' && (
              <>
                <div className="field">
                  <label>Fill</label>
                  <div className="row">
                    <input
                      type="color" value={layer.fill ?? '#ffffff'}
                      onChange={(event) => onUpdate(layer.id, (l) => { if (l.type === 'shape') l.fill = event.target.value })}
                    />
                    <NumberInput label="Radius" value={layer.radius} onChange={(v) => onUpdate(layer.id, (l) => {
                      if (l.type === 'shape') l.radius = Math.max(0, v)
                    })} />
                  </div>
                  <div className="swatches" style={{ marginTop: 6 }}>
                    {doc.palette.map((color) => (
                      <button key={color} className="swatch" style={{ background: color }} title={color}
                        onClick={() => onUpdate(layer.id, (l) => { if (l.type === 'shape') l.fill = color })} />
                    ))}
                  </div>
                </div>

                <div className="field">
                  <label>Stroke</label>
                  <div className="row">
                    <button
                      style={{ flex: 1 }}
                      onClick={() => onUpdate(layer.id, (l) => {
                        if (l.type !== 'shape') return
                        l.stroke = l.stroke ? null : { color: doc.palette[0] ?? '#000000', width: 2 }
                      })}
                    >{layer.stroke ? 'Remove stroke' : 'Add stroke'}</button>
                  </div>
                  {layer.stroke && (
                    <div className="row" style={{ marginTop: 6 }}>
                      <input
                        type="color" value={layer.stroke.color}
                        onChange={(event) => onUpdate(layer.id, (l) => {
                          if (l.type === 'shape' && l.stroke) l.stroke.color = event.target.value
                        })}
                      />
                      <NumberInput
                        label="Width" value={layer.stroke.width} step={0.5}
                        onChange={(v) => onUpdate(layer.id, (l) => {
                          if (l.type === 'shape' && l.stroke) l.stroke.width = Math.max(0, v)
                        })}
                      />
                    </div>
                  )}
                </div>

                {layer.meta.ornament && (() => {
                  const canReroll = rerollable.length === 0
                    || rerollable.includes(layer.meta.ornament.motif)
                  return (
                  <div className="field">
                    <label>Vector motif</label>
                    <select
                      value={layer.meta.ornament.motif}
                      disabled={!!busy}
                      onChange={(event) => onReshape(layer.id, { motif: event.target.value })}
                    >
                      {(motifs.length ? motifs : [layer.meta.ornament.motif]).map((motif) => (
                        <option key={motif} value={motif}>{motif}</option>
                      ))}
                    </select>
                    <div className="row" style={{ marginTop: 6 }}>
                      <label style={{ flex: 1, fontSize: 11, color: 'var(--muted)' }}>
                        Density — {layer.meta.ornament.density}
                        <input
                          type="range" min={1} max={5} step={1}
                          value={layer.meta.ornament.density}
                          disabled={!!busy}
                          onChange={(event) => onReshape(layer.id, { density: Number(event.target.value) })}
                          style={{ marginTop: 3 }}
                        />
                      </label>
                    </div>
                    <button
                      style={{ marginTop: 6, width: '100%' }}
                      disabled={!!busy || !canReroll}
                      title={canReroll ? undefined : 'This motif is the same at every seed'}
                      onClick={() => onReshape(layer.id, {})}
                    >
                      {busy === `reshape:${layer.id}`
                        ? <><span className="spinner" /> Reshaping…</>
                        : 'Re-roll shape'}
                    </button>
                    <div className="hint" style={{ padding: '8px 0 0' }}>
                      {canReroll
                        ? `seed ${layer.meta.ornament.seed} · procedural, so re-rolling is free`
                        : 'A frame is fully determined by its box — nothing to re-roll.'}
                    </div>
                  </div>
                  )
                })()}
              </>
            )}

            {layer.type === 'image' && (
              <>
                <div className="field">
                  <label>Fit</label>
                  <select
                    value={layer.fit}
                    onChange={(event) => onUpdate(layer.id, (l) => {
                      if (l.type === 'image') l.fit = event.target.value as 'fill' | 'cover' | 'contain'
                    })}
                  >
                    {['cover', 'contain', 'fill'].map((fit) => <option key={fit} value={fit}>{fit}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>AI operations</label>
                  <button
                    style={{ width: '100%', marginBottom: 6 }}
                    disabled={!!busy}
                    onClick={() => onRegenerate(layer.id)}
                  >
                    {busy === `regenerate:${layer.id}` ? <><span className="spinner" /> Regenerating…</> : 'Regenerate (new seed)'}
                  </button>
                  <button
                    style={{ width: '100%' }}
                    disabled={!!busy || !layer.assetId}
                    onClick={() => onRemoveBackground(layer.id)}
                  >
                    {busy === `removebg:${layer.id}` ? <><span className="spinner" /> Cutting out…</> : 'Remove background'}
                  </button>
                </div>
                {layer.meta.generation && (
                  <div className="field">
                    <label>Generation (INV-2)</label>
                    <div className="hint" style={{ padding: 0, wordBreak: 'break-word' }}>
                      <div>model: {layer.meta.generation.model}</div>
                      <div>seed: {layer.meta.generation.seed}</div>
                      <div style={{ marginTop: 4, opacity: 0.8 }}>{layer.meta.generation.prompt}</div>
                    </div>
                  </div>
                )}
              </>
            )}
          </>
        )}

        {layerViolations.length > 0 && (
          <div className="violations">
            {layerViolations.map((violation, index) => (
              <div key={index} className={`violation ${violation.severity}`}>
                <strong>{violation.code}</strong> — {violation.message}
              </div>
            ))}
          </div>
        )}

        <div className="field">
          <label>Export</label>
          <div className="row">
            <select value={exportFormat} onChange={(event) => setExportFormat(event.target.value)}>
              {['png', 'jpeg', 'webp', 'pdf', 'svg'].map((format) => (
                <option key={format} value={format}>{format.toUpperCase()}</option>
              ))}
            </select>
            <select value={exportScale} onChange={(event) => setExportScale(Number(event.target.value))}>
              {[1, 2, 3, 4].map((scale) => <option key={scale} value={scale}>{scale}×</option>)}
            </select>
          </div>
          <button
            className="primary" style={{ width: '100%', marginTop: 6 }}
            disabled={!!busy}
            onClick={() => onExport(exportFormat, exportScale)}
          >
            {busy === 'export' ? <><span className="spinner" /> Exporting…</> : 'Export'}
          </button>
          {exportFormat === 'pdf' && (
            <div className="hint" style={{ padding: '8px 0 0' }}>
              PDF keeps text live and embeds the font — not a rasterised page.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function shadowOf(layer: Layer): Extract<Effect, { kind: 'shadow' }> | undefined {
  const found = layer.effects.find((effect) => effect.kind === 'shadow')
  return found && found.kind === 'shadow' ? found : undefined
}

function NumberInput({ label, value, onChange, step = 1 }: {
  label: string; value: number; onChange: (value: number) => void; step?: number
}) {
  return (
    <label style={{ flex: 1, fontSize: 11, color: 'var(--muted)' }}>
      {label}
      <input
        type="number"
        value={Number.isFinite(value) ? Math.round(value * 100) / 100 : 0}
        step={step}
        onChange={(event) => {
          const parsed = Number(event.target.value)
          if (Number.isFinite(parsed)) onChange(parsed)
        }}
        style={{ marginTop: 3 }}
      />
    </label>
  )
}
