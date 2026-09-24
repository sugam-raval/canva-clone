/** Typed client for the Lido.js (template) API. */

import type {
  LidoDocumentEntry, LidoGenerateResponse, LidoGenerationSummary, LidoTemplateSummary,
} from './lidoTypes'

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
  openaiConfigured: boolean
}

export const api = {
  health: () => request<HealthResponse>('/health'),

  lidoGenerate: (
    prompt: string,
    kind?: string,
    options: { templateId?: string; randomTemplate?: boolean } = {},
  ) =>
    request<LidoGenerateResponse>('/lido/generate', {
      method: 'POST',
      body: JSON.stringify({
        prompt,
        kind: kind || null,
        templateId: options.templateId || null,
        randomTemplate: options.randomTemplate ?? false,
      }),
    }),

  lidoTemplates: () => request<LidoTemplateSummary[]>('/lido/templates'),

  lidoGenerations: (options: { limit?: number } = {}) => {
    const params = new URLSearchParams()
    if (options.limit) params.set('limit', String(options.limit))
    const query = params.toString()
    return request<LidoGenerationSummary[]>(`/lido/generations${query ? `?${query}` : ''}`)
  },

  lidoGeneration: (designId: string) =>
    request<{ designId: string; document: LidoDocumentEntry[] }>(`/lido/generations/${designId}`),
}
