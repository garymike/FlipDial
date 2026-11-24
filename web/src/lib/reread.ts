// "Read again": compare what the card says now with the saved contact, field by field.
// Pure functions so they can be tested. A proposal never removes a value: an empty field in
// the new reading is ignored, and lists default to adding what's missing.

import { addressLine, kindName, type Contact, type PostalAddress, type Social, type Typed } from './api'

export interface Proposed {
  full_name: string
  title: string
  organization: string
  emails: Typed[]
  phones: Typed[]
  websites: Typed[]
  socials: Social[]
  addresses: PostalAddress[]
  about: string
}

type Scalar = 'full_name' | 'title' | 'organization' | 'about'
type List = 'emails' | 'phones' | 'websites' | 'socials' | 'addresses'
export type Field = Scalar | List

export const LABELS: Record<Field, string> = {
  full_name: 'Name',
  title: 'Title',
  organization: 'Company',
  emails: 'Email',
  phones: 'Phone',
  websites: 'Website',
  socials: 'Social',
  addresses: 'Address',
  about: 'About',
}
const SCALARS: Scalar[] = ['full_name', 'title', 'organization', 'about']
const LISTS: List[] = ['emails', 'phones', 'websites', 'socials', 'addresses']

/** keep: leave as is. use: take the new value (or list). add: add the new items to the list. */
export type Choice = 'keep' | 'use' | 'add'

export interface Change {
  field: Field
  label: string
  list: boolean
  current: string[] // shown values
  proposed: string[]
  added: string[] // new items, for lists
  choices: Choice[]
  choice: Choice
}

const norm = (s: string) => s.normalize('NFKC').replace(/\s+/g, ' ').trim().toLowerCase()

function key(field: List, item: unknown): string {
  if (field === 'phones') return (item as Typed).value.replace(/\D/g, '')
  if (field === 'websites') return norm((item as Typed).value).replace(/^https?:\/\/(www\.)?/, '').replace(/\/$/, '')
  if (field === 'emails') return norm((item as Typed).value)
  if (field === 'socials') return `${norm((item as Social).platform)}|${norm((item as Social).handle).replace(/^@/, '')}`
  return norm(addressLine(item as PostalAddress))
}

/** The full identity of an item, type included, to tell "same value, new type" apart. */
function full(field: List, item: unknown): string {
  if (field === 'socials') return key(field, item)
  const kind = (item as { kind: string; label: string })
  return `${key(field, item)}|${kind.kind}|${norm(kind.label ?? '')}`
}

export function show(field: List, item: unknown): string {
  if (field === 'socials') {
    const s = item as Social
    return [s.platform, s.handle].filter(Boolean).join(' ')
  }
  if (field === 'addresses') {
    const a = item as PostalAddress
    return `${addressLine(a)} (${kindName('addresses', a)})`
  }
  const t = item as Typed
  return `${t.value} (${kindName(field, t)})`
}

export function changes(current: Contact, proposed: Proposed): Change[] {
  const out: Change[] = []
  for (const f of SCALARS) {
    const now = current[f] ?? ''
    const next = proposed[f] ?? ''
    if (!next.trim() || norm(now) === norm(next)) continue
    out.push({
      field: f, label: LABELS[f], list: false, current: now ? [now] : [], proposed: [next], added: [],
      choices: ['use', 'keep'], choice: 'use',
    })
  }
  for (const f of LISTS) {
    const now = (current[f] ?? []) as unknown[]
    const next = (proposed[f] ?? []) as unknown[]
    if (!next.length) continue
    const sameItems = now.length === next.length && now.every((x, i) => full(f, x) === full(f, next[i]))
    if (sameItems) continue
    const have = new Set(now.map((x) => key(f, x)))
    const added = next.filter((x) => !have.has(key(f, x)))
    const haveFull = new Set(now.map((x) => full(f, x)))
    const retyped = next.some((x) => have.has(key(f, x)) && !haveFull.has(full(f, x)))
    if (!added.length && !retyped) continue // nothing new, only fewer or reordered: keep
    // A reread address usually corrects the old one, so it replaces it by default; for
    // emails, phones and websites the default adds what's new and keeps what you had.
    const choices: Choice[] = !now.length || !added.length
      ? ['use', 'keep']
      : f === 'addresses' ? ['use', 'add', 'keep'] : ['add', 'use', 'keep']
    out.push({
      field: f, label: LABELS[f], list: true,
      current: now.map((x) => show(f, x)), proposed: next.map((x) => show(f, x)), added: added.map((x) => show(f, x)),
      choices, choice: choices[0],
    })
  }
  return out
}

/** The edit to save for the chosen changes. */
export function patchFor(current: Contact, proposed: Proposed, chosen: Change[]): Partial<Proposed> {
  const patch: Record<string, unknown> = {}
  for (const c of chosen) {
    if (c.choice === 'keep') continue
    if (!c.list) {
      patch[c.field] = proposed[c.field as Scalar]
      continue
    }
    const f = c.field as List
    const next = proposed[f] as unknown[]
    if (c.choice === 'use') patch[f] = next
    else {
      const now = current[f] as unknown[]
      const have = new Set(now.map((x) => key(f, x)))
      patch[f] = [...now, ...next.filter((x) => !have.has(key(f, x)))]
    }
  }
  return patch as Partial<Proposed>
}
