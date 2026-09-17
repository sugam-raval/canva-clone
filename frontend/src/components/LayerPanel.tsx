/** Layer list — select, reorder, hide, lock, delete (§3.2). */

import type { Layer } from '../lib/types'
import { flattenLayers } from '../editor/useDocument'

const ICONS: Record<string, string> = {
  image: '▣', text: 'T', shape: '◆', group: '▤', svg: '✦',
}

export interface LayerPanelProps {
  layers: Layer[]
  selectedId: string | null
  onSelect: (layerId: string) => void
  onToggleVisible: (layerId: string) => void
  onToggleLocked: (layerId: string) => void
  onReorder: (layerId: string, direction: 1 | -1) => void
  onDelete: (layerId: string) => void
}

export function LayerPanel({
  layers, selectedId, onSelect, onToggleVisible, onToggleLocked, onReorder, onDelete,
}: LayerPanelProps) {
  // Paint order is bottom-first; the panel shows top-first, as designers expect.
  const rows = flattenLayers(layers).reverse()

  return (
    <div className="pane">
      <h3>Layers</h3>
      <div className="scroll">
        {rows.length === 0 && <div className="empty">No layers</div>}
        {rows.map(({ layer, depth }) => (
          <div
            key={layer.id}
            className={`layer-row ${selectedId === layer.id ? 'selected' : ''}`}
            style={{ paddingLeft: 10 + depth * 12 }}
            onClick={() => onSelect(layer.id)}
          >
            <span className="icon">{ICONS[layer.type] ?? '?'}</span>
            <span className="name" style={{ opacity: layer.visible ? 1 : 0.45 }}>
              {layer.type === 'text' && layer.content.trim()
                ? layer.content.trim().slice(0, 22)
                : layer.name || layer.id}
            </span>
            <span className="role">{layer.role}</span>
            <button
              title={layer.visible ? 'Hide' : 'Show'}
              onClick={(event) => { event.stopPropagation(); onToggleVisible(layer.id) }}
            >
              {layer.visible ? '◉' : '○'}
            </button>
            <button
              title={layer.locked ? 'Unlock' : 'Lock'}
              onClick={(event) => { event.stopPropagation(); onToggleLocked(layer.id) }}
            >
              {layer.locked ? '🔒' : '🔓'}
            </button>
            <button
              title="Bring forward"
              onClick={(event) => { event.stopPropagation(); onReorder(layer.id, 1) }}
            >↑</button>
            <button
              title="Send backward"
              onClick={(event) => { event.stopPropagation(); onReorder(layer.id, -1) }}
            >↓</button>
            <button
              title="Delete"
              onClick={(event) => { event.stopPropagation(); onDelete(layer.id) }}
            >✕</button>
          </div>
        ))}
      </div>
    </div>
  )
}
