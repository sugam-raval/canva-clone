/**
 * Throwaway SVG renderer for Lido layers — the TS port of `app/lido_corpus/preview.py`.
 *
 * Same caveats as the Python version: no real text wrapping, approximate clip-path
 * positioning, `scale` on text layers is ignored. Good enough to sanity-check a
 * generated design's layout/copy without a real Lido.js install.
 */

import { useEffect, useState } from 'react'
import type { LidoLayer } from './lidoTypes'

const OCTAGON_PTS = '150,0 350,0 500,150 500,350 350,500 150,500 0,350 0,150'

/** Families already handed to the browser, so switching between previews doesn't
 * refetch a face the document is holding anyway. */
const loadedFamilies = new Set<string>()

type FontDescriptor = { name?: string; fonts?: { urls?: string[] }[] }

/** Every `props.fonts` descriptor in the document, as {family, url}. */
function collectFonts(layers: Record<string, LidoLayer>): { family: string; url: string }[] {
  const found = new Map<string, string>()
  for (const layer of Object.values(layers)) {
    const descriptors = (layer?.props?.fonts ?? []) as FontDescriptor[]
    for (const descriptor of descriptors) {
      const url = descriptor.fonts?.[0]?.urls?.[0]
      if (descriptor.name && url && !found.has(descriptor.name)) {
        found.set(descriptor.name, url)
      }
    }
  }
  return [...found].map(([family, url]) => ({ family, url }))
}

/**
 * Actually load the faces the document names.
 *
 * `props.fonts` carries a real gstatic URL per family, and the renderer was setting
 * `fontFamily` from it without ever fetching anything — so a poster set in Anton over
 * Barlow Condensed rendered entirely in the browser's default serif, and every
 * generated design looked identical regardless of the vibe chosen for it. Typography is
 * most of what separates these pages from a slide, and none of it was reaching the
 * screen.
 *
 * Returns a counter that changes as faces arrive, to repaint text first laid out
 * against the fallback metrics.
 */
