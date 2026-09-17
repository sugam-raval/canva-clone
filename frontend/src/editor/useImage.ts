import { useEffect, useState } from 'react'

/** Loads an image element per URL, cached across mounts. */
const cache = new Map<string, HTMLImageElement>()

export function useImage(url: string | undefined): HTMLImageElement | undefined {
  const [image, setImage] = useState<HTMLImageElement | undefined>(
    url ? cache.get(url) : undefined,
  )

  useEffect(() => {
    if (!url) { setImage(undefined); return }
    const cached = cache.get(url)
    if (cached) { setImage(cached); return }

    const element = new window.Image()
    element.crossOrigin = 'anonymous'
    let cancelled = false
    element.onload = () => {
      cache.set(url, element)
      if (!cancelled) setImage(element)
    }
    element.onerror = () => { if (!cancelled) setImage(undefined) }
    element.src = url
    return () => { cancelled = true }
  }, [url])

  return image
}
