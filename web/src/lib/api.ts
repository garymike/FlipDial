// Typed calls to the FlipDial API. All values are rendered as text by the components.

export interface Social {
  platform: string
  handle: string
  url?: string
}

/** Platforms offered in the form (the server tidies names and builds profile links). */
export const PLATFORMS = [
  'Instagram', 'Facebook', 'X', 'TikTok', 'LinkedIn', 'Bluesky', 'Threads', 'Mastodon', 'YouTube',
  'Pinterest', 'Behance', 'Dribbble', 'Etsy', 'GitHub', 'Snapchat', 'WhatsApp', 'Signal', 'Telegram',
] as const

/** A phone, email or website with its type. Matches the types Apple and Google Contacts use. */
export interface Typed {
  value: string
  kind: string
  label: string // only when kind is 'custom'
}

export interface PostalAddress {
  street: string
  city: string
  region: string
  postal_code: string
  country: string
  kind: string
  label: string
}

export type TypedField = 'emails' | 'phones' | 'websites'

/** The types offered for each field, with the names shown. 'custom' lets you type a label. */
export const KINDS: Record<TypedField | 'addresses', [string, string][]> = {
  phones: [
    ['mobile', 'Mobile'], ['work', 'Work'], ['home', 'Home'], ['main', 'Main'], ['work_fax', 'Work fax'],
    ['home_fax', 'Home fax'], ['fax', 'Other fax'], ['pager', 'Pager'], ['other', 'Other'], ['custom', 'Custom…'],
  ],
  emails: [['work', 'Work'], ['home', 'Personal'], ['other', 'Other'], ['custom', 'Custom…']],
  websites: [
    ['work', 'Work'], ['home', 'Personal'], ['homepage', 'Homepage'], ['blog', 'Blog'], ['other', 'Other'],
    ['custom', 'Custom…'],
  ],
  addresses: [['work', 'Work'], ['home', 'Home'], ['other', 'Other'], ['custom', 'Custom…']],
}

/** The name to show for a value's type: its custom label, or the standard name. */
export function kindName(field: TypedField | 'addresses', item: { kind: string; label: string }): string {
  if (item.kind === 'custom') return item.label || 'Other'
  return KINDS[field].find(([k]) => k === item.kind)?.[1] ?? 'Other'
}

export const blankTyped = (kind = 'work'): Typed => ({ value: '', kind, label: '' })
export const blankAddress = (kind = 'work'): PostalAddress => ({
  street: '', city: '', region: '', postal_code: '', country: '', kind, label: '',
})

/** Drop empty rows before saving. */
export function cleanInput<T extends Pick<ContactInput, TypedField | 'addresses'>>(f: T): T {
  const keep = (t: Typed) => t.value.trim() !== ''
  return {
    ...f,
    emails: f.emails.filter(keep),
    phones: f.phones.filter(keep),
    websites: f.websites.filter(keep),
    addresses: f.addresses.filter((a) => [a.street, a.city, a.region, a.postal_code, a.country].some((x) => x.trim())),
  }
}

/** An address on one line, for lists and cards. */
export function addressLine(a: PostalAddress): string {
  const street = a.street.split('\n').map((x) => x.trim()).filter(Boolean).join(', ')
  const line2 = [a.region, a.postal_code].filter(Boolean).join(' ')
  return [street, a.city, line2, a.country].filter(Boolean).join(', ')
}

export interface Contact {
  uid: string
  full_name: string
  title: string
  organization: string
  department?: string
  given_name?: string
  middle_name?: string
  family_name?: string
  prefix?: string // Dr., Prof.
  suffix?: string // Jr., PhD
  nickname?: string
  birthday?: string // YYYY-MM-DD, or --MM-DD without a year
  emails: Typed[]
  phones: Typed[]
  websites: Typed[]
  socials: Social[]
  addresses: PostalAddress[]
  address: string // the first address on one line (read only)
  about: string
  note: string
  categories: string[]
  event: string
  met_on: string
  starred: boolean
  source: string
  card_id: string | null
  has_back: boolean
  card_view?: string // how the scan is shown: turns and swapped sides
  rev?: string // when the vCard last changed
  // Phone sync, only when it is turned on: on the phone or not, why, and the contact's own choice
  phone?: '' | 'on' | 'off'
  phone_why?: string // "contact", "tag:<name>" or "everything"
  phone_choice?: '' | 'on' | 'off'
}

