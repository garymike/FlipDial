// Pure math for the Dial view. Kept separate so it can be unit tested.

/** Index n wrapped into 0..n-1. */
export function mod(x: number, n: number): number {
  return ((x % n) + n) % n
}

/**
 * Signed distance of card i from the current position on a looping dial.
 * 0 is the front card; negative is above/before, positive below/after.
 */
export function offset(i: number, pos: number, n: number): number {
  if (n <= 1) return i - pos
  return mod(i - pos + n / 2, n) - n / 2
}

/** Position to move to so card `target` comes to the front by the shortest way round. */
export function nearest(target: number, pos: number, n: number): number {
  const cur = Math.round(pos)
  let diff = mod(target - mod(cur, n), n)
  if (diff > n / 2) diff -= n
  return cur + diff
}

/**
 * Where a flick should settle. `velocity` is in cards per millisecond.
 * The throw is capped so a hard flick cannot skip more than `maxCards`.
 */
export function settle(pos: number, velocity: number, maxCards = 4, throwMs = 260): number {
  const extra = Math.max(-maxCards, Math.min(maxCards, velocity * throwMs))
  return Math.round(pos + extra)
}

/** First index of each initial letter, for the A to Z jump list. */
export function letterIndex(names: string[]): Map<string, number> {
  const out = new Map<string, number>()
  names.forEach((name, i) => {
    const ch = name.trim().charAt(0).toUpperCase()
    if (/[A-Z]/.test(ch) && !out.has(ch)) out.set(ch, i)
  })
  return out
}

/** First card whose name, any word of the name, or company starts with the query. */
export function seek(query: string, cards: { full_name: string; organization: string }[]): number {
  const q = query.trim().toLowerCase()
  if (!q) return -1
  return cards.findIndex((c) => {
    const name = c.full_name.toLowerCase()
    return (
      name.startsWith(q) ||
      name.split(/\s+/).some((w) => w.startsWith(q)) ||
      c.organization.toLowerCase().startsWith(q)
    )
  })
}

export interface SlotStyle {
  transform: string
  opacity: number
  zIndex: number
  shade: number
  visible: boolean
}

/** Placement of a card on the drum, `d` cards from the front. */
export function slot(d: number, spacingDeg: number, radiusPx: number): SlotStyle {
  const a = Math.abs(d)
  const visible = a < 4.5
  return {
    transform: `translate(-50%, -50%) translateZ(${-radiusPx}px) rotateX(${-d * spacingDeg}deg) translateZ(${radiusPx}px)`,
    opacity: !visible ? 0 : a <= 3.5 ? 1 : Math.max(0, 4.5 - a),
    zIndex: Math.round(100 - a * 10),
    shade: Math.min(0.82, a * 0.21),
    visible,
  }
}
