/**
 * Renders a server-produced draw list with Konva — IMPLEMENTATION_PLAN §0.11.
 *
 * Per ADR 0001 the browser computes no geometry and no glyph positions of its own: it
 * replays the command list the server generated. That is what makes the canvas and the
 * exported file agree (INV-3) — there is one implementation, not two kept in step.
 *
 * Text is drawn by a custom `sceneFunc` that places each shaped glyph at the exact
 * offset HarfBuzz produced, rather than handing a string to the browser's own shaper.
 *
 * Interaction is deliberately separated from painting: the artwork layer is inert, and
 * a single proxy rectangle on an overlay layer carries the selection and the transform
 * handles. Dragging therefore never repaints the artwork (§3.2), and transform maths
 * stays in one place instead of being threaded through nested groups.
 */

import Konva from 'konva'
import { useEffect, useMemo, useRef } from 'react'
import { Group, Image as KonvaImage, Layer, Path, Rect, Shape, Stage, Transformer } from 'react-konva'

import type { DrawCommand, DrawList } from '../lib/types'
import { canvasFamily } from './fonts'
import { decompose } from './matrix'
import { useImage } from './useImage'

export interface SelectableLayer {
  layerId: string
  layerType: string
  name: string
  locked: boolean
  /** World-space box in draw-list pixels. */
  x: number; y: number; width: number; height: number; rotation: number
}

interface LayerNode {
  kind: 'layer'
  layerId: string
  layerType: string
  name: string
  locked: boolean
  transform: ReturnType<typeof decompose>
  opacity: number
  blend: string
  clip: { x: number; y: number; w: number; h: number } | null
  size: { x: number; y: number; w: number; h: number } | null
  effects: Record<string, unknown>[]
  children: Node[]
}
type PaintNode = { kind: 'paint'; command: DrawCommand }
type Node = LayerNode | PaintNode

interface Tree {
  background: string
  nodes: Node[]
  selectable: SelectableLayer[]
}

/** Rebuilds the flat command list into the layer tree it encodes. */
function buildTree(commands: DrawCommand[]): Tree {
  let background = '#FFFFFF'
  const root: Node[] = []
  const stack: Node[][] = [root]
  const selectable: SelectableLayer[] = []

  for (const command of commands) {
    const current = stack[stack.length - 1]
    if (command.op === 'clear') {
      background = command.color
    } else if (command.op === 'saveTransform') {
      const transform = decompose(command.matrix)
      const node: LayerNode = {
        kind: 'layer',
        layerId: command.layerId,
        layerType: command.layerType,
        name: command.name,
        locked: command.locked,
        transform,
        opacity: command.opacity,
        blend: command.blend,
        clip: command.clip ?? null,
        size: command.size ?? null,
        effects: command.effects ?? [],
        children: [],
      }
      current.push(node)
      stack.push(node.children)
      if (command.size) {
        selectable.push({
          layerId: command.layerId,
          layerType: command.layerType,
          name: command.name,
          locked: command.locked,
          x: transform.x,
          y: transform.y,
          width: command.size.w * transform.scaleX,
          height: command.size.h * transform.scaleY,
          rotation: transform.rotation,
        })
      }
    } else if (command.op === 'restore') {
      if (stack.length > 1) stack.pop()
    } else {
      current.push({ kind: 'paint', command })
    }
  }
  return { background, nodes: root, selectable }
}

const BLEND_MODES: Record<string, GlobalCompositeOperation> = {
  normal: 'source-over',
  multiply: 'multiply',
  screen: 'screen',
  overlay: 'overlay',
  'soft-light': 'soft-light',
  darken: 'darken',
  lighten: 'lighten',
  'color-dodge': 'color-dodge',
  difference: 'difference',
}

function ImageCommand({ command }: { command: Extract<DrawCommand, { op: 'image' }> }) {
  const image = useImage(command.assetUrl)
  if (!image) return null
  const crop = command.crop
    ? { x: command.crop.x, y: command.crop.y, width: command.crop.w, height: command.crop.h }
    : undefined

  // A masked image is drawn by hand rather than through KonvaImage: Konva's own
  // `clipFunc` clips to the context's current path, which a Path2D never becomes, so
  // the silhouette the server computed has to be applied to the 2D context directly.
  if (command.clipPath) {
    return (
      <Shape
        listening={false}
        sceneFunc={(context) => {
          const ctx = context._context
          ctx.save()
          ctx.beginPath()
          ctx.clip(new Path2D(command.clipPath!))
          ctx.globalAlpha = command.opacity
          const c = crop
          if (c) {
            ctx.drawImage(image, c.x, c.y, c.width, c.height,
              command.dest.x, command.dest.y, command.dest.w, command.dest.h)
          } else {
            ctx.drawImage(image, command.dest.x, command.dest.y,
              command.dest.w, command.dest.h)
          }
          ctx.restore()
        }}
      />
    )
  }

  return (
    <KonvaImage
      image={image}
      x={command.dest.x}
      y={command.dest.y}
      width={command.dest.w}
      height={command.dest.h}
      crop={crop}
      opacity={command.opacity}
      cornerRadius={command.radius || undefined}
      listening={false}
    />
  )
}

