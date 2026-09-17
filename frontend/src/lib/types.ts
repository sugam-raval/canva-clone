/**
 * Document and draw-list types, mirroring backend/app/schema (IMPLEMENTATION_PLAN §0.5,
 * §0.11).
 *
 * These are hand-mirrored rather than generated. The backend emits its JSON Schema from
 * the same Pydantic models, so `npm run gen:types` against /openapi.json is the natural
 * next step if these drift.
 */

export type LayerRole =
  | 'background' | 'subject' | 'object' | 'decoration'
  | 'headline' | 'subhead' | 'body' | 'cta' | 'caption'
  | 'offer' | 'price' | 'terms' | 'feature' | 'event' | 'contact'
  | 'logo' | 'badge' | 'overlay' | 'unknown'

export type BlendMode =
  | 'normal' | 'multiply' | 'screen' | 'overlay' | 'soft-light'
  | 'darken' | 'lighten' | 'color-dodge' | 'difference'

export interface Frame {
  x: number; y: number; w: number; h: number
  rotation: number; flipX?: boolean; flipY?: boolean
}

export interface Constraints {
  horizontal: 'left' | 'right' | 'center' | 'scale' | 'stretch'
  vertical: 'top' | 'bottom' | 'middle' | 'scale' | 'stretch'
  lockAspect: boolean
  optional?: boolean
  priority: number
}

export interface GenerationParams {
  adapter: string; model: string; prompt: string
  negativePrompt?: string; seed: number
  params: Record<string, unknown>; producedAt?: string
}

/** How a vector motif was built — the ornament counterpart to GenerationParams. */
export interface OrnamentParams {
  motif: string; seed: number; density: number
}

export interface LayerMeta {
  generation?: GenerationParams
  ornament?: OrnamentParams
  notes?: Record<string, unknown>
}

export interface Stroke {
  color: string; width: number; dash?: number[] | null
}

export type Effect =
  | { kind: 'shadow'; dx: number; dy: number; blur: number; color: string; opacity: number }
  | { kind: 'blur'; radius: number }
  | { kind: 'stroke'; color: string; width: number }
  | { kind: 'glow'; color: string; radius: number; opacity: number }

export interface BaseLayer {
  id: string; name: string; role: LayerRole
  frame: Frame; opacity: number; blendMode: BlendMode
  visible: boolean; locked: boolean
  effects: Effect[]; constraints: Constraints; meta: LayerMeta
}

export interface ImageLayer extends BaseLayer {
  type: 'image'
  assetId: string; hasAlpha: boolean
  naturalSize: { w: number; h: number }
  fit: 'fill' | 'cover' | 'contain'
  adjust?: Record<string, number>
  placeholderColor?: string
  mask?: MaskShape | null
  maskRadius?: number
}

export interface TextLayer extends BaseLayer {
  type: 'text'
  content: string; fontFamily: string; fontWeight: number
  fontStyle: 'normal' | 'italic'; fontSize: number
  lineHeight: number; letterSpacing: number
  align: 'left' | 'center' | 'right'
  verticalAlign: 'top' | 'middle' | 'bottom'
  color: string
  textTransform: 'none' | 'uppercase' | 'capitalize'
  autoFit?: { min: number; max: number; mode: string }
  autoHeight?: boolean
  backdrop?: { color: string; opacity: number; padding: number; radius: number }
  stroke?: Stroke | null
}

export type MaskShape =
  | 'rounded' | 'circle' | 'ellipse' | 'diamond' | 'arch' | 'arch-down'
  | 'hexagon' | 'leaf' | 'squircle' | 'pill'

export interface ShapeLayer extends BaseLayer {
  type: 'shape'
  shape: 'rect' | 'ellipse' | 'line' | 'polygon' | 'path'
  fill?: string | null; radius: number
  stroke?: Stroke | null
  pathData?: string | null
  points?: number[] | null
  gradient?: { angle: number; stops: { offset: number; color: string; opacity: number }[] } | null
}

export interface GroupLayer extends BaseLayer { type: 'group'; children: Layer[] }
export interface SvgLayer extends BaseLayer { type: 'svg'; assetId: string }

export type Layer = ImageLayer | TextLayer | ShapeLayer | GroupLayer | SvgLayer

export interface Canvas {
  width: number; height: number; background: string
  safeMargin: number; dpi: number
}

export interface DesignDoc {
  id: string; schemaVersion: 3; title: string
  canvas: Canvas; layers: Layer[]
  palette: string[]
  fonts: { family: string; weights: number[]; source: string }[]
  provenance: Record<string, unknown>
  createdAt: string; updatedAt: string
}

/* ---- draw list (§0.11) --------------------------------------------------------- */

export interface Matrix2D { a: number; b: number; c: number; d: number; e: number; f: number }
export interface DrawRect { x: number; y: number; w: number; h: number }

export interface PositionedGlyph { gid: number; cluster: number; x: number; y: number; text: string }

export interface PositionedGlyphRun {
  fontFamily: string; fontWeight: number; fontStyle: 'normal' | 'italic'
  fontSize: number; fontKey: string
  glyphs: PositionedGlyph[]
  originX: number; originY: number; advance: number
  direction: 'ltr' | 'rtl'
}

export type DrawCommand =
  | { op: 'clear'; color: string }
  | {
      op: 'saveTransform'; layerId: string; layerType: string; role: string
      locked: boolean; name: string; matrix: Matrix2D; opacity: number
      blend: BlendMode; clip?: DrawRect | null; size?: DrawRect | null
      effects: Record<string, unknown>[]
    }
  | { op: 'restore' }
  | {
      op: 'image'; assetUrl: string; assetId: string; dest: DrawRect
      crop?: DrawRect | null; opacity: number; blend: BlendMode
      adjust?: Record<string, number> | null; radius: number
      clipPath?: string | null
    }
  | {
      op: 'textRun'; runs: PositionedGlyphRun[]; color: string
      strokeColor?: string | null; strokeWidth: number; layerId: string
    }
  | {
      op: 'path'; d: string; fill?: string | null; stroke?: string | null
      strokeWidth: number; dash?: number[] | null
      cap?: 'butt' | 'round' | 'square'; join?: 'miter' | 'round' | 'bevel'
      gradient?: { angle: number; stops: { offset: number; color: string; opacity: number }[] } | null
    }
  | {
      op: 'placeholder'; dest: DrawRect; color: string; layerId: string
      radius: number; clipPath?: string | null
    }

export interface DrawList {
  width: number; height: number; scale: number; commands: DrawCommand[]
}

/* ---- progress events (§0.9) ---------------------------------------------------- */

export type ProgressEvent =
  | { t: 'request.started'; requestId: string; plan: string[] }
  | { t: 'brief.ready'; brief: Record<string, unknown> }
  | { t: 'doc.skeleton'; doc: DesignDoc }
  | { t: 'job.started'; jobId: string; type: string; layerId?: string }
  | { t: 'layer.patch'; layerId: string; patch: Record<string, unknown> }
  | { t: 'job.failed'; jobId: string; type: string; recoverable: boolean; reason: string }
  | { t: 'doc.solved'; doc: DesignDoc; violations: Violation[] }
  | { t: 'request.done'; docId: string; costCents: number; tier: string; summary: string }
  | { t: 'request.failed'; reason: string }
  | { t: 'request.clarify'; requestId: string; question: string; options: string[] }
  | { t: 'ping' }

export interface Violation {
  code: string; message: string; layerId: string | null
  severity: 'error' | 'warning'
}

export interface DocSummary {
  id: string; title: string; updatedAt: string | null
  provenance: Record<string, unknown>; thumbUrl: string | null
}
