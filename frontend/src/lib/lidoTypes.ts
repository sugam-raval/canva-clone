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
  /** The draft's row id (lido_drafts.id). */
  id: number
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
    photos: { subject: string; role: string; frame: string; orientation?: string }[]
  } | null
  planLayout?: string | null
  textCount?: number | null
  /** What each photo should show — the prompts photo generation uses. */
  photoSubjects: string[]
  /** corpus-cache (placeholder photos) or generated (rendered from photoSubjects). */
  photoSource?: string | null
  /** Photos that failed to generate and kept a cached placeholder instead. */
  photoFallbacks?: number | null
  attempts?: number | null
  /** Design checks still failing after repairs; empty when the design passes. */
  problems: string[]
  /** The layered gradient background it was drawn on (style, side, angle, split, tone). */
  backdrop?: { style: string; side?: string | null; angle?: number | null; split?: number | null; tone?: string | null } | null
  /** The contact lines that got an icon beside them. */
  contactIcons?: string[]
  /** The brand colours it was asked to use (#rrggbb, first = primary), if any. */
  brandPalette?: string[] | null
  /** The client logo it shows, if one was given. */
  logoUrl?: string | null
  /** How long designing it took, ms (request start → this draft saved); null if unknown. */
  generationMs?: number | null
  /** The same step by step, ms: planMs, designMs, photosMs, saveMs, totalMs. */
  timing?: Record<string, number>
  /** Each designer LLM call in order: a first draft or a repair patch, and how long it took. */
  llmCalls?: { step: 'draft' | 'repair'; ms: number; outputTokens?: number | null }[]
  /** What making it cost in OpenAI calls (backend/app/costs); null for older drafts. */
  cost?: LidoDraftCost | null
  /** The template_<n> file it was imported from, for drafts made before the database. */
  importedFrom?: string | null
  hasPreview: boolean
  previewUrl?: string | null
  /** Only on a single draft (or one just created), not in the list. */
  document?: LidoDocumentEntry[] | null
}

/** One line of POST /lido/drafts/stream: a step starting, a saved draft, the end or a failure. */
export type LidoDraftEvent =
  | { stage: 'planning' | 'designing' | 'photos' | 'saving'; variation?: number; elapsedMs: number }
  | { stage: 'repairing'; variation: number; attempt: number; problems: number; elapsedMs: number }
  | { stage: 'draft'; variation: number; draft: LidoDraftInfo; elapsedMs: number }
  | { stage: 'done'; elapsedMs: number }
  | { stage: 'error'; status: number; detail: string }

/** The bill of one draft: priced from each call's token usage (backend/app/costs/pricing.yaml). */
export interface LidoDraftCost {
  totalUsd: number
  /** plan, design, repair, photo → USD */
  byStepUsd: Record<string, number>
  /** Calls abandoned before OpenAI answered (timed out, cancelled): may still be billed. */
  unknownCalls: number
  calls: {
    step: string; model: string; kind: 'text' | 'image'
    inputTokens: number; cachedTokens: number; imageInputTokens: number; outputTokens: number
    usd: number | null; note?: string
  }[]
}
