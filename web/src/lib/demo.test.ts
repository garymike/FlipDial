import { describe, expect, it } from 'vitest'
import type { ContactList, DuplicatePair } from './api'
import { handle } from './demo'

const get = <T>(path: string) => handle('GET', path) as Promise<T>

describe('demo stand-in server', () => {
  it('lists, filters and searches invented contacts', async () => {
    const all = await get<ContactList>('/api/contacts')
    expect(all.total).toBeGreaterThan(10)
    expect(all.contacts.every((c) => c.emails.every((e) => e.value.endsWith('.example')))).toBe(true)
    const deck = await get<ContactList>('/api/contacts?deck=SecCon%202026')
    expect(deck.contacts.every((c) => c.event === 'SecCon 2026')).toBe(true)
    const found = await get<ContactList>('/api/contacts?q=letterpress')
    expect(found.contacts.map((c) => c.full_name)).toEqual(['Bram Okonkwo-Lind'])
  })

  it('finds the planted duplicate, merges and undoes', async () => {
    const { pairs } = await get<{ pairs: DuplicatePair[] }>('/api/duplicates')
    expect(pairs).toHaveLength(1)
    const [p] = pairs
    const before = (await get<ContactList>('/api/contacts')).total
    const r = (await handle('POST', '/api/merge', {
      keep_uid: p.a.uid,
      drop_uid: p.b.uid,
      contact: { ...p.a, tags: [] },
    })) as { merge_id: number }
    expect((await get<ContactList>('/api/contacts')).total).toBe(before - 1)
    await handle('POST', `/api/merge/${r.merge_id}/undo`)
    expect((await get<ContactList>('/api/contacts')).total).toBe(before)
  })

  it('approves a review card and records it', async () => {
    const q = await get<{ items: { card_id: string }[] }>('/api/review')
    const id = q.items[0].card_id
    await handle('POST', `/api/review/${id}/approve`, {
      full_name: 'Test Person', title: '', organization: '', emails: [], phones: [], websites: [],
      socials: [], address: '', event: '', met_on: '', starred: false, tags: [],
    })
    const log = await get<{ entries: { action: string }[] }>('/api/audit')
    expect(log.entries[0].action).toBe('card.approve')
  })

  it('refuses imports', async () => {
    await expect(handle('POST', '/api/import', { text: 'x' })).rejects.toMatchObject({ code: 'demo_readonly' })
  })
})
