// Typed calls to the FlipDial API. All values are rendered as text by the components.

export interface Social {
  platform: string
  handle: string
}

export interface Contact {
  uid: string
  full_name: string
  title: string
  organization: string
  emails: string[]
  phones: string[]
  websites: string[]
  socials: Social[]
  address: string
  categories: string[]
  event: string
  met_on: string
  starred: boolean
  source: string
  card_id: string | null
  has_back: boolean
}

export interface ContactList {
  contacts: Contact[]
  total: number
  starred: number
  with_scan: number
  decks: { name: string; count: number }[]
}

export interface Field {
  value: string
  confidence: number
}

export interface ReviewFields {
  full_name: Field
  title: Field
  organization: Field
  emails: Field[]
  phones: Field[]
  websites: Field[]
  socials: (Social & { confidence: number })[]
  address: Field
}

export interface ReviewItem {
  card_id: string
  status: 'review' | 'extract_pending' | 'extract_failed'
  created_at: string
  has_back: boolean
  fields: ReviewFields | null
  flags: string[]
  error: string | null
}

export type ContactInput = Omit<Contact, 'uid' | 'categories' | 'source' | 'card_id' | 'has_back'> & {
  tags: string[]
}

export interface DuplicatePair {
  score: number
  reasons: string[]
  a: Contact
  b: Contact
}

export interface MergeRecord {
  id: number
  keep_uid: string
  drop_uid: string
  drop_name: string
  created_at: string
  undone: boolean
}

export interface Match {
  score: number
  reasons: string[]
  contact: Contact
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code)
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-FlipDial-Request'] = '1'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  if (!res.ok) {
    let code = `http_${res.status}`
    try {
      const data = await res.json()
      if (typeof data.detail === 'string') code = data.detail
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, code)
  }
  return (await res.json()) as T
}

export interface ListQuery {
  q?: string
  deck?: string
  scan?: 'all' | 'yes' | 'no'
  starred?: boolean
}

export const api = {
  contacts(query: ListQuery = {}): Promise<ContactList> {
    const p = new URLSearchParams()
    if (query.q) p.set('q', query.q)
    if (query.deck) p.set('deck', query.deck)
    if (query.scan && query.scan !== 'all') p.set('scan', query.scan)
    if (query.starred) p.set('starred', 'true')
    const qs = p.toString()
    return call('GET', `/api/contacts${qs ? `?${qs}` : ''}`)
  },
  contact: (uid: string) => call<Contact>('GET', `/api/contacts/${encodeURIComponent(uid)}`),
  update: (uid: string, changes: Partial<ContactInput>) =>
    call<Contact>('PATCH', `/api/contacts/${encodeURIComponent(uid)}`, changes),
  sync: () => call<Record<string, number>>('POST', '/api/sync'),
  review: () => call<{ items: ReviewItem[]; ready: number }>('GET', '/api/review'),
  approve: (cardId: string, input: ContactInput) =>
    call<Contact & { uid: string }>('POST', `/api/review/${cardId}/approve`, input),
  dismiss: (cardId: string) => call('POST', `/api/review/${cardId}/dismiss`),
  duplicates: () => call<{ pairs: DuplicatePair[]; count: number }>('GET', '/api/duplicates'),
  notDuplicates: (uid_a: string, uid_b: string) =>
    call('POST', '/api/duplicates/dismiss', { uid_a, uid_b }),
  merge: (keep_uid: string, drop_uid: string, contact: ContactInput) =>
    call<{ contact: Contact; merge_id: number }>('POST', '/api/merge', { keep_uid, drop_uid, contact }),
  undoMerge: (id: number) => call<{ restored: string[] }>('POST', `/api/merge/${id}/undo`),
  merges: () => call<{ merges: MergeRecord[] }>('GET', '/api/merges'),
  matches: (cardId: string) => call<{ matches: Match[] }>('GET', `/api/review/${cardId}/matches`),
  attach: (cardId: string, uid: string, input: ContactInput) =>
    call<Contact>('POST', `/api/review/${cardId}/attach/${encodeURIComponent(uid)}`, input),
  image: (cardId: string, side: 'front' | 'back' | 'thumb') => `/api/cards/${cardId}/image/${side}`,
  original: (cardId: string, role: 'front' | 'back' | 'scan') =>
    `/api/cards/${cardId}/original/${role}`,
}

/** Plain-language reasons two contacts look alike. */
export const REASONS: Record<string, string> = {
  same_email: 'Same email',
  same_phone: 'Same phone',
  same_name: 'Same name',
  similar_name: 'Similar name',
  same_company: 'Same company',
}

/** Plain-language messages for error codes. */
export function describe(err: unknown): string {
  const code = err instanceof ApiError ? err.code : 'network'
  const messages: Record<string, string> = {
    changed_elsewhere: 'This contact was changed on another device. Reload it and try again.',
    carddav_not_configured: 'No contacts server is set up yet.',
    server_unreachable: 'The contacts server could not be reached.',
    auth_failed: 'The contacts server did not accept the sign-in.',
    not_in_review: 'This card was already handled.',
    csrf_check_failed: 'The request was blocked. Reload the page and try again.',
    network: 'FlipDial could not be reached.',
    already_undone: 'That merge was already undone.',
    same_contact: 'Pick two different contacts.',
  }
  return messages[code] ?? `Something went wrong (${code}).`
}
