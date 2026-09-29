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
  /** A: places every line and detail; B: keeps the must-keeps (headline, offer, price,
   * contact); C: the rest (docs/slot_fit_match_plan.md). */
  tier: 'A' | 'B' | 'C'
  coverage: number
  placedLines: string[]
  droppedLines: string[]
}

/** How the automatic match picked the template. `holds_all`: the pick places every line
 * and detail the user gave. */
export interface LidoMatchInfo {
  path: 'holds_all' | 'best_match'
  tier: 'A' | 'B' | 'C'
  topicLine: string
  requestDetails: string[]
  requestedLines: string[]
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
  /** Lines the user asked for that had no room in the template. */
  droppedLines: string[]
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