export interface PhoneChange {
  uid: string
  name: string
}

/** Changes the phone sync is waiting for you to confirm. */
export interface PhonePending {
  token: string
  first: boolean
  add: PhoneChange[]
  update: number
  remove: PhoneChange[]
  gone: PhoneChange[]
  pull?: PhoneChange[]
}

export interface PhoneStatus {
  enabled: boolean
  book: string
  everything?: boolean
  tags?: Record<string, 'on' | 'off'>
  on_phone?: number
  wanted?: number
  last_run?: string | null
  last_success?: string | null
  problem?: { code: string; before?: number; now?: number } | null
  pending?: PhonePending | null
  check_hour?: number
  waiting?: number // in Review: added on the phone, or changed in both places
}

/** FlipDial's built-in contacts server. */
export interface BuiltinServer {
  available: boolean // false when a contacts server is set in the settings file
  on: boolean
  set_up: boolean
  running: boolean
  problem: string
  host: string
  port: number
  suggestions: { host: string; note: string }[]
  windows: boolean
  docker: boolean
}

/** The phone setup wizard's view of the contacts server. */
export interface PhoneSetupInfo {
  server: boolean
  server_kind: string
  server_name: string
  book: string
  book_from_settings_file: boolean
  book_url: string
  main_book: string
  books: string[]
  phone_username: string
  flipdial_username: string
  bundled: boolean // FlipDial's own contacts server: it can make the phone's account
  error: string
}

/** Something from the phone that needs a decision (shown at the top of Review). */
export interface PhoneInboxItem {
  id: number
  kind: 'added' | 'conflict'
  uid: string
  name: string
  fields: { field: string; phone: string; flipdial?: string }[]
}

export interface PhoneSyncResult {
  status: 'done' | 'confirm' | 'stopped' | 'busy'
  added?: number
  updated?: number
  removed?: number
  switched_off?: number
  from_phone?: number
  to_review?: number
  problem?: string
  state: PhoneStatus
}

/** "Read again" on a saved contact. `proposed` is only a suggestion until applied. */
export interface RereadState {
  status: 'none' | 'pending' | 'done' | 'failed'
  card_id: string
  error?: string | null
  error_detail?: string
  progress?: ReadProgress | null
  proposed?: import('./reread').Proposed | null
  flags?: string[]
}

/** One card a person gave you. A contact can have several (a new job, a new card). */
export interface Scan {
  card_id: string
  created_at: string
  has_back: boolean
  view?: string
}

/** A contact in Trash: off the contacts server, restorable until days_left runs out. */
export interface TrashItem {
  uid: string
  full_name: string
  organization: string
  card_id: string | null
  trashed_at: string
  days_left: number
}

/** Who is signed in, and where contacts are saved (for the icons in the reading pane). */
export interface Me {
  user: string
  mode: 'none' | 'oidc' | 'proxy'
  storage: 'server' | 'local'
  server_kind?: '' | 'icloud' | 'google' | 'synology' | 'server'
  server_name?: string
  last_backup?: string // when the last FlipDial backup was made
}

export interface ContactList {
  contacts: Contact[]
  total: number
  starred: number
  with_scan: number
  trashed?: number
  decks: { name: string; count: number }[]
}

export interface Field {
  value: string
  confidence: number
  kind?: string
}

export interface ReviewFields {
  full_name: Field
  given_name?: Field
  middle_name?: Field
  family_name?: Field
  prefix?: Field
  suffix?: Field
  title: Field
  organization: Field
  department?: Field
  emails: Field[]
  phones: Field[]
  websites: Field[]
  socials: (Social & { confidence: number })[]
  address: Field
  address_parts?: Omit<PostalAddress, 'kind' | 'label'>
  about?: Field
  text?: string
}

export interface ReviewItem {
  card_id: string
  status: 'review' | 'extract_pending' | 'extract_failed'
  created_at: string
  has_back: boolean
  fields: ReviewFields | null
  flags: string[]
  error: string | null
  error_detail?: string
  progress?: ReadProgress | null
  view?: string
}

export interface ReadProgress {
  stage: 'waiting' | 'reading' | 'checking'
  seconds: number
  fields: Partial<Record<'full_name' | 'title' | 'organization' | 'address' | 'about', string>> &
    Partial<Record<'emails' | 'phones' | 'websites' | 'text', string[]>>
}

