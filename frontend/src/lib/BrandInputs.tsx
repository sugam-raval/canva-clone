/** Brand inputs shared by "Fill a template" and "Design new template": an optional
 * colour palette (docs/palette_theme.md — at most 4 colours, the first is primary) and
 * an optional logo URL. Both pages send them as `palette` / `logoUrl`. */

export const MAX_PALETTE = 4
export const PALETTE_PRESETS: { name: string; colors: string[] }[] = [
  { name: 'Forest', colors: ['#0b3d2e', '#f2c14e', '#e4572e', '#f7f3e9'] },
  { name: 'Ocean', colors: ['#1d3557', '#457b9d', '#a8dadc', '#f1faee'] },
  { name: 'Sunset', colors: ['#6a0d52', '#e4572e', '#ffc857', '#fff4e0'] },
]

export function BrandInputs({
  palette, onPalette, logoUrl, onLogoUrl, disabled, emptyLabel, logoTitle,
}: {
  palette: string[]
  onPalette: (palette: string[]) => void
  logoUrl: string
  onLogoUrl: (url: string) => void
  disabled?: boolean
  /** What happens with no colours chosen, e.g. "template colours". */
  emptyLabel: string
  /** Tooltip on the logo field: what the logo will replace. */
  logoTitle: string
}) {
  return (
    <>
      <div className="prompt-row" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>
          Colour theme (optional, up to {MAX_PALETTE}):
        </span>
        {palette.length === 0 && (
          <span style={{ fontSize: 12 }}>{emptyLabel}</span>
        )}
        {palette.map((color, i) => (
          <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: 2 }}>
            <input
              type="color"
              value={color}
              title={i === 0 ? `Primary ${color}` : color}
              disabled={disabled}
              onChange={(e) => onPalette(palette.map((c, j) => (j === i ? e.target.value : c)))}
              style={{ width: 32, height: 28, padding: 0, border: 'none', background: 'none' }}
            />
            <button
              onClick={() => onPalette(palette.filter((_, j) => j !== i))}
              disabled={disabled}
              title="Remove colour"
              style={{ padding: '0 6px' }}
            >
              ×
            </button>
          </span>
        ))}
        {palette.length < MAX_PALETTE && (
          <button
            onClick={() => onPalette([...palette, palette.length ? palette[palette.length - 1] : '#1d3557'])}
            disabled={disabled}
          >
            + Add colour
          </button>
        )}
        {PALETTE_PRESETS.map((preset) => (
          <button key={preset.name} onClick={() => onPalette(preset.colors)} disabled={disabled}
            title={preset.colors.join(', ')}>
            {preset.name}
          </button>
        ))}
        {palette.length > 0 && (
          <button onClick={() => onPalette([])} disabled={disabled}>Clear</button>
        )}
      </div>
      <div className="prompt-row" style={{ alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
        <span style={{ fontSize: 12, color: 'var(--muted)' }}>Brand logo (optional):</span>
        <input
          type="url"
          value={logoUrl}
          onChange={(e) => onLogoUrl(e.target.value)}
          placeholder="https://example.com/logo.png"
          disabled={disabled}
          style={{ flex: '1 1 260px', minWidth: 200 }}
          title={logoTitle}
        />
        {logoUrl.trim() && (
          <>
            <img
              src={logoUrl.trim()}
              alt="Logo preview"
              style={{ height: 28, width: 28, objectFit: 'contain', background: '#fff', borderRadius: 4 }}
              onError={(e) => { (e.target as HTMLImageElement).style.visibility = 'hidden' }}
            />
            <button onClick={() => onLogoUrl('')} disabled={disabled}>Clear</button>
          </>
        )}
      </div>
    </>
  )
}
