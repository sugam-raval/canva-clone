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

export interface LidoImagePromptInfo {
  layerId: string
  prompt: string
}

/** One candidate from the automatic template match (see docs/new_match_plan.md). */
export interface LidoMatchCandidate {
  templateId: string
  score: number
  topic: number
  details: number
  held: string[]
  missing: string[]
  emptyContactSlots: string[]
}

/** How the automatic match picked the template. `holds_all`: at least one template had
 * a slot for every detail the user gave, and the pick came from those. */
export interface LidoMatchInfo {
  path: 'holds_all' | 'best_match'
  topicLine: string
  requestDetails: string[]
  usedLlm: boolean
  embedder: string
  candidates: LidoMatchCandidate[]
}

export interface LidoGenerateResponse {
  document: LidoDocumentEntry[]
  templateId: string
  templateScore: number
  designId: string
  textFills: LidoSlotFillInfo[]
  imageFills: LidoAssetInfo[]
  imagePrompts: LidoImagePromptInfo[]
  imageFailures: string[]
  /** null for an explicit or random template pick. */
  match?: LidoMatchInfo | null
}

/** `/v1/lido/templates` — one entry per template in the corpus, for a template picker. */
export interface LidoTemplateSummary {
  id: string
  name: string
  kind: string
  aspect: string
  tags: string[]
  description: string
  /** Whether the auto-scored default (no explicit templateId/randomTemplate) would
   * ever pick this one — see meta.reference_note on the backend. */
  ready: boolean
}

/** `/v1/lido/generations` — the DB-backed gallery index for both flows. */
export interface LidoGenerationSummary {
  id: string
  templateId: string | null
  name: string
  kind: string
  aspect: string
  prompt: string
  canvasSize: Record<string, number>
  thumbnailUrl: string | null
  /** Legacy: only set on a design promoted in from the old file-based storage. */
  path: string | null
  createdAt: string
}
