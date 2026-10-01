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

/** docs/palette_theme.md — template colour → palette colour, per-layer text colours,
 * and text layers whose colour was swapped to stay readable on the generated image. */
export interface LidoTheme {
  palette: string[]
  colorMap: Record<string, string>
  textColors: Record<string, Record<string, string>>
  contrastFixed: string[]
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
  /** How the colour palette was applied; null when none was chosen. */
  theme?: LidoTheme | null
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

/** `/v1/lido/drafts` — a brand-new template designed from a prompt (or by the CLI),
 * waiting for review in lidojs_templates/drafts/. */
export interface LidoDraftInfo {
  id: string
  createdAt: string
  /** "brief" (from a prompt in this UI), "ai" / "recipe" (the CLI), "manual". */
  source: string
  prompt?: string | null
  name?: string | null
  idea?: string | null
  direction?: string | null
  layout?: string | null
  theme?: string | null
  palette?: string | null
  fonts?: string | null
  mirrored?: boolean
  colors: Record<string, string>
  /** Feature families this design was asked to use (gradient, frame, draw, line…). */
  features?: string[]
  /** The art director's plan (step 1): photos, texts, moods, layout, exclusions. */
  plan?: {
    layout: string
    custom_layout?: string | null
    moods: string[]
    exclude: string[]
    logo: boolean
    notes: string
    photos: { subject: string; role: string; frame: string }[]
  } | null
  planLayout?: string | null
  textCount?: number | null
  /** What each photo should show — the prompts future image generation will use. */
  photoSubjects: string[]
  photoSource?: string | null
  attempts?: number | null
  /** Design checks still failing after repairs; empty when the design passes. */
  problems: string[]
  hasPreview: boolean
  previewUrl?: string | null
  /** Only on a single draft (or one just created), not in the list. */
  document?: LidoDocumentEntry[] | null
}
