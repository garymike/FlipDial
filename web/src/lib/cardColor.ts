// The main color of a scanned card's front, so a card with no back can show its details on a
// back in the same color instead of a plain gray one. Worked out in the browser from the
// thumbnail; nothing is sent anywhere or stored.

export interface CardColor {
  background: string
  text: string // dark or light, whichever reads better on the background
}

const cache = new Map<string, Promise<CardColor | null>>()

export function cardColor(url: string): Promise<CardColor | null> {
  let found = cache.get(url)
  if (!found) {
    found = measure(url).catch(() => null)
    cache.set(url, found)
  }
  return found
}

async function measure(url: string): Promise<CardColor | null> {
  const img = new Image()
  img.decoding = 'async'
  img.src = url
  await img.decode()
  const w = 48
  const h = Math.max(8, Math.round((w * img.naturalHeight) / Math.max(1, img.naturalWidth)))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  if (!ctx) return null
  ctx.drawImage(img, 0, 0, w, h)
  const { data } = ctx.getImageData(0, 0, w, h)
  return dominant(data, w, h)
}

/** Most common color, by 16 levels per channel, ignoring a 2px margin (scanner edges). */
export function dominant(data: Uint8ClampedArray, w: number, h: number): CardColor | null {
  const buckets = new Map<number, { n: number; r: number; g: number; b: number }>()
  for (let y = 2; y < h - 2; y++) {
    for (let x = 2; x < w - 2; x++) {
      const i = (y * w + x) * 4
      if (data[i + 3] < 128) continue
      const r = data[i], g = data[i + 1], b = data[i + 2]
      const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
      const bucket = buckets.get(key) ?? { n: 0, r: 0, g: 0, b: 0 }
      bucket.n++
      bucket.r += r
      bucket.g += g
      bucket.b += b
      buckets.set(key, bucket)
    }
  }
  let best: { n: number; r: number; g: number; b: number } | null = null
  for (const bucket of buckets.values()) if (!best || bucket.n > best.n) best = bucket
  if (!best) return null
  const r = Math.round(best.r / best.n), g = Math.round(best.g / best.n), b = Math.round(best.b / best.n)
  return { background: `rgb(${r}, ${g}, ${b})`, text: luminance(r, g, b) > 0.45 ? '#1a1b1e' : '#f4efe6' }
}

function luminance(r: number, g: number, b: number): number {
  const lin = (c: number) => {
    const s = c / 255
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
  }
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