/** Draws one text layer's shaped runs at their exact server-computed positions. */
function TextRunCommand({ command }: { command: Extract<DrawCommand, { op: 'textRun' }> }) {
  return (
    <Shape
      listening={false}
      sceneFunc={(context) => {
        const ctx = context._context
        ctx.save()
        ctx.fillStyle = command.color
        ctx.textBaseline = 'alphabetic'
        ctx.textAlign = 'left'
        if (command.strokeColor && command.strokeWidth > 0) {
          ctx.strokeStyle = command.strokeColor
          ctx.lineWidth = command.strokeWidth
          ctx.lineJoin = 'round'
        }
        for (const run of command.runs) {
          const style = run.fontStyle === 'italic' ? 'italic ' : ''
          ctx.font = `${style}${run.fontWeight} ${run.fontSize}px "${canvasFamily(run.fontKey)}", sans-serif`
          for (const glyph of run.glyphs) {
            if (!glyph.text) continue
            const x = run.originX + glyph.x
            const y = run.originY + glyph.y
            if (command.strokeColor && command.strokeWidth > 0) ctx.strokeText(glyph.text, x, y)
            ctx.fillText(glyph.text, x, y)
          }
        }
        ctx.restore()
      }}
    />
  )
}

function withAlpha(hex: string, opacity: number): string {
  const value = hex.replace('#', '')
  const r = parseInt(value.slice(0, 2), 16)
  const g = parseInt(value.slice(2, 4), 16)
  const b = parseInt(value.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${opacity})`
}

function PathCommand({ command }: { command: Extract<DrawCommand, { op: 'path' }> }) {
  const ref = useRef<Konva.Path>(null)
  const gradient = command.gradient

  useEffect(() => {
    const node = ref.current
    if (!node || !gradient) return
    // Resolve the gradient against the path's own bounds, matching the Skia backend so
    // the two renderers produce the same ramp.
    const box = node.getSelfRect()
    const angle = ((gradient.angle ?? 90) - 90) * (Math.PI / 180)
    const cx = box.x + box.width / 2
    const cy = box.y + box.height / 2
    // Span the box along the gradient's OWN direction. Sizing by max(width, height)
    // leaves a wide, short shape covering only the middle slice of the ramp, which
    // renders as a flat band with two hard edges instead of a fade.
    const ux = Math.cos(angle)
    const uy = Math.sin(angle)
    const half = (box.width * Math.abs(ux) + box.height * Math.abs(uy)) / 2
    node.fillLinearGradientStartPoint({ x: cx - ux * half, y: cy - uy * half })
    node.fillLinearGradientEndPoint({ x: cx + ux * half, y: cy + uy * half })
    node.fillLinearGradientColorStops(
      gradient.stops.flatMap((stop) => [stop.offset, withAlpha(stop.color, stop.opacity)]),
    )
    node.getLayer()?.batchDraw()
  }, [gradient, command.d])

  return (
    <Path
      ref={ref}
      data={command.d}
      fill={gradient ? undefined : command.fill ?? undefined}
      stroke={command.stroke ?? undefined}
      strokeWidth={command.strokeWidth || undefined}
      dash={command.dash ?? undefined}
      lineCap={command.cap ?? undefined}
      lineJoin={command.join ?? undefined}
      listening={false}
    />
  )
}

function PlaceholderCommand({ command }: { command: Extract<DrawCommand, { op: 'placeholder' }> }) {
  // Cut to the same silhouette the finished image will use, so the layer does not change
  // shape when its asset lands mid-render.
  if (command.clipPath) {
    return (
      <Shape
        listening={false}
        fill={command.color}
        opacity={0.9}
        sceneFunc={(context, shape) => {
          const ctx = context._context
          ctx.save()
          ctx.beginPath()
          ctx.clip(new Path2D(command.clipPath!))
          context.fillStyle = shape.fill() as string
          ctx.fillRect(command.dest.x, command.dest.y, command.dest.w, command.dest.h)
          ctx.restore()
        }}
      />
    )
  }
  return (
    <Rect
      x={command.dest.x}
      y={command.dest.y}
      width={command.dest.w}
      height={command.dest.h}
      fill={command.color}
      cornerRadius={command.radius || undefined}
      opacity={0.9}
      listening={false}
    />
  )
}

function shadowProps(effects: Record<string, unknown>[]) {
  const shadow = effects.find((effect) => effect.kind === 'shadow')
  if (!shadow) return {}
  return {
    shadowColor: (shadow.color as string) ?? '#000000',
    shadowBlur: (shadow.blur as number) ?? 0,
    shadowOffsetX: (shadow.dx as number) ?? 0,
    shadowOffsetY: (shadow.dy as number) ?? 0,
    shadowOpacity: (shadow.opacity as number) ?? 0.3,
  }
}

function renderNodes(nodes: Node[], keyPrefix = ''): React.ReactNode {
  return nodes.map((node, index) => {
    const key = `${keyPrefix}${index}`
    if (node.kind === 'paint') {
      const command = node.command
      if (command.op === 'image') return <ImageCommand key={key} command={command} />
      if (command.op === 'textRun') return <TextRunCommand key={key} command={command} />
      if (command.op === 'path') return <PathCommand key={key} command={command} />
      if (command.op === 'placeholder') return <PlaceholderCommand key={key} command={command} />
      return null
    }
    const { transform } = node
    return (
      <Group
        key={`${key}-${node.layerId}`}
        x={transform.x}
        y={transform.y}
        rotation={transform.rotation}
        scaleX={transform.scaleX}
        scaleY={transform.scaleY}
        skewX={transform.skewX}
        opacity={node.opacity}
        globalCompositeOperation={BLEND_MODES[node.blend] ?? 'source-over'}
        clipFunc={node.clip ? (ctx) => ctx.rect(node.clip!.x, node.clip!.y, node.clip!.w, node.clip!.h) : undefined}
        listening={false}
        {...shadowProps(node.effects)}
      >
        {renderNodes(node.children, `${key}-`)}
      </Group>
    )
  })
}

export interface TransformResult {
  x: number; y: number; width: number; height: number; rotation: number
}

export interface DrawListStageProps {
  drawList: DrawList
  selectedLayerId: string | null
  onSelect: (layerId: string | null) => void
  onTransformEnd?: (layerId: string, box: TransformResult) => void
  onDoubleClick?: (layerId: string) => void
  showSafeMargin?: number
}

export function DrawListStage({
  drawList, selectedLayerId, onSelect, onTransformEnd, onDoubleClick, showSafeMargin,
}: DrawListStageProps) {
  const tree = useMemo(() => buildTree(drawList.commands), [drawList])
  const transformerRef = useRef<Konva.Transformer>(null)
  const proxyRef = useRef<Konva.Rect>(null)

  const selected = tree.selectable.find((layer) => layer.layerId === selectedLayerId) ?? null

  useEffect(() => {
    const transformer = transformerRef.current
    const proxy = proxyRef.current
    if (!transformer) return
    if (selected && proxy) {
      proxy.setAttrs({
        x: selected.x, y: selected.y,
        width: selected.width, height: selected.height,
        rotation: selected.rotation, scaleX: 1, scaleY: 1,
      })
      transformer.nodes([proxy])
    } else {
      transformer.nodes([])
    }
    transformer.getLayer()?.batchDraw()
  }, [selected, drawList])

  const emit = () => {
    const proxy = proxyRef.current
    if (!proxy || !selectedLayerId || !onTransformEnd) return
    onTransformEnd(selectedLayerId, {
      x: proxy.x(),
      y: proxy.y(),
      width: Math.max(1, proxy.width() * proxy.scaleX()),
      height: Math.max(1, proxy.height() * proxy.scaleY()),
      rotation: proxy.rotation(),
    })
    proxy.scaleX(1)
    proxy.scaleY(1)
  }

  // Topmost-first, so a click selects what the user sees rather than what is beneath it.
  const hitOrder = [...tree.selectable].reverse()

  return (
    <Stage
      width={drawList.width}
      height={drawList.height}
      style={{ background: tree.background, display: 'block' }}
      onMouseDown={(event) => { if (event.target === event.target.getStage()) onSelect(null) }}
    >
      <Layer listening={false}>
        <Rect x={0} y={0} width={drawList.width} height={drawList.height} fill={tree.background} />
        {renderNodes(tree.nodes)}
      </Layer>

      <Layer>
        {showSafeMargin && showSafeMargin > 0 ? (
          <Rect
            x={showSafeMargin * drawList.scale}
            y={showSafeMargin * drawList.scale}
            width={drawList.width - showSafeMargin * drawList.scale * 2}
            height={drawList.height - showSafeMargin * drawList.scale * 2}
            stroke="#38bdf8"
            strokeWidth={1}
            dash={[6, 6]}
            opacity={0.5}
            listening={false}
          />
        ) : null}

        {/* Invisible hit areas — one per layer, topmost first. */}
        {hitOrder.map((layer) => (
          <Rect
            key={`hit-${layer.layerId}`}
            x={layer.x}
            y={layer.y}
            width={layer.width}
            height={layer.height}
            rotation={layer.rotation}
            fill="transparent"
            listening={!layer.locked}
            onMouseDown={(event) => { event.cancelBubble = true; onSelect(layer.layerId) }}
            onTap={(event) => { event.cancelBubble = true; onSelect(layer.layerId) }}
            onDblClick={(event) => { event.cancelBubble = true; onDoubleClick?.(layer.layerId) }}
          />
        ))}

        <Rect ref={proxyRef} fill="transparent" draggable onDragEnd={emit} onTransformEnd={emit} />
        <Transformer
          ref={transformerRef}
          rotateEnabled
          keepRatio={false}
          anchorSize={8}
          borderStroke="#38bdf8"
          anchorStroke="#38bdf8"
          anchorFill="#0f172a"
          boundBoxFunc={(_oldBox, newBox) => ({
            ...newBox,
            width: Math.max(8, newBox.width),
            height: Math.max(8, newBox.height),
          })}
        />
      </Layer>
    </Stage>
  )
}
