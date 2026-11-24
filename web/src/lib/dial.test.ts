import { describe, expect, it } from 'vitest'
import { letterIndex, mod, nearest, offset, seek, settle, slot } from './dial'

describe('mod', () => {
  it('wraps negatives', () => {
    expect(mod(-1, 5)).toBe(4)
    expect(mod(7, 5)).toBe(2)
  })
})

describe('offset', () => {
  it('is zero for the front card', () => {
    expect(offset(3, 3, 10)).toBe(0)
  })
  it('wraps around the shortest way', () => {
    expect(offset(0, 9, 10)).toBe(1) // card 0 is just after card 9
    expect(offset(9, 0, 10)).toBe(-1)
  })
  it('works mid-drag', () => {
    expect(offset(2, 1.5, 10)).toBeCloseTo(0.5)
  })
})

describe('nearest', () => {
  it('jumps forward or backward, whichever is shorter', () => {
    expect(nearest(1, 9, 10)).toBe(11)
    expect(nearest(8, 0, 10)).toBe(-2)
  })
  it('keeps going from an unwrapped position', () => {
    expect(nearest(2, 23, 10)).toBe(22)
  })
})

describe('settle', () => {
  it('rounds a slow release to the nearest card', () => {
    expect(settle(4.4, 0)).toBe(4)
  })
  it('carries a flick forward but caps it', () => {
    expect(settle(4, 0.008)).toBe(6)
    expect(settle(4, 1)).toBe(8)
    expect(settle(4, -1)).toBe(0)
  })
})

describe('letterIndex', () => {
  it('maps the first card for each letter', () => {
    const idx = letterIndex(['Ava', 'Ben', 'Bo', 'élan', '3M', 'Cara'])
    expect(idx.get('A')).toBe(0)
    expect(idx.get('B')).toBe(1)
    expect(idx.get('C')).toBe(5)
    expect(idx.has('3')).toBe(false)
  })
})

describe('seek', () => {
  const cards = [
    { full_name: 'Ava Example', organization: 'Glass Studio' },
    { full_name: 'Finn Brandt', organization: 'Brandt Financial' },
  ]
  it('matches first name, last name or company', () => {
    expect(seek('fi', cards)).toBe(1)
    expect(seek('brandt', cards)).toBe(1)
    expect(seek('glass', cards)).toBe(0)
    expect(seek('zzz', cards)).toBe(-1)
    expect(seek('  ', cards)).toBe(-1)
  })
  it('falls back to words anywhere: title, email, event, About', () => {
    const more = [
      { full_name: 'Noor Gems', organization: 'Noor Gems', about: 'Precious stones, emerald', emails: [{ value: 'noor@gems.example' }] },
      { full_name: 'Café Ñandú', organization: '', title: 'Owner', event: 'Art Fair 2026' },
    ]
    expect(seek('precious', more)).toBe(0)
    expect(seek('noor@', more)).toBe(0)
    expect(seek('art fair', more)).toBe(1)
    expect(seek('nandu', more)).toBe(1) // accents ignored
  })
})

describe('slot', () => {
  it('keeps nearby cards fully opaque and fades only the far edge', () => {
    expect(slot(0, 17, 420).opacity).toBe(1)
    expect(slot(3, 17, 420).opacity).toBe(1)
    expect(slot(4, 17, 420).opacity).toBeCloseTo(0.5)
    expect(slot(6, 17, 420).visible).toBe(false)
  })
  it('stacks the front card on top', () => {
    expect(slot(0, 17, 420).zIndex).toBeGreaterThan(slot(1, 17, 420).zIndex)
  })
})
