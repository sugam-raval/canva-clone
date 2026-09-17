/**
 * Editor document state.
 *
 * The document is the source of truth; the draw list is derived from it by the server
 * (ADR 0001). An edit therefore follows: mutate locally for instant feedback -> PATCH
 * -> refetch the draw list. Refetching is debounced so a drag produces one round-trip
 * on release rather than one per frame (§3.2: "re-solve layout on gesture end, not per
 * frame").
 */

import { useCallback, useEffect, useRef, useState } from 'react'

import { api } from '../lib/api'
import type { DesignDoc, DrawList, Layer, Violation } from '../lib/types'

const HISTORY_LIMIT = 50

export interface DocumentState {
  doc: DesignDoc | null
  drawList: DrawList | null
  violations: Violation[]
  loading: boolean
  saving: boolean
  error: string | null
  canUndo: boolean
  canRedo: boolean
}

export function useDocument(docId: string | undefined, viewScale: number) {
  const [doc, setDoc] = useState<DesignDoc | null>(null)
  const [drawList, setDrawList] = useState<DrawList | null>(null)
  const [violations, setViolations] = useState<Violation[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const undoStack = useRef<DesignDoc[]>([])
  const redoStack = useRef<DesignDoc[]>([])
  const [historyVersion, setHistoryVersion] = useState(0)
  const refreshTimer = useRef<number | null>(null)
  const scaleRef = useRef(viewScale)
  scaleRef.current = viewScale

  const refreshDrawList = useCallback(async () => {
    if (!docId) return
    try {
      setDrawList(await api.getDrawList(docId, scaleRef.current))
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    }
  }, [docId])

  useEffect(() => {
    if (!docId) return
    let cancelled = false
    setLoading(true)
    ;(async () => {
      try {
        const [{ doc: loaded }, list] = await Promise.all([
          api.getDoc(docId),
          api.getDrawList(docId, scaleRef.current),
        ])
        if (cancelled) return
        setDoc(loaded)
        setDrawList(list)
        setError(null)
      } catch (caught) {
        if (!cancelled) setError(caught instanceof Error ? caught.message : String(caught))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [docId])

  // Re-render at the new zoom without a round-trip storm.
  useEffect(() => {
    if (!doc) return
    const timer = window.setTimeout(refreshDrawList, 120)
    return () => window.clearTimeout(timer)
  }, [viewScale, doc?.id, refreshDrawList, doc])

  const scheduleRefresh = useCallback(() => {
    if (refreshTimer.current) window.clearTimeout(refreshTimer.current)
    refreshTimer.current = window.setTimeout(refreshDrawList, 60)
  }, [refreshDrawList])

  const pushHistory = useCallback((snapshot: DesignDoc) => {
    undoStack.current.push(structuredClone(snapshot))
    if (undoStack.current.length > HISTORY_LIMIT) undoStack.current.shift()
    redoStack.current = []
    setHistoryVersion((version) => version + 1)
  }, [])

  const persist = useCallback(async (next: DesignDoc, { solve = false } = {}) => {
    if (!docId) return
    setSaving(true)
    try {
      if (solve) {
        const result = await api.patchDoc(docId, { layers: next.layers, palette: next.palette, title: next.title })
        const solved = await api.solve(docId)
        setDoc(solved.doc)
        setViolations(solved.violations)
        void result
      } else {
        const { doc: saved } = await api.patchDoc(docId, {
          layers: next.layers, palette: next.palette, title: next.title,
        })
        setDoc(saved)
      }
      setError(null)
      scheduleRefresh()
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught))
    } finally {
      setSaving(false)
    }
  }, [docId, scheduleRefresh])

  /** Apply a local mutation, record history, and persist. */
  const mutate = useCallback((
    recipe: (draft: DesignDoc) => void,
    options: { solve?: boolean; history?: boolean } = {},
  ) => {
    setDoc((current) => {
      if (!current) return current
      if (options.history !== false) pushHistory(current)
      const next = structuredClone(current)
      recipe(next)
      void persist(next, { solve: options.solve })
      return next
    })
  }, [persist, pushHistory])

  const updateLayer = useCallback((
    layerId: string,
    patch: Partial<Layer> | ((layer: Layer) => void),
    options: { solve?: boolean; history?: boolean } = {},
  ) => {
    mutate((draft) => {
      const target = findLayer(draft.layers, layerId)
      if (!target) return
      if (typeof patch === 'function') patch(target)
      else Object.assign(target, patch)
    }, options)
  }, [mutate])

  const undo = useCallback(() => {
    const previous = undoStack.current.pop()
    if (!previous) return
    setDoc((current) => {
      if (current) redoStack.current.push(structuredClone(current))
      void persist(previous)
      return previous
    })
    setHistoryVersion((version) => version + 1)
  }, [persist])

  const redo = useCallback(() => {
    const next = redoStack.current.pop()
    if (!next) return
    setDoc((current) => {
      if (current) undoStack.current.push(structuredClone(current))
      void persist(next)
      return next
    })
    setHistoryVersion((version) => version + 1)
  }, [persist])

  /** Replace the document wholesale — used after server ops like rewrite or solve. */
  const replaceDoc = useCallback((next: DesignDoc, nextViolations: Violation[] = []) => {
    setDoc((current) => {
      if (current) pushHistory(current)
      return next
    })
    setViolations(nextViolations)
    scheduleRefresh()
  }, [pushHistory, scheduleRefresh])

  return {
    doc, drawList, violations, loading, saving, error,
    canUndo: undoStack.current.length > 0,
    canRedo: redoStack.current.length > 0,
    historyVersion,
    mutate, updateLayer, undo, redo, replaceDoc, refreshDrawList, setError,
  }
}

export function findLayer(layers: Layer[], layerId: string): Layer | null {
  for (const layer of layers) {
    if (layer.id === layerId) return layer
    if (layer.type === 'group') {
      const nested = findLayer(layer.children, layerId)
      if (nested) return nested
    }
  }
  return null
}

export function flattenLayers(layers: Layer[], depth = 0): { layer: Layer; depth: number }[] {
  const out: { layer: Layer; depth: number }[] = []
  for (const layer of layers) {
    out.push({ layer, depth })
    if (layer.type === 'group') out.push(...flattenLayers(layer.children, depth + 1))
  }
  return out
}
