// Demo mode: an in-browser stand-in for the FlipDial server, filled with invented people.
// Built only with `npm run build:demo`; it is not part of the normal app bundle.
// Nothing is saved: reloading the page starts over.

import data from '../../../demo/contacts.json'
import {
  addressLine,
  ApiError,
  blankAddress,
  setUrls,
  type AuditEntry,
  type Contact,
  type ContactInput,
  type ReviewItem,
  type Scan,
  type Typed,
} from './api'

const images = import.meta.glob('../../../demo/cards/*.svg', {
  eager: true,
  query: '?url',
  import: 'default',
}) as Record<string, string>

function imageFor(cardId: string, side: string): string {
  const s = side === 'thumb' ? 'front' : side === 'scan' ? 'front' : side
  return images[`../../../demo/cards/${cardId}-${s}.svg`] ?? ''
}

// The sample file stores plain values; give them types the way the server does.
type Raw = Omit<Contact, 'emails' | 'phones' | 'websites' | 'addresses'> & {
  emails: string[]
  phones: string[]
  websites: string[]
}
const typed = (values: string[], first = 'work'): Typed[] =>
  values.map((value, i) => ({ value, kind: i === 0 ? first : 'mobile', label: '' }))
let contacts: Contact[] = (structuredClone(data.contacts) as Raw[]).map((c) => ({
  ...c,
  emails: typed(c.emails).map((t) => ({ ...t, kind: 'work' })),
  phones: typed(c.phones),
  websites: typed(c.websites).map((t) => ({ ...t, kind: 'work' })),
  addresses: c.address ? [{ ...blankAddress(), street: c.address }] : [],
}))
let review: ReviewItem[] = structuredClone(data.review) as ReviewItem[]
const notSame = new Set<string>()
const merges: { id: number; keep: Contact; dropped: Contact; undone: boolean; at: string }[] = []
const audit: AuditEntry[] = []
let nextId = 1

function record(action: string, target = '', detail: Record<string, unknown> = {}) {
  audit.unshift({ id: nextId++, ts: new Date().toISOString(), actor: 'demo', action, target, detail })
}

const fold = (s: string) => s.normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
const digits = (p: string) => p.replace(/\D/g, '').slice(-10)
const words = (s: string) => fold(s).match(/[a-z0-9]+/g)?.sort().join(' ') ?? ''

function similar(a: Contact, b: Contact): { score: number; reasons: string[] } | null {
  const reasons: string[] = []
  let score = 0
  if (a.emails.some((e) => b.emails.map((x) => fold(x.value)).includes(fold(e.value)))) {
    reasons.push('same_email')
    score = 0.95
  }
  if (a.phones.some((p) => digits(p.value) && b.phones.map((x) => digits(x.value)).includes(digits(p.value)))) {
    reasons.push('same_phone')
    score = Math.max(score, 0.85)
  }
  if (words(a.full_name) === words(b.full_name)) {
    reasons.push('same_name')
    score = Math.max(score, 0.7)
  }
  return score ? { score, reasons } : null
}

// "Read again" in the demo: a few seconds of pretend reading, then a made-up improvement
// (a mobile number and a fuller About line) so the review step can be tried.
const rereads = new Map<string, number>()
function rereadState(c: Contact) {
  const at = rereads.get(c.uid)
  if (!c.card_id || at === undefined) return { status: 'none', card_id: c.card_id ?? '' }
  if (Date.now() - at < 3000)
    return { status: 'pending', card_id: c.card_id, progress: { stage: 'reading', seconds: Math.round((Date.now() - at) / 1000), fields: {} } }
  return {
    status: 'done',
    card_id: c.card_id,
    proposed: {
      full_name: c.full_name,
      title: c.title,
      organization: c.organization,
      emails: c.emails,
      phones: [...c.phones, { value: '(555) 010-0199', kind: 'mobile', label: '' }],
      websites: c.websites,
      socials: c.socials,
      addresses: c.addresses,
      about: c.about ? `${c.about}. Commissions welcome.` : 'Commissions welcome.',
    },
  }
}

// Cards a contact gained by merging, so the demo can show a card history.
const extraScans = new Map<string, Scan[]>()
function scansOf(c: Contact): Scan[] {
  const own = c.card_id ? [{ card_id: c.card_id, created_at: '', has_back: c.has_back }] : []
  const all = [...(extraScans.get(c.uid) ?? []), ...own]
  return all.filter((x, i) => all.findIndex((y) => y.card_id === x.card_id) === i)
}

function find(uid: string): Contact {
  const c = contacts.find((x) => x.uid === uid)
  if (!c) throw new ApiError(404, 'not_found')
  return c
}

