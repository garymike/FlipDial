<script lang="ts">
  import { untrack } from 'svelte'
  import {
    api,
    cleanInput,
    describe,
    kindName,
    READ_ERRORS,
    type Contact,
    type ContactInput,
    type RereadState,
    type Scan,
  } from './api'
  import { changes, patchFor, type Change } from './reread'
  import ContactForm from './ContactForm.svelte'
  import FlipCard from './FlipCard.svelte'
  import ScanImage from './ScanImage.svelte'
  import Star from './Star.svelte'

  // The reading pane: one contact's card, details and notes, edited in place.
  // Used beside the Wall and the Dial. Pass `initial` when the list already has the contact,
  // so it shows at once; it is fetched otherwise (a link straight to a contact).
  let {
    uid,
    initial = null,
    showCard = true,
    onclose,
    onchange,
    onforget,
  }: {
    uid: string
    initial?: Contact | null
    showCard?: boolean
    onclose?: () => void
    onchange?: (c: Contact) => void
    onforget?: (uid: string) => void
  } = $props()

  let contact = $state<Contact | null>(null)
  let flipped = $state(false)
  let editing = $state(false)
  let form = $state<ContactInput | null>(null)
  let error = $state('')
  let saving = $state(false)
  let confirming = $state(false)

  $effect(() => {
    const id = uid
    const given = untrack(() => initial)
    flipped = false
    editing = false
    confirming = false
    error = ''
    if (given && given.uid === id) {
      contact = given
      return
    }
    contact = null
    api
      .contact(id)
      .then((c) => {
        if (id === uid) contact = c
      })
      .catch((e) => {
        if (id === uid) error = describe(e)
      })
  })

  // Every card this person has given you. One is shown on the contact; the others can be
  // looked at here, and any of them made the one shown.
  let scans = $state<Scan[]>([])
  let viewing = $state<string | null>(null)
  $effect(() => {
    const id = contact?.uid
    const hasScan = !!contact?.card_id
    untrack(() => {
      scans = []
      viewing = null
    })
    if (!id || !hasScan) return
    api
      .scans(id)
      .then((r) => {
        if (contact?.uid === id) scans = r.scans
      })
      .catch(() => (scans = []))
  })
  const shown = $derived.by(() => {
    if (!contact) return null
    const v = viewing && scans.find((x) => x.card_id === viewing)
    return v ? { ...contact, card_id: v.card_id, has_back: v.has_back } : contact
  })

  async function useCard(cardId: string) {
    if (!contact) return
    try {
      contact = await api.update(contact.uid, { card_id: cardId })
      viewing = null
      onchange?.(contact)
    } catch (e) {
      error = describe(e)
    }
  }

  // "Read again": read the card once more and propose what changed. Nothing is saved until
  // the person applies the changes they pick.
  let rr = $state<RereadState | null>(null)
  let picks = $state<Change[]>([])
  let applying = $state(false)
  $effect(() => {
    const id = contact?.uid
    const hasScan = !!contact?.card_id
    untrack(() => {
      rr = null
      picks = []
    })
    if (!id || !hasScan) return
    api.rereadState(id).then((s) => {
      if (contact?.uid === id) setReread(s)
    }).catch(() => {})
  })
  function setReread(s: RereadState) {
    rr = s
    picks = s.status === 'done' && s.proposed && contact ? changes(contact, s.proposed) : []
  }
  // While it reads, check every two seconds.
  $effect(() => {
    if (rr?.status !== 'pending' || !contact) return
    const id = contact.uid
    const timer = setInterval(() => {
      api.rereadState(id).then((s) => {
        if (contact?.uid === id) setReread(s)
      }).catch(() => {})
    }, 2000)
    return () => clearInterval(timer)
  })
  async function readAgain() {
    if (!contact) return
    try {
      setReread(await api.reread(contact.uid))
    } catch (e) {
      error = describe(e)
    }
  }
  async function dropReread() {
    if (!contact) return
    try {
      await api.rereadDiscard(contact.uid)
    } catch {
      /* already gone */
    }
    rr = { status: 'none', card_id: rr?.card_id ?? '' }
    picks = []
  }
  async function applyReread() {
    if (!contact || !rr?.proposed) return
    applying = true
    try {
      const patch = patchFor(contact, rr.proposed, picks)
      if (Object.keys(patch).length) {
        contact = await api.update(contact.uid, patch)
        onchange?.(contact)
      }
      await dropReread()
    } catch (e) {
      error = describe(e)
    } finally {
      applying = false
    }
  }
  const CHOICE_NAMES = { use: 'Use new', add: 'Add the new ones', keep: 'Keep current' } as const
  const STAGE_NAMES: Record<string, string> = {
    waiting: 'Starting the model',
    reading: 'Reading the card',
    checking: 'Checking what was read',
  }

  // A star toggled on the Wall shows here too.
  $effect(() => {
    const i = initial
    if (!i) return
    const starred = i.starred
    untrack(() => {
      if (contact && contact.uid === i.uid && contact.starred !== starred) contact = { ...contact, starred }
    })
  })

  function startEdit() {
    if (!contact) return
    const { full_name, title, organization, emails, phones, websites, socials, addresses, about, note, event, met_on, starred } =
      contact
    form = {
      full_name, title, organization, about, note, event, met_on, starred,
      emails: emails.map((t) => ({ ...t })), phones: phones.map((t) => ({ ...t })), websites: websites.map((t) => ({ ...t })),
      addresses: addresses.map((a) => ({ ...a })),
      socials: socials.map((s) => ({ ...s })),
      tags: contact.categories.filter((c) => c !== contact?.event),
    }
    editing = true
  }

  async function save() {
    if (!form || !contact) return
    saving = true
    try {
      contact = await api.update(contact.uid, cleanInput(form))
      onchange?.(contact)
      editing = false
      error = ''
    } catch (e) {
      error = describe(e)
    } finally {
      saving = false
    }
  }

  async function toggleStar() {
    if (!contact) return
    try {
      contact = await api.update(contact.uid, { starred: !contact.starred })
      onchange?.(contact)
    } catch (e) {
      error = describe(e)
    }
  }

  let forgetting = $state(false)
  async function forgetContact() {
    if (!contact) return
    forgetting = true
    try {
      await api.forget(contact.uid)
      forgetting = false
      confirming = false
      onforget?.(contact.uid)
    } catch (e) {
      error = describe(e)
      forgetting = false
    }
  }

  let storage = $state<'server' | 'local'>('server')
  $effect(() => {
    api.me().then((m) => (storage = m.storage)).catch(() => {})
  })

  const safeUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : `https://${u}`)
