<script lang="ts">
  import { api, describe, READ_ERRORS, REASONS, type ContactInput, type Match, type ReviewItem, type SetupItem } from './api'
  import { href } from './router.svelte'
  import ContactForm from './ContactForm.svelte'

  let { onchange }: { onchange?: () => void } = $props()

  let items = $state<ReviewItem[]>([])
  let index = $state(0)
  let form = $state<ContactInput | null>(null)
  let showBack = $state(false)
  let busy = $state(false)
  let error = $state('')
  let matches = $state<Match[]>([])

  const ready = $derived(items.filter((i) => i.status === 'review'))
  const waiting = $derived(items.filter((i) => i.status !== 'review'))
  const current = $derived(ready[index] ?? null)

  function toForm(item: ReviewItem): ContactInput {
    const f = item.fields
    return {
      full_name: f?.full_name.value ?? '',
      title: f?.title.value ?? '',
      organization: f?.organization.value ?? '',
      emails: f?.emails.map((x) => x.value) ?? [],
      phones: f?.phones.map((x) => x.value) ?? [],
      websites: f?.websites.map((x) => x.value) ?? [],
      socials: f?.socials.map((s) => ({ platform: s.platform, handle: s.handle })) ?? [],
      address: f?.address.value ?? '',
      about: f?.about?.value ?? '',
      note: '',
      event: '',
      met_on: '',
      starred: false,
      tags: [],
    }
  }

  async function load() {
    try {
      items = (await api.review()).items
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }

  $effect(() => {
    load()
  })

  // While no card is open, check for new and newly read cards every few seconds.
  // (Never while a card is open, so edits in progress aren't reset.)
  $effect(() => {
    if (current) return
    // Faster while a card shows live progress, so the panel feels live.
    const timer = setInterval(load, waiting.some((w) => w.progress) ? 1500 : 4000)
    return () => clearInterval(timer)
  })

  // When cards are stuck, say why: the first setup problem, if any.
  let problem = $state<SetupItem | null>(null)
  const waitingCount = $derived(waiting.length) // a number, so this reruns only when it changes
  $effect(() => {
    if (!waitingCount) {
      problem = null
      return
    }
    api
      .status()
      .then((s) => (problem = s.items.find((i) => i.state === 'fail') ?? null))
      .catch(() => (problem = null))
  })

  const failed = $derived(waiting.filter((i) => i.status === 'extract_failed'))

  const STAGES = { waiting: 'Starting the model', reading: 'Reading the card', checking: 'Checking what was read' } as const
  const FIELD_ORDER = ['full_name', 'title', 'organization', 'emails', 'phones', 'websites', 'address', 'about'] as const
  const FIELD_NAMES: Record<(typeof FIELD_ORDER)[number], string> = {
    full_name: 'Name',
    title: 'Title',
    organization: 'Company',
    emails: 'Email',
    phones: 'Phone',
    websites: 'Website',
    address: 'Address',
    about: 'About',
  }

  async function readAgain(cardId?: string) {
    try {
      if (cardId) await api.retry(cardId)
      else await api.retryAll()
      await load()
    } catch (e) {
      error = describe(e)
    }
  }

  let lastEvent = ''
  // Unsaved edits, kept per card so moving to another card and back loses nothing.
  // A plain Map, not state, so writing to it never reruns the effect below.
  const drafts = new Map<string, ContactInput>()

  function go(step: number) {
    if (!current || ready.length < 2) return
    if (form) drafts.set(current.card_id, form)
    index = (index + step + ready.length) % ready.length
  }

  function onkey(e: KeyboardEvent) {
    if (!current || e.altKey || e.ctrlKey || e.metaKey) return
    const t = e.target as HTMLElement | null
    if (t?.closest('input, textarea, select, [contenteditable]')) return
    if (e.key === 'ArrowLeft') go(-1)
    else if (e.key === 'ArrowRight') go(1)
    else return
    e.preventDefault()
  }

  $effect(() => {
    if (current) {
      const next = drafts.get(current.card_id) ?? toForm(current)
      if (!drafts.has(current.card_id)) next.event = lastEvent // keep the deck while working through a stack
      form = next
      showBack = false
      matches = []
      const id = current.card_id
      api
        .matches(id)
        .then((r) => {
          if (current?.card_id === id) matches = r.matches
        })
        .catch(() => (matches = []))
    } else {
      form = null
    }
  })

  function cleaned(f: ContactInput): ContactInput {
    return {
      ...f,
      emails: f.emails.filter(Boolean),
      phones: f.phones.filter(Boolean),
      websites: f.websites.filter(Boolean),
    }
  }

  async function attach(uid: string) {
    if (!current || !form) return
    busy = true
    try {
      lastEvent = form.event
      await api.attach(current.card_id, uid, cleaned(form))
      drafts.delete(current.card_id)
      await load()
      if (index >= ready.length) index = Math.max(0, ready.length - 1)
      onchange?.()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  async function approve() {
    if (!current || !form) return
    busy = true
    try {
      lastEvent = form.event
      await api.approve(current.card_id, cleaned(form))
      drafts.delete(current.card_id)
      await load()
      if (index >= ready.length) index = Math.max(0, ready.length - 1)
      onchange?.()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  // Undo for the last dismissal, the Dismissed list, and reading a card again.
  let undoId = $state<string | null>(null)
  let confirmReread = $state(false)
  let dismissedList = $state<{ card_id: string; created_at: string; label: string }[]>([])
  let showDismissed = $state(false)
  let confirmDelete = $state<string | null>(null)

  async function loadDismissed() {
    try {
      dismissedList = (await api.dismissedCards()).items
    } catch {
      dismissedList = []
    }
  }
  $effect(() => {
    loadDismissed()
  })

  async function act(fn: () => Promise<unknown>) {
    try {
      await fn()
      await Promise.all([load(), loadDismissed()])
      onchange?.()
    } catch (e) {
      error = describe(e)
    }
  }
  const restore = (id: string) => act(async () => { await api.restoreCard(id); if (undoId === id) undoId = null })
  const reread = (id: string) => act(async () => { await api.retry(id); confirmReread = false; if (undoId === id) undoId = null })
  const remove = (id: string) => act(async () => { await api.deleteCard(id); confirmDelete = null })

  async function dismiss() {
    if (!current) return
    busy = true
    const id = current.card_id
    try {
      await api.dismiss(id)
      undoId = id
      await Promise.all([load(), loadDismissed()])
      onchange?.()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }
</script>

<svelte:window onkeydown={onkey} />

<div class="wrap">
  {#if undoId}
    <p class="undo" role="status">
      Card dismissed. <button type="button" class="link" onclick={() => undoId && restore(undoId)}>Undo</button>
      <button type="button" class="link" aria-label="Close message" onclick={() => (undoId = null)}>×</button>
    </p>
  {/if}
  <h1>
    Review
    <span class="count">
      {ready.length} ready{waiting.length - failed.length ? `, ${waiting.length - failed.length} being read` : ''}{failed.length
        ? `, ${failed.length} couldn't be read`
        : ''}
    </span>
  </h1>
  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if problem}
    <div class="problem" role="status">
      <strong>Cards can't be read right now.</strong>
      <span>{problem.label}: {problem.detail}</span>
      {#if problem.fix}<span class="fix">{problem.fix}</span>{/if}
      <a href={href({ name: 'setup' })}>Open the setup check</a>
    </div>
  {/if}

  {#if waiting.length && !current}
    <section class="waiting" aria-label="Cards being read">
      <div class="waiting-head">
        <h2>{failed.length ? `${failed.length} couldn't be read` : 'Reading your cards'}</h2>
        {#if failed.length > 1}<button type="button" class="secondary all" onclick={() => readAgain()}>Read all again</button>{/if}
      </div>
      <ul>
        {#each waiting as w (w.card_id)}
          <li>
            <img src={api.image(w.card_id, 'thumb')} alt="Scanned card" loading="lazy" />
            {#if w.status === 'extract_failed'}
              <span class="why">{READ_ERRORS[w.error ?? ''] ?? "Couldn't be read."}</span>
              {#if w.error_detail}<span class="said">Ollama said: {w.error_detail}</span>{/if}
              <button type="button" class="secondary" onclick={() => readAgain(w.card_id)}>Read again</button>
            {:else}
              {#if w.progress}
                <div class="live" aria-live="polite">
                  <span class="stage"><span class="pulse" aria-hidden="true"></span>{w.progress.stage === 'reading' && !FIELD_ORDER.some((k) => w.progress?.fields[k]?.length) ? 'Copying the text' : STAGES[w.progress.stage]} · {w.progress.seconds}s</span>
                  {#if w.progress.stage === 'waiting' && w.progress.seconds > 10}
                    <span class="reading">Loading the model can take a minute on the first card.</span>
                  {/if}
                  {#if w.progress.fields.text?.length && !FIELD_ORDER.some((k) => w.progress?.fields[k]?.length)}
                    <div class="seeing" aria-label="Text read so far">
                      {#each w.progress.fields.text as line, i (i + line)}<span>{line}</span>{/each}
                    </div>
                  {/if}
                  {#if FIELD_ORDER.some((k) => w.progress?.fields[k]?.length)}
                    <dl>
                      {#each FIELD_ORDER as key (key)}
                        {#if w.progress.fields[key]?.length}
                          <dt>{FIELD_NAMES[key]}</dt>
                          <dd>{Array.isArray(w.progress.fields[key]) ? (w.progress.fields[key] as string[]).join(', ') : w.progress.fields[key]}</dd>
                        {/if}
                      {/each}
                    </dl>
                  {/if}
                </div>
              {:else}
                <span class="reading">{w.error ? `Retrying: ${READ_ERRORS[w.error] ?? w.error}` : 'Waiting its turn…'}</span>
              {/if}
            {/if}
          </li>
        {/each}
      </ul>
      {#if !failed.length}<p class="hint">The first card can take a minute while the model loads. This page updates by itself.</p>{/if}
    </section>
  {/if}

  {#if !current}
    {#if !waiting.length}<p class="empty">Nothing to review. New scans appear here after they are read.</p>{/if}
  {:else if form}
    <div class="layout">
      <section class="images" aria-label="Card images">
        <img
          src={api.image(current.card_id, showBack ? 'back' : 'front')}
          alt={showBack ? 'Back of the card' : 'Front of the card'}
        />
        {#if current.has_back}
          <div class="segmented" role="group" aria-label="Side">
            <button type="button" aria-pressed={!showBack} onclick={() => (showBack = false)}>Front</button>
            <button type="button" aria-pressed={showBack} onclick={() => (showBack = true)}>Back</button>
          </div>
        {/if}
        {#if current.flags.length}
          <p class="flags">Check the highlighted fields before saving.</p>
        {/if}
        <nav class="pager" aria-label="Cards to review">
          <button type="button" class="secondary" onclick={() => go(-1)} disabled={ready.length < 2} aria-label="Previous card">‹ Previous</button>
          <p class="pos" aria-live="polite">{index + 1} of {ready.length}</p>
          <button type="button" class="secondary" onclick={() => go(1)} disabled={ready.length < 2} aria-label="Next card">Next ›</button>
        </nav>
      </section>
      <section class="details" aria-label="Contact details">
        {#each matches as m (m.contact.uid)}
          <div class="match" role="note">
            <p>
              Looks like <strong>{m.contact.full_name}</strong>, already in your contacts
              ({m.reasons.map((r) => REASONS[r] ?? r).join(', ').toLowerCase()}).
            </p>
            <button type="button" class="primary small" onclick={() => attach(m.contact.uid)} disabled={busy}>
              Add this scan to {m.contact.full_name}
            </button>
          </div>
        {/each}
        <ContactForm bind:value={form} flags={current.flags} idPrefix="review" />
        {#if confirmReread}
          <div class="confirm" role="group" aria-label="Read this card again">
            <span>Read this card again? Changes you made here are discarded.</span>
            <button type="button" class="secondary" onclick={() => (confirmReread = false)}>Cancel</button>
            <button type="button" class="primary" onclick={() => current && reread(current.card_id)}>Read again</button>
          </div>
        {/if}
        {#if !form.full_name.trim() && form.organization.trim()}
          <p class="hint">No person's name, so this is saved as a company contact.</p>
        {/if}
        <div class="buttons">
          <button type="button" class="secondary" onclick={dismiss} disabled={busy}>Dismiss</button>
          <button type="button" class="secondary" onclick={() => (confirmReread = true)} disabled={busy}>Read again</button>
          <button type="button" class="primary" onclick={approve} disabled={busy || !(form.full_name.trim() || form.organization.trim())}>
            {busy ? 'Saving…' : matches.length ? 'Save as a new contact' : 'Approve and save'}
          </button>
        </div>
      </section>
    </div>
  {/if}
  {#if dismissedList.length}
    <section class="dismissed">
      <button type="button" class="link" aria-expanded={showDismissed} onclick={() => (showDismissed = !showDismissed)}>
        {showDismissed ? 'Hide' : 'Show'} dismissed cards ({dismissedList.length})
      </button>
      {#if showDismissed}
        <ul>
          {#each dismissedList as d (d.card_id)}
            <li>
              <img src={api.image(d.card_id, 'thumb')} alt="Dismissed card" loading="lazy" />
              <span class="label">{d.label || 'Not read'}</span>
              {#if confirmDelete === d.card_id}
                <span class="why">Delete this scan for good? This can't be undone.</span>
                <div class="row">
                  <button type="button" class="secondary" onclick={() => (confirmDelete = null)}>Keep</button>
                  <button type="button" class="danger" onclick={() => remove(d.card_id)}>Delete</button>
                </div>
              {:else}
                <div class="row">
                  <button type="button" class="secondary" onclick={() => restore(d.card_id)}>Back to review</button>
                  <button type="button" class="secondary" onclick={() => reread(d.card_id)}>Read again</button>
                  <button type="button" class="link danger-link" onclick={() => (confirmDelete = d.card_id)}>Delete</button>
                </div>
              {/if}
            </li>
          {/each}
        </ul>
      {/if}
    </section>
  {/if}
</div>

<style>
  .wrap {
    max-width: 1200px;
    margin: 0 auto;
    padding: 28px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 30px;
    font-weight: 600;
  }
  .count {
    color: var(--ash);
    font-size: 18px;
    font-weight: 500;
  }
  .layout {
    display: flex;
    flex-wrap: wrap;
    gap: 32px;
  }
  .images {
    flex: 1 1 420px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .images img {
    width: 100%;
    max-height: 60vh;
    object-fit: contain;
    border-radius: 10px;
    background: #111214;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
  }
  .details {
    flex: 1 1 360px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  .segmented {
    display: flex;
    align-self: flex-start;
    padding: 3px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--graphite);
  }
  .segmented button {
    min-height: 36px;
    padding: 0 16px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: #bdb8af;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .segmented button[aria-pressed='true'] {
    background: #2e3239;
    color: var(--bone);
  }
  .flags {
    margin: 0;
    color: var(--amber);
    font-size: 14px;
  }
  .pager {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .pager button {
    min-height: 44px;
  }
  .pos {
    margin: 0;
    font-family: var(--font-mono);
    color: var(--ash);
    font-size: 13px;
  }
  .buttons {
    display: flex;
    gap: 10px;
  }
  .primary,
  .secondary {
    min-height: 48px;
    border-radius: 12px;
    font: inherit;
    font-size: 15px;
    cursor: pointer;
  }
  .primary {
    flex: 2;
    border: 0;
    background: var(--amber);
    color: var(--ink);
    font-weight: 600;
  }
  .secondary {
    flex: 1;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
  }
  .match {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid var(--amber);
    background: #2a241a;
  }
  .match p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
  }
  .primary.small {
    flex: none;
    align-self: flex-start;
    min-height: 40px;
    padding: 0 14px;
    font-size: 14px;
  }
  button:disabled {
    opacity: 0.6;
    cursor: default;
  }
  .error {
    margin: 0;
    padding: 12px 14px;
    border-radius: 10px;
    background: #3a2a1a;
    color: var(--signal);
  }
  .empty {
    color: var(--ash);
  }
  .problem {
    display: flex;
    flex-direction: column;
    gap: 4px;
    padding: 14px 16px;
    border-radius: 12px;
    background: #3a2422;
    border: 1px solid #6b3a35;
    font-size: 14px;
    line-height: 1.5;
  }
  .problem .fix {
    color: #f0d6cf;
  }
  .waiting {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .waiting-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  .waiting .all {
    flex: 0 0 auto;
    width: auto;
  }
  .waiting h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 19px;
  }
  .waiting ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px;
  }
  .waiting li {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .waiting img {
    width: 100%;
    aspect-ratio: 1.75;
    object-fit: contain;
    border-radius: 6px;
    background: #111;
  }
  .reading,
  .hint {
    color: var(--ash);
    font-size: 13px;
  }
  .hint {
    margin: 0;
  }
  .live {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .stage {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--bone);
  }
  .pulse {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--sage);
    animation: pulse 1.2s ease-in-out infinite;
  }
  @keyframes pulse {
    50% {
      opacity: 0.3;
    }
  }
  .seeing {
    display: flex;
    flex-direction: column;
    gap: 1px;
    font-family: var(--font-mono);
    font-size: 11px;
    color: #cfc9bf;
  }
  .seeing span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    animation: arrive 0.4s ease-out;
  }
  .live dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 2px 10px;
    margin: 0;
    font-size: 12px;
  }
  .live dt {
    color: var(--ash);
  }
  .live dd {
    margin: 0;
    overflow-wrap: anywhere;
    animation: arrive 0.4s ease-out;
  }
  @keyframes arrive {
    from {
      opacity: 0;
    }
  }
  .undo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 0;
    padding: 10px 14px;
    border-radius: 10px;
    background: #22302a;
    border: 1px solid #3d5a4b;
    font-size: 14px;
  }
  .confirm {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
    padding: 12px 14px;
    border-radius: 10px;
    background: #33301f;
    border: 1px solid #6a5e2e;
    font-size: 14px;
  }
  .confirm span {
    flex: 1 1 220px;
  }
  .hint {
    margin: 0;
    color: var(--ash);
    font-size: 13px;
  }
  .link {
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--amber);
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .dismissed {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding-top: 12px;
    border-top: 1px solid #2c2f36;
  }
  .dismissed .link {
    align-self: flex-start;
  }
  .dismissed ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
    gap: 14px;
  }
  .dismissed li {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .dismissed img {
    width: 100%;
    aspect-ratio: 1.75;
    object-fit: contain;
    border-radius: 6px;
    background: #111;
  }
  .dismissed .label {
    font-size: 14px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .row .secondary {
    white-space: nowrap;
    min-height: 36px;
    padding: 0 12px;
    font-size: 13px;
  }
  .danger {
    min-height: 36px;
    padding: 0 12px;
    border: 0;
    border-radius: 10px;
    background: #e5776b;
    color: var(--ink);
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .danger-link {
    color: #e5776b;
    font-size: 13px;
  }
  .said {
    color: var(--ash);
    font-family: var(--font-mono);
    font-size: 12px;
    overflow-wrap: anywhere;
  }
  .why {
    color: #f0b3a8;
    font-size: 13px;
  }
</style>
