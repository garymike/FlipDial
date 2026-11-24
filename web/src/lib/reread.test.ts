import { describe, expect, it } from 'vitest'
import type { Contact } from './api'
import { changes, patchFor, type Proposed } from './reread'

const addr = (street: string, city = '') => ({
  street, city, region: '', postal_code: '', country: '', kind: 'work', label: '',
})

const contact = {
  uid: 'u', full_name: 'Noor Gems', title: '', organization: 'Noor Gems',
  emails: [{ value: 'noor@gems.example', kind: 'work', label: '' }],
  phones: [{ value: '(555) 010-0101', kind: 'work', label: '' }],
  websites: [], socials: [], addresses: [addr('2500 E Ajo WayTucson')], address: '',
  about: 'Precious stones', note: 'mine', categories: [], event: '', met_on: '', starred: false,
  source: 'scan', card_id: 'c', has_back: false,
} as Contact

const proposed: Proposed = {
  full_name: 'Noor Gems', title: '', organization: '',
  emails: [{ value: 'NOOR@gems.example', kind: 'work', label: '' }],
  phones: [
    { value: '555.010.0101', kind: 'mobile', label: '' },
    { value: '(555) 010-0102', kind: 'work', label: '' },
  ],
  websites: [], socials: [], addresses: [addr('2500 E Ajo Way', 'Tucson')],
  about: 'Precious stones, emerald and silver',
}

describe('read again', () => {
  const found = changes(contact, proposed)
  const by = (f: string) => found.find((c) => c.field === f)

  it('lists only real changes and never proposes clearing a field', () => {
    expect(found.map((c) => c.field).sort()).toEqual(['about', 'addresses', 'phones'])
    expect(by('organization')).toBeUndefined() // new reading is empty: keep what's there
    expect(by('emails')).toBeUndefined() // same address, different case
  })

  it('offers adding new items to a list by default', () => {
    const p = by('phones')!
    expect(p.choices).toEqual(['add', 'use', 'keep'])
    expect(p.added).toEqual(['(555) 010-0102 (Work)'])
  })

  it('saves only what was chosen', () => {
    const chosen = found.map((c) => (c.field === 'about' ? { ...c, choice: 'keep' as const } : c))
    const patch = patchFor(contact, proposed, chosen)
    expect(Object.keys(patch).sort()).toEqual(['addresses', 'phones'])
    expect(patch.phones!.map((p) => p.value)).toEqual(['(555) 010-0101', '(555) 010-0102'])
    expect(patch.addresses![0].city).toBe('Tucson')
  })

  it('can take the new list as a whole', () => {
    const chosen = found.map((c) => (c.field === 'phones' ? { ...c, choice: 'use' as const } : c))
    expect(patchFor(contact, proposed, chosen).phones![0].kind).toBe('mobile')
  })
})
