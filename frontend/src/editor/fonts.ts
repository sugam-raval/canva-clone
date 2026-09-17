/**
 * Loads the exact font files the server shaped with.
 *
 * ADR 0001: the browser draws glyphs at positions HarfBuzz computed server-side. Those
 * positions are only correct if the browser rasterises the same face, so the editor
 * loads the same static TTFs the layout engine measured — never a Google Fonts CSS
 * import, which could serve a different version or a variable instance.
 */

const loaded = new Map<string, Promise<void>>()

export interface FontFaceDescriptor {
  key: string
  family: string
  weight: number
  style: string
  url: string
}

/** Family name used in canvas `font` strings, unique per weight+style. */
export function canvasFamily(fontKey: string): string {
  return `LD-${fontKey}`
}

export function loadFace(descriptor: FontFaceDescriptor): Promise<void> {
  const existing = loaded.get(descriptor.key)
  if (existing) return existing

  const promise = (async () => {
    const face = new FontFace(canvasFamily(descriptor.key), `url(${descriptor.url})`, {
      weight: String(descriptor.weight),
      style: descriptor.style,
    })
    await face.load()
    document.fonts.add(face)
  })().catch((error) => {
    // A missing face must degrade to a fallback, not blank the canvas.
    console.warn(`font ${descriptor.key} failed to load`, error)
  })

  loaded.set(descriptor.key, promise)
  return promise
}

export async function loadAll(descriptors: FontFaceDescriptor[]): Promise<void> {
  await Promise.all(descriptors.map(loadFace))
}

export function isLoaded(fontKey: string): boolean {
  return loaded.has(fontKey)
}
