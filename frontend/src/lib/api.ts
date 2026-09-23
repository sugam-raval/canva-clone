/** Typed client for the §0.10 API surface. */

import type {
  LidoDocumentEntry, LidoGenerateResponse, LidoScratchResponse, LidoScratchSummary,
} from './lidoTypes'
import type {
  DesignDoc, DocSummary, DrawList, Layer, ProgressEvent, Violation,
} from './types'

const BASE = '/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep the status line */ }
    throw new ApiError(detail, response.status)
  }
  return response.status === 204 ? (undefined as T) : response.json()
}

export class ApiError extends Error {
  constructor(message: string, public status: number) {
    super(message)
    this.name = 'ApiError'
  }
}

export interface HealthResponse {
  status: string
  database: boolean
  adapters: Record<string, string>
  fonts: number
  openaiConfigured: boolean
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  generate: (prompt: string, count = 1) =>
    request<{ requestId: string; docIds: string[] }>('/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt, count }),
    }),

  listDocs: () => request<DocSummary[]>('/docs'),

  getDoc: (docId: string) =>
    request<{ doc: DesignDoc; assets: Record<string, string>; updatedAt: string | null }>(
      `/docs/${docId}`,
    ),

  getDrawList: (docId: string, scale: number) =>
    request<DrawList>(`/docs/${docId}/drawlist?scale=${scale}`),

  patchDoc: (docId: string, patch: { layers?: Layer[]; title?: string; palette?: string[] }) =>
    request<{ doc: DesignDoc }>(`/docs/${docId}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  solve: (docId: string) =>
    request<{ doc: DesignDoc; violations: Violation[] }>(`/docs/${docId}/solve`, {
      method: 'POST',
    }),

  deleteDoc: (docId: string) => request<{ deleted: boolean }>(`/docs/${docId}`, { method: 'DELETE' }),

  duplicateDoc: (docId: string) =>
    request<{ docId: string }>(`/docs/${docId}/duplicate`, { method: 'POST' }),

  regenerateLayer: (docId: string, layerId: string, promptOverride?: string) =>
    request<{ patch: Record<string, unknown>; costCents: number }>(
      `/docs/${docId}/layers/${layerId}/regenerate`,
      { method: 'POST', body: JSON.stringify({ promptOverride: promptOverride ?? null }) },
    ),

  /** Re-roll, re-densify or swap a vector motif. Procedural, so this costs nothing. */
  reshapeLayer: (docId: string, layerId: string,
                 body: { motif?: string; seed?: number; density?: number } = {}) =>
    request<{ patch: Record<string, unknown>; costCents: number }>(
      `/docs/${docId}/layers/${layerId}/reshape`,
      { method: 'POST', body: JSON.stringify(body) },
    ),

  removeBackground: (docId: string, layerId: string) =>
    request<{ patch: Record<string, unknown> }>(`/docs/${docId}/layers/${layerId}/remove-bg`, {
      method: 'POST',
    }),

  rewriteCopy: (docId: string, layerIds: string[], instruction: string) =>
    request<{ patches: { layerId: string; content: string }[]; doc: DesignDoc; violations: Violation[] }>(
      `/docs/${docId}/copy/rewrite`,
      { method: 'POST', body: JSON.stringify({ layerIds, instruction }) },
    ),

  resize: (docId: string, width: number, height: number) =>
    request<{ docId: string; doc: DesignDoc }>(`/docs/${docId}/resize`, {
      method: 'POST',
      body: JSON.stringify({ width, height }),
    }),

  exportDoc: (docId: string, format: string, scale: number) =>
    request<{ exportId: string; state: string; url: string | null }>(`/docs/${docId}/export`, {
      method: 'POST',
      body: JSON.stringify({ format, scale }),
    }),

  fonts: () =>
    request<{
      faces: { key: string; family: string; weight: number; style: string; url: string }[]
      families: string[]
      byVibe: Record<string, string[]>
    }>('/fonts'),

  motifs: () =>
    request<{
      motifs: string[]
      compositional: string[]
      decorative: string[]
      stroked: string[]
      rerollable: string[]
    }>('/motifs'),

  lidoGenerate: (prompt: string, kind?: string) =>
    request<LidoGenerateResponse>('/lido/generate', {
      method: 'POST',
      body: JSON.stringify({ prompt, kind: kind || null }),
    }),

  /** Design a document from scratch — no template is retrieved or referenced. */
  lidoScratch: (
    prompt: string,
    options: { kind?: string; size?: { width: number; height: number }; generateImages?: boolean } = {},
  ) =>
    request<LidoScratchResponse>('/lido/scratch', {
      method: 'POST',
      body: JSON.stringify({
        prompt,
        kind: options.kind || null,
        size: options.size ?? null,
        generateImages: options.generateImages ?? true,
      }),
    }),

  lidoScratchList: () => request<LidoScratchSummary[]>('/lido/scratch'),

  lidoScratchGet: (designId: string) =>
    request<{ designId: string; document: LidoDocumentEntry[] }>(`/lido/scratch/${designId}`),
}

/** Subscribes to the §0.9 progress stream. Returns an unsubscribe function. */
export function subscribeProgress(
  requestId: string,
  onEvent: (event: ProgressEvent) => void,
  onError?: (error: Error) => void,
): () => void {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const url = `${protocol}//${window.location.host}${BASE}/progress?requestId=${encodeURIComponent(requestId)}`
  const socket = new WebSocket(url)
  let closed = false

  socket.onmessage = (message) => {
    try {
      const event = JSON.parse(message.data) as ProgressEvent
      if (event.t !== 'ping') onEvent(event)
    } catch {
      /* a malformed frame must not tear down the stream */
    }
  }
  socket.onerror = () => { if (!closed) onError?.(new Error('progress stream failed')) }

  return () => {
    closed = true
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close()
    }
  }
}