</script>

<article class="pane" aria-label={contact ? `Contact: ${contact.full_name}` : 'Contact'}>
  {#if onclose}
    <button type="button" class="close" aria-label="Close" onclick={onclose}>
      <span class="phone-only">← Back</span><span class="wide-only" aria-hidden="true">×</span>
    </button>
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if !contact && !error}<p class="loading">Loading…</p>{/if}

  {#if contact}
    <div class="head">
      <div>
        <h1>{contact.full_name}</h1>
        <p class="sub">{[contact.title, contact.organization].filter(Boolean).join(', ')}</p>
      </div>
      <div class="headbtns">
        <Star on={contact.starred} label={contact.starred ? 'Unstar' : 'Star'} onclick={toggleStar} />
        {#if !editing}<button type="button" class="secondary" onclick={startEdit}>Edit</button>{/if}
      </div>
    </div>

    {#if showCard && shown}
      <section class="card" aria-label="Card">
        <button type="button" class="tile" aria-label={flipped ? 'Show the front' : 'Show the back'} onclick={() => (flipped = !flipped)}>
          <FlipCard contact={shown} {flipped} size="large" />
        </button>
        {#if shown.card_id}<p class="fliphint">Click the card to flip it.</p>{/if}
        {#if viewing && viewing !== contact.card_id}
          <div class="older">
            <span>You're looking at another of their cards.</span>
            <button type="button" class="secondary" onclick={() => viewing && useCard(viewing)}>Show this one on the contact</button>
          </div>
        {/if}
      </section>
    {/if}
    {#if contact.card_id && !editing}
      <section class="reread" aria-label="Read the card again" aria-live="polite">
        {#if !rr || rr.status === 'none'}
          <button type="button" class="secondary small" onclick={readAgain}>Read again</button>
          <span class="hint">Reads the card once more and shows what changed. Nothing is saved until you choose.</span>
        {:else if rr.status === 'pending'}
          <span class="dot" aria-hidden="true"></span>
          <span>{STAGE_NAMES[rr.progress?.stage ?? 'waiting'] ?? 'Reading the card'}…{#if rr.progress?.seconds} {Math.round(rr.progress.seconds)}s{/if}</span>
          <button type="button" class="link" onclick={dropReread}>Cancel</button>
        {:else if rr.status === 'failed'}
          <span class="bad">{READ_ERRORS[rr.error ?? ''] ?? "The card couldn't be read again."}</span>
          <button type="button" class="secondary small" onclick={readAgain}>Try again</button>
          <button type="button" class="link" onclick={dropReread}>Dismiss</button>
        {:else if !picks.length}
          <span>Read again: nothing new on the card.</span>
          <button type="button" class="link" onclick={dropReread}>OK</button>
        {:else}
          <div class="proposal">
            <h2>The card reads differently now</h2>
            <p class="hint">Pick what to use. Your notes, deck and star aren't touched.</p>
            {#each picks as c, i (c.field)}
              <fieldset>
                <legend>{c.label}</legend>
                <div class="cmp">
                  <span class="k">Now</span>
                  <span class="v">{#if c.current.length}{#each c.current as v, j (j)}<span>{v}</span>{/each}{:else}<em>Empty</em>{/if}</span>
                  <span class="k">Card</span>
                  <span class="v new">{#each c.proposed as v, j (j)}<span class:added={c.added.includes(v)}>{v}</span>{/each}</span>
                </div>
                <div class="choices" role="radiogroup" aria-label={`${c.label}: what to keep`}>
                  {#each c.choices as ch (ch)}
                    <label><input type="radio" name={`rr-${c.field}`} value={ch} bind:group={picks[i].choice} /> {CHOICE_NAMES[ch]}</label>
                  {/each}
                </div>
              </fieldset>
            {/each}
            <div class="buttons">
              <button type="button" class="secondary" onclick={dropReread}>Discard</button>
              <button type="button" class="primary" onclick={applyReread} disabled={applying}>
                {applying ? 'Saving…' : `Apply ${picks.filter((p) => p.choice !== 'keep').length} change${picks.filter((p) => p.choice !== 'keep').length === 1 ? '' : 's'}`}
              </button>
            </div>
          </div>
        {/if}
      </section>
    {/if}
    {#if scans.length > 1}
      <section class="history" aria-label="Their cards">
        <h2>Cards they've given you ({scans.length})</h2>
        <div class="thumbs">
          {#each scans as sc (sc.card_id)}
            {@const current = (viewing ?? contact.card_id) === sc.card_id}
            <button
              type="button"
              class="thumb"
              aria-pressed={current}
              aria-label={`${sc.card_id === contact.card_id ? 'Card shown on the contact' : 'Another card'}${sc.created_at ? `, scanned ${sc.created_at.slice(0, 10)}` : ''}`}
              onclick={() => {
                viewing = sc.card_id === contact?.card_id ? null : sc.card_id
                flipped = false
              }}
            >
              <ScanImage src={api.image(sc.card_id, 'thumb')} fit="fill" />
              {#if sc.card_id === contact.card_id}<span class="tag">Shown</span>{/if}
            </button>
          {/each}
        </div>
      </section>
    {/if}

      <section class="info" aria-label="Details">

        {#if editing && form}
          <ContactForm bind:value={form} idPrefix="edit" />
          <div class="buttons">
            <button type="button" class="secondary" onclick={() => (editing = false)}>Cancel</button>
            <button type="button" class="primary" onclick={save} disabled={saving || !form.full_name.trim()}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        {:else}
          <dl>
            {#each contact.emails as e, i (i)}
              <dt>Email <span class="kind">{kindName('emails', e)}</span></dt><dd><a href={`mailto:${e.value}`}>{e.value}</a></dd>
            {/each}
            {#each contact.phones as p, i (i)}
              <dt>Phone <span class="kind">{kindName('phones', p)}</span></dt>
              <dd><a href={`tel:${p.value.replace(/[^\d+]/g, '')}`}>{p.value}</a></dd>
            {/each}
            {#each contact.websites as w, i (i)}
              <dt>Website <span class="kind">{kindName('websites', w)}</span></dt>
              <dd><a href={safeUrl(w.value)} rel="noopener noreferrer" target="_blank">{w.value}</a></dd>
            {/each}
            {#each contact.socials as s (s.platform + s.handle)}
              <dt>{s.platform || 'Social'}</dt>
              <dd>{#if s.url}<a href={s.url} rel="noopener noreferrer" target="_blank">{s.handle}</a>{:else}{s.handle}{/if}</dd>
            {/each}
            {#each contact.addresses as a, i (i)}
              <dt>Address <span class="kind">{kindName('addresses', a)}</span></dt>
              <dd class="multiline">{[a.street, [a.city, [a.region, a.postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', '), a.country].filter(Boolean).join('\n')}</dd>
            {/each}
            {#if contact.about}<dt>About</dt><dd class="multiline">{contact.about}</dd>{/if}
            {#if contact.note}<dt>Notes</dt><dd class="multiline">{contact.note}</dd>{/if}
            <dt>Met at</dt><dd>{contact.event || 'Not set'}</dd>
            <dt>Met on</dt><dd>{contact.met_on || 'Not set'}</dd>
          </dl>
          {#if contact.categories.length}
            <ul class="tags">{#each contact.categories as t (t)}<li>{t}</li>{/each}</ul>
          {/if}
          <div class="panel">
            <span class="badge" aria-hidden="true">S</span>
            {storage === 'local' ? 'Saved on this computer (no contacts server set up yet)' : 'Saved to your contacts server'}
          </div>
          {#if contact.card_id}
            <div class="originals">
              <h2>Original scans, never modified</h2>
              <a href={api.original(shown?.card_id ?? contact.card_id, 'front')} download>Download front</a>
              {#if shown?.has_back}<a href={api.original(shown?.card_id ?? contact.card_id, 'back')} download>Download back</a>{/if}
            </div>
          {:else}
            <p class="noscan">No card scanned yet. Scan one and it can be attached to this contact.</p>
          {/if}
          {#if confirming}
            <div class="forget" role="group" aria-label="Forget this contact">
              <p>
                This removes {contact.full_name} from your contacts server and deletes their scans
                and history from FlipDial. It cannot be undone. Backups you already downloaded still
                include them.
              </p>
              <div class="buttons">
                <button type="button" class="secondary" onclick={() => (confirming = false)}>Keep</button>
                <button type="button" class="danger" onclick={forgetContact} disabled={forgetting}>
                  {forgetting ? 'Forgetting…' : 'Forget forever'}
                </button>
              </div>
            </div>
          {:else}
            <button type="button" class="link-danger" onclick={() => (confirming = true)}>Forget this contact…</button>
          {/if}
        {/if}
      </section>
  {/if}
</article>

<style>
  .multiline {
    white-space: pre-line;
  }
  .pane {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 20px;
    min-width: 0;
  }
  .close {
    align-self: flex-end;
    min-height: 40px;
    min-width: 40px;
    margin: -8px -8px -12px 0;
    padding: 0 10px;
    border: 0;
    border-radius: 10px;
    background: transparent;
    color: var(--ash);
    font: inherit;
    font-size: 22px;
    cursor: pointer;
  }
  .close:hover {
    color: var(--paper, #f4efe6);
    background: #23262c;
  }
  .close .phone-only {
    display: none;
    font-size: 15px;
  }
  .loading {
    color: var(--ash);
  }
  .card {
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .reread {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
    font-size: 14px;
  }
  .reread .hint,
  .proposal .hint {
    font-size: 12px;
    color: var(--ash);
    margin: 0;
  }
  .reread .small {
    min-height: 36px;
  }
  .reread .link {
    min-height: 36px;
    padding: 0 4px;
    border: 0;
    background: transparent;
    color: var(--amber);
    font: inherit;
    cursor: pointer;
  }
  .reread .bad {
    color: #e5776b;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--amber);
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .proposal {
    flex: 1 1 100%;
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px 16px;
    border: 1px solid #6a5426;
    border-radius: 12px;
    background: #2a2416;
  }
  .proposal h2 {
    margin: 0;
    font-size: 16px;
  }
  .proposal fieldset {
    margin: 0;
    padding: 10px 0 0;
    border: 0;
    border-top: 1px solid #3a3222;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }
  .proposal legend {
    padding: 0;
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ash);
  }
  .cmp {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    font-size: 14px;
  }
  .cmp .k {
    color: var(--ash);
    font-size: 12px;
    padding-top: 2px;
  }
  .cmp .v {
    display: flex;
    flex-direction: column;
    overflow-wrap: anywhere;
  }
  .cmp .new span.added {
    color: var(--amber);
  }
  .choices {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    font-size: 14px;
  }
  .choices label {
    display: flex;
    align-items: center;
    gap: 6px;
    min-height: 32px;
    cursor: pointer;
  }
  .older {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px 12px;
    font-size: 13px;
    color: var(--amber);
  }
  .history h2 {
    margin: 0 0 8px;
    font-size: 12px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ash);
  }
  .thumbs {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  .thumb {
    position: relative;
    flex: 0 0 96px;
    height: 58px;
    padding: 0;
    border: 2px solid transparent;
    border-radius: 8px;
    background: #23262c;
    cursor: pointer;
    overflow: hidden;
  }
  .thumb[aria-pressed='true'] {
    border-color: var(--amber);
  }
  .thumb .tag {
    position: absolute;
    left: 4px;
    bottom: 4px;
    padding: 1px 5px;
    border-radius: 4px;
    background: rgba(0, 0, 0, 0.7);
    font-size: 10px;
    color: #fff;
  }
  .fliphint {
    margin: 0;
    font-size: 12px;
    color: var(--ash);
    text-align: center;
  }
  .tile {
    display: block;
    width: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }
  .originals {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
    padding: 14px 16px;
    border: 1px solid #2c2f36;
    border-radius: 12px;
  }
  .originals h2 {
    flex-basis: 100%;
    margin: 0;
    font-size: 12px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ash);
  }
  .noscan {
    color: var(--ash);
    margin: 0;
  }
  .info {
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 12px;
  }
  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 30px;
    font-weight: 600;
  }
  .sub {
    margin: 6px 0 0;
    color: #d6d1c9;
  }
  .headbtns {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 10px 20px;
  }
  dt .kind {
    display: block;
    letter-spacing: 0.04em;
    color: var(--amber);
    font-size: 11px;
  }
  dt {
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ash);
    padding-top: 3px;
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .tags {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .tags li {
    font-size: 12px;
    padding: 5px 10px;
    border-radius: 999px;
    background: #23262c;
    border: 1px solid var(--line);
  }
  .panel {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid #2c2f36;
    font-size: 14px;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 6px;
    background: #23262c;
    border: 1px solid var(--line);
    font-size: 10px;
    font-weight: 700;
  }
  .forget {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border-radius: 12px;
    background: #3a2422;
    border: 1px solid #6b3a35;
  }
  .forget p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
  }
  .danger {
    min-height: 44px;
    padding: 0 18px;
    border: 0;
    border-radius: 10px;
    background: #e5776b;
    color: var(--ink);
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  .link-danger {
    align-self: flex-start;
    min-height: 40px;
    padding: 0;
    border: 0;
    background: transparent;
    color: #e5776b;
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .buttons {
    display: flex;
    gap: 10px;
  }
  .primary,
  .secondary {
    min-height: 44px;
    padding: 0 18px;
    border-radius: 10px;
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .primary {
    border: 0;
    background: var(--amber);
    color: var(--ink);
    font-weight: 600;
  }
  .secondary {
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
  }
  .error {
    margin: 0;
    padding: 12px 14px;
    border-radius: 10px;
    background: #3a2a1a;
    color: var(--signal);
  }
  @media (max-width: 900px) {
    .close {
      align-self: flex-start;
      margin: 0;
      font-size: 15px;
    }
    .close .phone-only {
      display: inline;
    }
    .close .wide-only {
      display: none;
    }
  }
</style>