export type ContactInput = Omit<Contact, 'uid' | 'categories' | 'source' | 'card_id' | 'has_back' | 'address'> & {
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

export type ImportField =
  | ''
  | 'full_name'
  | 'given_name'
  | 'middle_name'
  | 'family_name'
  | 'prefix'
  | 'suffix'
  | 'nickname'
  | 'organization'
  | 'department'
  | 'title'
  | 'email'
  | 'phone'
  | 'website'
  | 'linkedin'
  | 'address'
  | 'met_on'
  | 'birthday'
  | 'tags'
  | 'note'

export interface ImportOptions {
  text: string
  kind?: 'auto' | 'vcf' | 'csv'
  mapping?: ImportField[]
  deck?: string
  include_duplicates?: boolean
  update?: boolean // update contacts already in FlipDial (adds values, never removes)
  prefer_file?: boolean // when both have a different value, use the file's
}

export interface ImportCounts {
  total: number
  new: number
  update?: number // already in FlipDial, with something new to add
  same?: number // already in FlipDial, nothing new
  duplicate: number
  invalid: number
}

export interface ImportPreview {
  kind: 'vcf' | 'csv'
  format: 'vcard' | 'linkedin' | 'google' | 'outlook' | 'csv'
  headers?: string[]
  mapping?: ImportField[]
  counts: ImportCounts
  rows: {
    row: number
    name: string
    organization: string
    email: string
    status: 'new' | 'update' | 'same' | 'duplicate' | 'invalid'
    reason: string
    changes?: string[]
  }[]
}

export interface ImportRecord {
  id: number
  created_at: string
  format: string
  counts: ImportCounts & { created: number; updated?: number; unchanged?: number; skipped: number; failed: number }
  undone: boolean
}

export interface SetupItem {
  id: string
  label: string
  state: 'ok' | 'warn' | 'fail'
  detail: string
  fix: string
  action?: 'push_local'
  action_label?: string
}

export interface SetupStatus {
  state: 'ok' | 'warn' | 'fail'
  items: SetupItem[]
}

export interface UpdateInfo {
  current: string
  enabled: boolean
  available: boolean
  release: { tag: string; name: string; url: string; published_at: string } | null
  install: string
  can_update: boolean
  error?: string // check_failed: GitHub couldn't be reached
}

export interface AuditEntry {
  id: number
  ts: string
  actor: string
  action: string
  target: string
  detail: Record<string, unknown>
}

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super(code)
  }
}

/** True in the GitHub Pages demo build, where an in-browser stand-in replaces the server. */
export const DEMO = import.meta.env.MODE === 'demo'

const urls = {
  image: (cardId: string, side: 'front' | 'back' | 'thumb') => `/api/cards/${cardId}/image/${side}`,
  original: (cardId: string, role: 'front' | 'back' | 'scan') => `/api/cards/${cardId}/original/${role}`,
  exportUrl: (kind: 'vcf' | 'csv' | 'backup') =>
    kind === 'backup' ? '/api/export/backup' : `/api/export/contacts.${kind}`,
}

