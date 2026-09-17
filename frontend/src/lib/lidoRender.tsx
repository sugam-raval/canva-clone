/**
 * Throwaway SVG renderer for Lido layers — the TS port of `app/lido_corpus/preview.py`.
 *
 * Same caveats as the Python version: no real text wrapping, approximate clip-path
 * positioning, `scale` on text layers is ignored. Good enough to sanity-check a
 * generated design's layout/copy without a real Lido.js install.
 */

import type { LidoLayer } from './lidoTypes'

const OCTAGON_PTS = '150,0 350,0 500,150 500,350 350,500 150,500 0,350 0,150'

function textAnchor(align?: string): 'middle' | 'end' | 'start' {
  if (align === 'center') return 'middle'
  if (align === 'right') return 'end'
  return 'start'
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

  return (
    <g transform={`translate(${pos.x},${pos.y})`}>
      <text x={0} y={firstSize}>
        {paragraphs.map((p, i) => {
          const fontSize = parseFloat(String(p.attrs.fontSize ?? '16').replace('px', '')) || 16
          const lineHeight = parseFloat(p.attrs.lineHeight ?? '1.2') || 1.2
          return (
            <tspan
              key={i}
              x={0}
              dy={`${i === 0 ? 0 : lineHeight}em`}
              fontSize={fontSize}
              fill={p.attrs.color ?? 'black'}
              fontFamily={(p.attrs.fontFamily ?? 'sans-serif').split(',')[0]}
              textAnchor={textAnchor(p.attrs.textAlign)}
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
  const clipD = layer.props.clipPath ?? 'M 0 0 L 500 0 L 500 500 L 0 500 Z'
  const image = layer.props.image ?? {}
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

  if (shape === 'circle') {
    return <ellipse cx={x + w / 2} cy={y + h / 2} rx={w / 2} ry={h / 2} fill={color} />
  }
  if (shape === 'octagon') {
    return (
      <g transform={`translate(${x},${y}) scale(${w / 500},${h / 500})`}>
        <polygon points={OCTAGON_PTS} fill={color} />
      </g>
    )
  }
  return <rect x={x} y={y} width={w} height={h} fill={color} />
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