function fromInput(input: ContactInput, base: Partial<Contact>): Contact {
  const categories = [...new Set([...(input.event ? [input.event] : []), ...(input.tags ?? [])])]
  const { tags: _tags, ...rest } = input
  return {
    uid: base.uid ?? `demo-new-${nextId++}`,
    source: base.source ?? 'manual',
    card_id: base.card_id ?? null,
    has_back: base.has_back ?? false,
    categories,
    ...rest,
    addresses: rest.addresses ?? [],
    address: rest.addresses?.[0] ? addressLine(rest.addresses[0]) : '',
  }
}

function list(q: URLSearchParams) {
  const needle = fold(q.get('q') ?? '').trim()
  const deck = q.get('deck') ?? ''
  const scan = q.get('scan') ?? 'all'
  const starred = q.get('starred') === 'true'
  const sorted = [...contacts].sort((a, b) => a.full_name.localeCompare(b.full_name))
  const out = sorted.filter(
    (c) =>
      (!deck || c.event === deck || c.categories.includes(deck)) &&
      !(scan === 'yes' && !c.card_id) &&
      !(scan === 'no' && c.card_id) &&
      (!starred || c.starred) &&
      (!needle || fold([c.full_name, c.organization, c.title, ...c.emails.map((e) => e.value), c.event].join(' ')).includes(needle)),
  )
  const decks = new Map<string, number>()
  for (const c of contacts) if (c.event) decks.set(c.event, (decks.get(c.event) ?? 0) + 1)
  return {
    contacts: out,
    total: contacts.length,
    starred: contacts.filter((c) => c.starred).length,
    with_scan: contacts.filter((c) => c.card_id).length,
    decks: [...decks].sort().map(([name, count]) => ({ name, count })),
  }
}

function duplicates() {
  const pairs = []
  for (let i = 0; i < contacts.length; i++)
    for (let j = i + 1; j < contacts.length; j++) {
      const a = contacts[i], b = contacts[j]
      if (notSame.has([a.uid, b.uid].sort().join('|'))) continue
      const m = similar(a, b)
      if (m && m.score >= 0.6) pairs.push({ ...m, a, b })
    }
  return pairs.sort((x, y) => y.score - x.score)
}

const readonly = () => {
  throw new ApiError(403, 'demo_readonly')
}