/** Demo mode swaps in its own image and download addresses. */
export function setUrls(next: typeof urls): void {
  Object.assign(urls, next)
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (DEMO) return (await (await import('./demo')).handle(method, path, body)) as T
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-FlipDial-Request'] = '1'
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  })
  if (res.status === 401) {
    // Signed out or session expired: go to sign-in and come back to this screen.
    location.assign(`/auth/login?next=${encodeURIComponent(location.hash || '#/wall')}`)
    throw new ApiError(401, 'sign_in_required')
  }
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
  phone: () => call<PhoneStatus>('GET', '/api/phone'),
  phoneRule: (name: string, state: 'on' | 'off' | 'follow') =>
    call<PhoneStatus>('PUT', '/api/phone/rules', { name, state }),
  phoneSync: (body: { confirm?: string; accept_drop?: boolean } = {}) =>
    call<PhoneSyncResult>('POST', '/api/phone/sync', body),
  builtinServer: () => call<BuiltinServer>('GET', '/api/contacts-server'),
  builtinServerOn: (host: string) => call<BuiltinServer>('POST', '/api/contacts-server/on', { host }),
  builtinServerOff: () => call<BuiltinServer>('POST', '/api/contacts-server/off'),
  phoneSetup: () => call<PhoneSetupInfo>('GET', '/api/phone/setup'),
  phoneSetupBook: (name: string, create: boolean) =>
    call<PhoneSetupInfo>('POST', '/api/phone/setup/book', { name, create }),
  phoneSetupAccount: () =>
    call<{ username: string; password: string; book: string }>('POST', '/api/phone/setup/account'),
  phoneSetupOff: () => call<{ enabled: false }>('DELETE', '/api/phone/setup/book'),
  phoneSetupUsername: (username: string) => call<{ username: string }>('PUT', '/api/phone/setup/username', { username }),
  phoneSetupTest: (username: string, password: string) =>
    call<{ books: string[]; sees_phone_book: boolean; sees_main_book: boolean }>('POST', '/api/phone/setup/test', {
      username,
      password,
    }),
  phoneProfileLink: (base: string) =>
    call<{ url: string; expires_at: string; qr_svg: string }>('POST', '/api/phone/profile-link', { base }),
  phoneInbox: () => call<{ items: PhoneInboxItem[] }>('GET', '/api/phone/inbox'),
  phoneInboxAction: (id: number, action: 'accept' | 'dismiss') =>
    call<{ uid: string }>('POST', `/api/phone/inbox/${id}/${action}`),
  phoneUndo: (id: number) => call<{ uid: string }>('POST', `/api/phone/undo/${id}`),
  contactPhone: (uid: string, state: 'on' | 'off' | 'follow') =>
    call<Contact>('PUT', `/api/contacts/${encodeURIComponent(uid)}/phone`, { state }),
  update: (uid: string, changes: Partial<ContactInput> & { card_id?: string }) =>
    call<Contact>('PATCH', `/api/contacts/${encodeURIComponent(uid)}`, changes),
  reread: (uid: string) => call<RereadState>('POST', `/api/contacts/${encodeURIComponent(uid)}/reread`),
  rereadState: (uid: string) => call<RereadState>('GET', `/api/contacts/${encodeURIComponent(uid)}/reread`),
  rereadDiscard: (uid: string) => call('DELETE', `/api/contacts/${encodeURIComponent(uid)}/reread`),
  trash: (uid: string) => call<{ uid: string; days: number }>('POST', `/api/contacts/${encodeURIComponent(uid)}/trash`),
  trashList: () => call<{ items: TrashItem[]; days: number }>('GET', '/api/trash'),
  restoreTrash: (uid: string) => call<Contact>('POST', `/api/trash/${encodeURIComponent(uid)}/restore`),
  deleteForever: (uid: string) => call('DELETE', `/api/trash/${encodeURIComponent(uid)}`),
  scans: (uid: string) => call<{ scans: Scan[] }>('GET', `/api/contacts/${encodeURIComponent(uid)}/scans`),
  sync: () => call<Record<string, number>>('POST', '/api/sync'),
  review: () => call<{ items: ReviewItem[]; ready: number; from_phone?: number }>('GET', '/api/review'),
  approve: (cardId: string, input: ContactInput) =>
    call<Contact & { uid: string }>('POST', `/api/review/${cardId}/approve`, input),
  dismiss: (cardId: string) => call('POST', `/api/review/${cardId}/dismiss`),
  /** The back is a different card: make it its own card. Both are read again. */
  split: (cardId: string) =>
    call<{ card_id: string; new_card_id: string }>('POST', `/api/review/${cardId}/split`),
  duplicates: () => call<{ pairs: DuplicatePair[]; count: number }>('GET', '/api/duplicates'),
  notDuplicates: (uid_a: string, uid_b: string) =>
    call('POST', '/api/duplicates/dismiss', { uid_a, uid_b }),
  merge: (keep_uid: string, drop_uid: string, contact: ContactInput, show_card = '') =>
    call<{ contact: Contact; merge_id: number }>('POST', '/api/merge', { keep_uid, drop_uid, contact, show_card }),
  undoMerge: (id: number) => call<{ restored: string[] }>('POST', `/api/merge/${id}/undo`),
  merges: () => call<{ merges: MergeRecord[] }>('GET', '/api/merges'),
  matches: (cardId: string) => call<{ matches: Match[] }>('GET', `/api/review/${cardId}/matches`),
  attach: (cardId: string, uid: string, input: ContactInput) =>
    call<Contact>('POST', `/api/review/${cardId}/attach/${encodeURIComponent(uid)}`, input),
  importPreview: (o: ImportOptions) => call<ImportPreview>('POST', '/api/import/preview', o),
  importRun: (o: ImportOptions) =>
    call<{ import_id: number; format: string; counts: ImportRecord['counts'] }>('POST', '/api/import', o),
  imports: () => call<{ imports: ImportRecord[] }>('GET', '/api/imports'),
  undoImport: (id: number) => call<{ removed: number; restored?: number; kept_edited: number }>('POST', `/api/imports/${id}/undo`),
  exportUrl: (kind: 'vcf' | 'csv' | 'backup') => urls.exportUrl(kind),
  changesInfo: () =>
    call<{ since: string; count: number; phone_sync: boolean; count_phone?: number }>('GET', '/api/export/changes'),
  changesUrl: (onlyPhone: boolean) =>
    DEMO ? '#/transfer' : `/api/export/changes.vcf${onlyPhone ? '?only_phone=true' : ''}`,
  forget: (uid: string) =>
    call<{ forgotten: string; scans: number }>('DELETE', `/api/contacts/${encodeURIComponent(uid)}`),
  updateInfo: () => call<UpdateInfo>('GET', '/api/update'),
  checkUpdate: () => call<UpdateInfo>('POST', '/api/update/check'),
  startUpdate: () => call<{ updating_to: string }>('POST', '/api/update/start'),
  status: () => call<SetupStatus>('GET', '/api/status'),
  retry: (cardId: string) => call<{ retrying: number }>('POST', `/api/review/${cardId}/retry`),
  dismissedCards: () =>
    call<{ items: { card_id: string; created_at: string; label: string; view?: string }[] }>(
      'GET',
      '/api/review/dismissed',
    ),
  restoreCard: (cardId: string) => call<{ status: string }>('POST', `/api/review/${cardId}/restore`),
  deleteCard: (cardId: string) => call<{ deleted: string }>('DELETE', `/api/review/${cardId}`),
  retryAll: () => call<{ retrying: number }>('POST', '/api/review/retry'),
  me: () => call<Me>('GET', '/api/me'),
  pushLocal: () =>
    call<{ copied: number; already_there: number; failed: number }>('POST', '/api/contacts/push-local'),
  logout: () => call<{ signed_out: boolean }>('POST', '/api/logout'),
  audit: (before?: number) =>
    call<{ entries: AuditEntry[] }>('GET', `/api/audit${before ? `?before=${before}` : ''}`),
  auditVerify: () =>
    call<{ ok: boolean; entries: number; broken_at: number | null; head: string }>('GET', '/api/audit/verify'),
  // `view` (turns, swapped sides) is in the address so a changed card is never shown from cache.
  image: (cardId: string, side: 'front' | 'back' | 'thumb', view = '') =>
    urls.image(cardId, side) + (view && !DEMO ? `?v=${encodeURIComponent(view)}` : ''),
  cardView: (cardId: string, change: { swap?: boolean; turn?: 'front' | 'back' }) =>
    call<{ view: string }>('POST', `/api/cards/${cardId}/view`, change),
  original: (cardId: string, role: 'front' | 'back' | 'scan') => urls.original(cardId, role),
}

