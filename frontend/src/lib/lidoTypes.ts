/** Types for `/v1/lido/generate` — mirrors `app.lido_corpus` on the backend. */

export interface LidoLayerType {
  type?: string | null
  resolvedName: string
  fixedText?: string | null
  replacableText?: string | null
}

export interface LidoLayer {
  type: LidoLayerType
  child: string[]
  props: Record<string, any>
  locked: boolean
  parent: string | null
}

export interface LidoDocumentEntry {
  layers: Record<string, LidoLayer>
}

export interface LidoSlotFillInfo {
  layerId: string
  role: string
  text: string
}

export interface LidoAssetInfo {
  layerId: string
  url: string
}

export interface LidoGenerateResponse {
  document: LidoDocumentEntry[]
  templateId: string
  templateScore: number
  textFills: LidoSlotFillInfo[]
  imageFills: LidoAssetInfo[]
}

/** `/v1/lido/scratch` — a design composed from the brief, with no template involved. */

export interface LidoScratchElement {
  kind: string
  role: string | null
  text: string | null
  size: string
  x: number
  y: number
  w: number
  color: string | null
  imagePrompt: string | null
  cutout: boolean
  behind: boolean
  font: string
  tracking: string | null
}

export interface LidoScratchResponse {
  designId: string
  document: LidoDocumentEntry[]
  name: string
  kind: string
  width: number
  height: number
  vibe: string
  layoutStyle: string
  /** The graphic treatment chosen for the ground — see `lido_scratch/background.py`. */
  backgroundStyle: string
  /** The ornament the page wears, after the archetype's defaults were filled in. */
  decor: string[]
  palette: string[]
  elements: LidoScratchElement[]
  llmDesigned: boolean
  fontScale: number
  backgroundUrl: string | null
  path: string
}

export interface LidoScratchSummary {
  id: string
  name: string
  kind: string
  aspect: string
  description: string
  prompt: string
  generatedAt: string
  canvasSize: Record<string, number>
}