export async function handle(method: string, path: string, body?: unknown): Promise<unknown> {
  await new Promise((r) => setTimeout(r, 120)) // feel like a real server
  const url = new URL(path, 'https://demo.invalid')
  const p = url.pathname.replace(/^\/api/, '')
  const seg = p.split('/').filter(Boolean).map(decodeURIComponent)
  const route = `${method} /${seg[0] ?? ''}`

  switch (route) {
    case 'GET /update':
      return { current: 'demo', enabled: false, available: false, release: null, install: 'demo', can_update: false }
    case 'GET /status':
      return {
        state: 'ok',
        items: [
          { id: 'model_server', label: 'Ollama', state: 'ok', detail: 'Running (in the real app, on your computer).', fix: '' },
          { id: 'model_installed', label: 'Card-reading model', state: 'ok', detail: 'Installed.', fix: '' },
          { id: 'model_vision', label: 'Model can read images', state: 'ok', detail: 'Yes.', fix: '' },
          { id: 'worker', label: 'Scan worker', state: 'ok', detail: 'Running.', fix: '' },
          { id: 'contacts_server', label: 'Contacts server', state: 'ok', detail: 'In the demo, contacts live in your browser.', fix: '' },
        ],
      }
    case 'GET /me':
      return { user: 'demo', mode: 'none', storage: 'local' }
    case 'POST /sync':
      record('contacts.sync', '', { added: 0, updated: 0, removed: 0 })
      return { added: 0, updated: 0, removed: 0, skipped: 0 }
    case 'POST /contacts':
      if (seg[2] === 'reread') {
        const c = find(seg[1])
        if (!c.card_id) throw new ApiError(409, 'no_scan')
        rereads.set(c.uid, Date.now())
        record('contact.reread', c.uid)
        return { status: 'pending', card_id: c.card_id }
      }
      throw new ApiError(404, 'not_found')
    case 'GET /contacts':
      if (seg[2] === 'scans') return { scans: scansOf(find(seg[1])) }
      if (seg[2] === 'reread') return rereadState(find(seg[1]))
      return seg[1] ? find(seg[1]) : list(url.searchParams)
    case 'PATCH /contacts': {
      const c = find(seg[1])
      const changes = body as Partial<ContactInput>
      const pick = (changes as { card_id?: string }).card_id
      if (pick) {
        const scan = scansOf(c).find((x) => x.card_id === pick)
        if (!scan) throw new ApiError(409, 'not_this_contacts_card')
        c.has_back = scan.has_back
      }
      Object.assign(c, changes)
      if (changes.addresses) c.address = changes.addresses[0] ? addressLine(changes.addresses[0]) : ''
      if (changes.tags || changes.event !== undefined)
        c.categories = [...new Set([...(c.event ? [c.event] : []), ...(changes.tags ?? c.categories)])]
      record('contact.edit', c.uid, { fields: Object.keys(changes).sort() })
      return c
    }
    case 'DELETE /contacts': {
      if (seg[2] === 'reread') {
        rereads.delete(seg[1])
        return { discarded: true }
      }
      const c = find(seg[1])
      contacts = contacts.filter((x) => x !== c)
      record('contact.forget', c.uid, { scans: c.card_id ? 1 : 0 })
      return { forgotten: c.uid, scans: c.card_id ? 1 : 0 }
    }
    case 'GET /review': {
      if (seg[1] === 'dismissed') return { items: [] }
      if (seg[2] === 'matches') {
        const item = review.find((r) => r.card_id === seg[1])
        const probe = { full_name: item?.fields?.full_name.value ?? '', emails: item?.fields?.emails ?? [], phones: [] } as unknown as Contact
        return { matches: contacts.flatMap((c) => { const m = similar(probe, c); return m ? [{ ...m, contact: c }] : [] }).slice(0, 3) }
      }
      return { items: review, ready: review.length }
    }
    case 'POST /cards':
      throw new ApiError(403, 'demo_readonly') // the demo's cards are drawings, not scans
    case 'POST /review': {
      const item = review.find((r) => r.card_id === seg[1])
      if (!item) throw new ApiError(404, 'not_found')
      review = review.filter((r) => r !== item)
      if (seg[2] === 'dismiss') {
        record('card.dismiss', item.card_id)
        return { card_id: item.card_id, status: 'dismissed' }
      }
      if (seg[2] === 'attach') {
        const c = find(seg[3])
        Object.assign(c, fromInput(body as ContactInput, c), { card_id: item.card_id })
        record('card.attach', item.card_id, { vcard_uid: c.uid })
        return c
      }
      const c = fromInput(body as ContactInput, { source: 'scan', card_id: item.card_id })
      contacts.push(c)
      record('card.approve', item.card_id, { vcard_uid: c.uid })
      return { ...c, uid: c.uid }
    }
    case 'GET /duplicates': {
      const pairs = duplicates()
      return { pairs, count: pairs.length }
    }
    case 'POST /duplicates': {
      const { uid_a, uid_b } = body as { uid_a: string; uid_b: string }
      notSame.add([uid_a, uid_b].sort().join('|'))
      record('duplicate.not_same', uid_a, { other: uid_b })
      return { ok: true }
    }
    case 'POST /merge': {
      if (seg[2] === 'undo') {
        const m = merges.find((x) => x.id === Number(seg[1]))
        if (!m || m.undone) throw new ApiError(409, 'already_undone')
        contacts = contacts.map((c) => (c.uid === m.keep.uid ? m.keep : c))
        contacts.push(m.dropped)
        m.undone = true
        record('contact.merge_undo', String(m.id))
        return { restored: [m.keep.uid, m.dropped.uid] }
      }
      const { keep_uid, drop_uid, contact, show_card } = body as {
        keep_uid: string
        drop_uid: string
        contact: ContactInput
        show_card?: string
      }
      const keep = find(keep_uid), drop = find(drop_uid)
      const both = [...scansOf(keep), ...scansOf(drop)]
      extraScans.set(keep_uid, both)
      const shown = both.find((x) => x.card_id === show_card) ?? both[both.length - 1] ?? null
      const merged = fromInput(contact, { ...keep, card_id: shown?.card_id ?? null, has_back: shown?.has_back ?? false })
      const id = nextId++
      merges.unshift({ id, keep: structuredClone(keep), dropped: structuredClone(drop), undone: false, at: new Date().toISOString() })
      contacts = contacts.filter((c) => c !== drop).map((c) => (c === keep ? merged : c))
      record('contact.merge', keep_uid, { dropped: drop_uid, merge_id: id })
      return { contact: merged, merge_id: id }
    }
    case 'GET /merges':
      return {
        merges: merges.map((m) => ({ id: m.id, keep_uid: m.keep.uid, drop_uid: m.dropped.uid, drop_name: m.dropped.full_name, created_at: m.at, undone: m.undone })),
      }
    case 'GET /imports':
      return { imports: [] }
    case 'POST /import':
    case 'POST /imports':
    case 'POST /logout':
      return readonly()
    case 'GET /audit':
      if (seg[1] === 'verify') return { ok: true, entries: audit.length, broken_at: null, head: '' }
      return { entries: audit }
  }
  throw new ApiError(404, 'not_found')
}

export function install(): void {
  setUrls({
    image: imageFor,
    original: (cardId, role) => imageFor(cardId, role),
    exportUrl: () => '#/transfer',
  })
}