/** Plain-language reasons two contacts look alike. */
export const REASONS: Record<string, string> = {
  same_email: 'Same email',
  same_phone: 'Same phone',
  same_name: 'Same name',
  similar_name: 'Similar name',
  same_company: 'Same company',
}

/** Why a card couldn't be read, in plain words. */
export const READ_ERRORS: Record<string, string> = {
  model_unreachable: "Couldn't reach Ollama. Is it running?",
  model_disconnected: 'Ollama stopped answering partway, often while loading the model. Read again usually works.',
  model_cannot_load: "Ollama couldn't load this model. Choose another vision model (see the setup check).",
  model_not_installed: "The card-reading model isn't installed in Ollama.",
  model_not_vision: "The chosen model can't read images.",
  model_timeout: 'Reading took too long.',
  model_error: 'The model reported an error.',
  image_missing: 'The scan image is missing.',
  unexpected_response: "The model's answer couldn't be used.",
  response_not_json: "The model's answer couldn't be used.",
  response_not_object: "The model's answer couldn't be used.",
  response_too_large: "The model's answer was too long.",
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
    already_undone: 'That was already undone.',
    same_contact: 'Pick two different contacts.',
    file_too_large: 'That file is too large (10 MB limit). Split it and import the parts.',
    too_many_rows: 'That file has too many rows (10,000 limit).',
    too_many_cards: 'That file has too many contacts (10,000 limit).',
    no_contacts_found: 'No contacts were found in that file.',
    empty_file: 'That file is empty.',
    phone_sync_off: 'Phone sync is not set up. See Setup.',
    changed_on_phone_again: 'It changed on the phone again. Sync, then decide on the newest version.',
    too_old: 'That is more than 30 days old and can no longer be undone.',
    invalid_contact: "That contact can't be saved: it has no usable name.",
    cannot_create_book: "The contacts server didn't let FlipDial make the address book. Make it on the server, then pick it here.",
    book_exists: 'An address book with that name is already there. Pick it from the list instead.',
    set_in_settings_file: 'The phone book is set in the settings file (FLIPDIAL_PHONE_ADDRESSBOOK). Change it there.',
    username_required: "Enter the phone's user name first.",
    no_bundled_server: "FlipDial's own contacts server isn't set up here.",
    port_in_use: 'Something else on this computer is already using port 5232. Stop it, or set up that server in the settings file instead.',
    bad_address: 'Enter just a name or address, like 192.168.1.20 or mycomputer.local.',
    server_in_settings_file: 'A contacts server is set in the settings file, so the built-in one is not used.',
    name_required: 'Enter a name.',
    demo_readonly: 'That is turned off in the demo. Install FlipDial to use it with your own contacts.',
    not_supported: 'This install updates differently. See the release notes.',
    no_update: 'You already have the newest version.',
    launch_failed: "The update couldn't be started. Run update.cmd instead.",
    updater_missing: "FlipDial's update script couldn't be found. Run update.cmd instead.",
    not_failed: 'That card is already being read.',
    cannot_reread: 'That card is already being read, or was already saved.',
    not_dismissed: 'That card is already back in Review.',
    cannot_delete: 'Saved cards are removed with Forget on the contact page.',
    bad_mapping: 'The column choices do not match the file. Pick the file again.',
    no_back: 'This card has no back to swap with.',
    no_scan: "This contact has no scanned card to read.",
    not_this_contacts_card: "That card isn't linked to this contact.",
    not_found: "That contact isn't in your address book any more. It may have been deleted or merged.",
    unknown_card: "That card isn't in FlipDial any more.",
    changed_on_server: 'This contact was changed on the contacts server. Reload it and try again.',
    already_exists: 'A contact with that ID already exists on the contacts server.',
    address_book_not_found: "The address book in your settings wasn't found on the contacts server.",
    phone_book_is_main_book: "That's your main address book. The phone needs a separate one.",
    no_address_book: 'No address book was found on the contacts server.',
    put_failed: "The contacts server didn't accept the change. Try again in a moment.",
    get_failed: "The contacts server didn't return the contact. Try again in a moment.",
    delete_failed: "The contacts server didn't delete the contact. Try again in a moment.",
    propfind_failed: "The contacts server didn't list the address book. Check the address in Setup.",
    not_allowed: "You don't have permission to do that.",
    sign_in_required: 'Your sign-in has ended. Reload the page to sign in again.',
    unsupported_format: "FlipDial can't read that kind of file. Use a .vcf or .csv file.",
    not_a_vcard: "That file doesn't look like a vCard (.vcf).",
    vcard_too_large: 'One of the contacts in that file is too large to import.',
    unreadable: "That file couldn't be read. Save it again as UTF-8 and retry.",
    too_large: 'That file is too large.',
    empty: 'That file is empty.',
    not_a_backup: "That file isn't a FlipDial backup.",
    http_422: "Some values weren't accepted. Check them and try again.",
    http_413: 'That is too large to send.',
    http_429: 'Too many requests at once. Wait a moment and try again.',
  }
  if (messages[code]) return messages[code]
  if (err instanceof ApiError && err.status >= 500) return 'FlipDial hit an error. Try again; if it keeps happening, the details are in the server log.'
  return `Something went wrong (${code}).`
}