function useWebFonts(layers: Record<string, LidoLayer>): number {
  const faces = collectFonts(layers)
  const key = faces.map((f) => f.family).sort().join('|')
  const [ready, setReady] = useState(0)

  useEffect(() => {
    if (typeof document === 'undefined' || !('fonts' in document)) return
    let cancelled = false
    const pending = collectFonts(layers).filter((f) => !loadedFamilies.has(f.family))
    if (pending.length === 0) return
    // allSettled, not all: a face that fails to load is not worth failing a preview
    // over — that line renders in the fallback exactly as it did before, and every
    // other line still improves.
    void Promise.allSettled(
      pending.map(async ({ family, url }) => {
        const face = new FontFace(family, `url(${url})`)
        await face.load()
        document.fonts.add(face)
        loadedFamilies.add(family)
      }),
    ).then(() => {
      if (!cancelled) setReady((n) => n + 1)
    })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return ready
}

function textAnchor(align?: string): 'middle' | 'end' | 'start' {
  if (align === 'center') return 'middle'
  if (align === 'right' || align === 'end') return 'end'
  return 'start'
}

/** Lido positions a text layer by its top-left and aligns inside `boxSize.width`, but
 * SVG aligns around an anchor point. Offsetting the anchor by the box width is what
 * makes a centred or right-aligned block land where the editor puts it instead of
 * hanging off the layer's left edge. */
function anchorOffset(align: string | undefined, boxWidth: number): number {
  if (align === 'center') return boxWidth / 2
  if (align === 'right' || align === 'end') return boxWidth
  return 0
}

function applyTransform(text: string, transform?: string | null): string {
  if (transform === 'uppercase') return text.toUpperCase()
  if (transform === 'capitalize') {
    return text.replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
  }
  return text
}

function RenderText({ layer }: { layer: LidoLayer }) {
  const pos = layer.props.position ?? { x: 0, y: 0 }
  const doc = layer.props.doc ?? { content: [] }
  const paragraphs: { attrs: Record<string, any>; text: string }[] = (doc.content ?? [])
    .map((para: any) => {
      const attrs = para.attrs ?? {}
      const text = (para.content ?? [])
        .map((n: any) => applyTransform(n.text ?? '', attrs.textTransform))
        .join('')
      return { attrs, text }
    })
    .filter((p: { text: string }) => p.text.length > 0)

  if (paragraphs.length === 0) return null
  const firstSize = parseFloat(String(paragraphs[0].attrs.fontSize ?? '16').replace('px', '')) || 16
  const boxWidth = layer.props.boxSize?.width ?? 0

  return (
    <g transform={`translate(${pos.x},${pos.y})`}>
      <text y={firstSize}>
        {paragraphs.map((p, i) => {
          const fontSize = parseFloat(String(p.attrs.fontSize ?? '16').replace('px', '')) || 16
          const lineHeight = parseFloat(p.attrs.lineHeight ?? '1.2') || 1.2
          return (
            <tspan
              key={i}
              x={anchorOffset(p.attrs.textAlign, boxWidth)}
              dy={`${i === 0 ? 0 : lineHeight}em`}
              fontSize={fontSize}
              fill={p.attrs.color ?? 'black'}
              fontFamily={`${(p.attrs.fontFamily ?? 'sans-serif').split(',')[0]}, sans-serif`}
              textAnchor={textAnchor(p.attrs.textAlign)}
              letterSpacing={p.attrs.letterSpacing ?? undefined}
            >
              {p.text}
            </tspan>
          )
        })}
      </text>
    </g>
  )
}

function RenderFrame({ id, layer }: { id: string; layer: LidoLayer }) {
  const box = layer.props.boxSize ?? {}
  const x = box.x ?? layer.props.position?.x ?? 0
  const y = box.y ?? layer.props.position?.y ?? 0
  const w = box.width ?? 100
  const h = box.height ?? 100
  const image = layer.props.image ?? {}

  // A contain-fit frame (a transparent cutout, or a logo lockup) has no crop shape to
  // honour, so it skips the 500-unit clip-path scaling trick entirely and draws
  // straight into the layer's real box — the only way to keep its aspect ratio
  // correct when that box isn't square.
  if (layer.props.imageStyle?.objectFit === 'contain') {
    return (
      <image
        href={image.url ?? ''}
        x={x} y={y} width={w} height={h}
        preserveAspectRatio="xMidYMid meet"
      />
    )
  }

  const clipD = layer.props.clipPath ?? 'M 0 0 L 500 0 L 500 500 L 0 500 Z'
  const imgPos = image.position ?? { x: 0, y: 0 }
  const imgScale = layer.props.scale ?? 1
  const clipId = `clip-${id}`

  return (
    <>
      <clipPath id={clipId}>
        <path d={clipD} />
      </clipPath>
      <g transform={`translate(${x},${y}) scale(${w / 500},${h / 500})`}>
        <image
          href={image.url ?? ''}
          width={500}
          height={500}
          clipPath={`url(#${clipId})`}
          transform={`translate(${imgPos.x ?? 0},${imgPos.y ?? 0}) scale(${imgScale})`}
          preserveAspectRatio="xMidYMid slice"
        />
      </g>
    </>
  )
}

function RenderShape({ layer }: { layer: LidoLayer }) {
  const box = layer.props.boxSize ?? {}
  const x = box.x ?? 0
  const y = box.y ?? 0
  const w = box.width ?? 100
  const h = box.height ?? 100
  const color = layer.props.color ?? 'black'
  const shape = layer.props.shape ?? 'rect'
  const opacity = layer.props.transparency ?? 1

  if (shape === 'circle') {
    return (
      <ellipse cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} fill={color} fillOpacity={opacity} />
    )
  }
  if (shape === 'octagon') {
    return (
      <g transform={`translate(${x},${y}) scale(${w / 500},${h / 500})`}>
        <polygon points={OCTAGON_PTS} fill={color} fillOpacity={opacity} />
      </g>
    )
  }
  return <rect x={x} y={y} width={w} height={h} fill={color} fillOpacity={opacity} />
}

function RenderLayer({ id, layer }: { id: string; layer: LidoLayer }) {
  const resolved = layer.type?.resolvedName
  try {
    if (resolved === 'TextLayer') return <RenderText layer={layer} />
    if (resolved === 'FrameLayer') return <RenderFrame id={id} layer={layer} />
    if (resolved === 'ShapeLayer') return <RenderShape layer={layer} />
  } catch {
    return null
  }
  return null
}

export function LidoPreview({ layers }: { layers: Record<string, LidoLayer> }) {
  // Ahead of the early return: hooks cannot run conditionally, and a document missing
  // its ROOT still names faces worth loading.
  const fontsReady = useWebFonts(layers)
  const root = layers.ROOT
  if (!root) return <div className="lido-preview-error">no ROOT layer</div>
  const box = root.props.boxSize ?? { width: 675, height: 675 }
  const w = box.width ?? 675
  const h = box.height ?? 675
  const bgColor = root.props.color ?? 'white'
  const bgImage = root.props.image?.url

  const order: string[] = root.child ?? []

  return (
    <svg
      key={fontsReady}
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      style={{ background: bgColor, boxShadow: '0 4px 24px rgba(0,0,0,.35)', maxWidth: '100%', height: 'auto' }}
    >
      {bgImage && (
        <image href={bgImage} x={0} y={0} width={w} height={h} preserveAspectRatio="xMidYMid slice" />
      )}
      {order.map((id) => {
        const layer = layers[id]
        return layer ? <RenderLayer key={id} id={id} layer={layer} /> : null
      })}
    </svg>
  )
}
