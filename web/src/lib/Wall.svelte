<script lang="ts">
  import { api, describe, type Contact, type ContactList } from './api'
  import ContactPane from './ContactPane.svelte'
  import FlipCard from './FlipCard.svelte'
  import { contactHref, href } from './router.svelte'
  import Star from './Star.svelte'

  // `open` is the contact shown in the reading pane (from the address, #/wall/<uid>).
  let { query = '', open = '' }: { query?: string; open?: string } = $props()

  type Scan = 'all' | 'yes' | 'no'
  let deck = $state('')
  let starredOnly = $state(false)
  let scan = $state<Scan>('all')
  let data = $state<ContactList | null>(null)
  let error = $state('')
  let syncing = $state(false)
  let dupes = $state(0)

  $effect(() => {
    api.duplicates().then((d) => (dupes = d.count)).catch(() => (dupes = 0))
  })

  // Typing in search sends a request per keystroke; only the newest may update the wall.
  let latest = 0
  async function load() {
    const ticket = ++latest
    try {
      const next = await api.contacts({ q: query, deck, scan, starred: starredOnly })
      if (ticket !== latest) return
      data = next
      error = ''
    } catch (e) {
      if (ticket === latest) error = describe(e)
    }
  }

  $effect(() => {
    // reload whenever a filter changes
    void [query, deck, scan, starredOnly]
    load()
  })

  let storage = $state<'server' | 'local'>('server')
  $effect(() => {
    api.me().then((m) => (storage = m.storage)).catch(() => {})
  })

  async function syncNow() {
    syncing = true
    try {
      await api.sync()
      await load()
    } catch (e) {
      error = describe(e)
    } finally {
      syncing = false
    }
  }

  async function toggleStar(c: Contact) {
    const next = !c.starred
    c.starred = next
    try {
      await api.update(c.uid, { starred: next })
      if (starredOnly && !next) await load()
    } catch (e) {
      c.starred = !next
      error = describe(e)
    }
  }

  const openIndex = $derived(data?.contacts.findIndex((c) => c.uid === open) ?? -1)

  function show(uid: string) {
    location.hash = contactHref(uid)
  }
  function close() {
    location.hash = href({ name: 'wall' })
  }

  // With a contact open: arrow keys move through the wall, Escape closes the pane.
  function onkey(e: KeyboardEvent) {
    if (!open || e.altKey || e.ctrlKey || e.metaKey) return
    const t = e.target as HTMLElement | null
    if (t?.closest('input, textarea, select, [contenteditable]')) return
    const list = data?.contacts ?? []
    if (e.key === 'Escape') close()
    else if ((e.key === 'ArrowRight' || e.key === 'ArrowDown') && openIndex < list.length - 1) show(list[openIndex + 1].uid)
    else if ((e.key === 'ArrowLeft' || e.key === 'ArrowUp') && openIndex > 0) show(list[openIndex - 1].uid)
    else return
    e.preventDefault()
  }

  // Keep the open card in view as the arrow keys move through the wall.
  $effect(() => {
    if (!open) return
    const el = document.querySelector(`[data-uid="${CSS.escape(open)}"]`)
    el?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  })

  function changed(c: Contact) {
    if (!data) return
    const i = data.contacts.findIndex((x) => x.uid === c.uid)
    if (i >= 0) data.contacts[i] = c
  }

  async function forgotten(uid: string) {
    close()
    if (data) data.contacts = data.contacts.filter((c) => c.uid !== uid)
    await load()
  }

  function pickDeck(name: string, starred = false) {
    deck = name
    starredOnly = starred
  }

  const heading = $derived(starredOnly ? 'Starred' : deck || 'All contacts')
  const scanOptions: { id: Scan; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'yes', label: 'Has scan' },
    { id: 'no', label: 'No scan' },
  ]
</script>

<svelte:window onkeydown={onkey} />

<div class="layout" class:with-pane={!!open}>
  <aside>
    <section>
      <h2>Decks</h2>
      <button type="button" class="deck" aria-pressed={!deck && !starredOnly} onclick={() => pickDeck('')}>
        <span>All contacts</span><span class="n">{data?.total ?? ''}</span>
      </button>
      <button type="button" class="deck" aria-pressed={starredOnly} onclick={() => pickDeck('', true)}>
        <span>Starred</span><span class="n">{data?.starred ?? ''}</span>
      </button>
      {#each data?.decks ?? [] as d (d.name)}
        <button type="button" class="deck" aria-pressed={deck === d.name} onclick={() => pickDeck(d.name)}>
          <span>{d.name}</span><span class="n">{d.count}</span>
        </button>
      {/each}
      <a class="deck phone-only" href={href({ name: 'transfer' })}>Import and export</a>
      {#if data?.trashed}
        <a class="trashlink" href={href({ name: 'trash' })}>Trash <span class="n">{data.trashed}</span></a>
      {/if}
    </section>
    {#if dupes}
      <section class="panel">
        <h2>Cleanup</h2>
        <a class="cleanup" href={href({ name: 'duplicates' })}>{dupes} possible duplicate{dupes === 1 ? '' : 's'}</a>
      </section>
    {/if}
    <section class="panel">
      <h2>Sync</h2>
      <div class="row"><span class="badge" aria-hidden="true">S</span><span>{storage === 'local' ? 'Saved on this computer' : 'Contacts server'}</span></div>
      <button type="button" class="secondary" onclick={syncNow} disabled={syncing}>
        {syncing ? 'Syncing…' : 'Sync now'}
      </button>
      <a class="cleanup" href={href({ name: 'transfer' })}>Import, export and backup</a>
      <a class="cleanup" href={href({ name: 'activity' })}>Activity log</a>
      <a class="cleanup" href={href({ name: 'setup' })}>Setup check</a>
    </section>
  </aside>

  <main>
    <div class="toolbar">
      <h1>{heading} <span class="count">{data?.contacts.length ?? 0} {(data?.contacts.length ?? 0) === 1 ? 'contact' : 'contacts'}</span></h1>
      <div class="segmented" role="group" aria-label="Scan filter">
        {#each scanOptions as o (o.id)}
          <button type="button" aria-pressed={scan === o.id} onclick={() => (scan = o.id)}>{o.label}</button>
        {/each}
      </div>
    </div>

    {#if error}<p class="error" role="alert">{error}</p>{/if}

    {#if data && data.contacts.length === 0}
      <p class="empty">No contacts here yet. Scan some cards, then approve them in the review queue.</p>
    {/if}

    <ul class="grid">
      {#each data?.contacts ?? [] as c (c.uid)}
        <li data-uid={c.uid} class:selected={c.uid === open}>
          <button
            type="button"
            class="tile"
            aria-label={`Open ${c.full_name}`}
            aria-current={c.uid === open ? 'true' : undefined}
            onclick={() => show(c.uid)}
          >
            <FlipCard contact={c} />
          </button>
          <div class="foot">
            <div class="who">
              <a href={contactHref(c.uid)}>{c.full_name}</a>
              <span class="sub">{c.event || 'No event'} · {c.card_id ? 'Scan' : c.source}</span>
            </div>
            <div class="actions">
              <span class="badge" role="img" aria-label="Saved to contacts server" title="Saved to contacts server">S</span>
              <Star on={c.starred} label={`${c.starred ? 'Unstar' : 'Star'} ${c.full_name}`} onclick={() => toggleStar(c)} />
            </div>
          </div>
        </li>
      {/each}
    </ul>
  </main>

  {#if open}
    <div class="pane-wrap">
      {#key open}
        <ContactPane
          uid={open}
          initial={data?.contacts.find((c) => c.uid === open) ?? null}
          onclose={close}
          onchange={changed}
          onforget={forgotten}
        />
      {/key}
    </div>
  {/if}
</div>

<style>
  .trashlink {
    display: flex;
    justify-content: space-between;
    margin-top: 6px;
    padding: 6px 12px;
    font-size: 13px;
    color: var(--ash);
    text-decoration: none;
  }
  .trashlink:hover {
    color: var(--bone);
  }
  .pane-wrap {
    flex: 0 1 460px;
    min-width: 360px;
    align-self: flex-start;
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 32px);
    overflow-y: auto;
    padding: 20px 22px 28px;
    border-radius: 16px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .with-pane {
    flex-wrap: nowrap;
  }
  .with-pane main {
    flex: 1 1 300px;
    min-width: 0;
  }
  .with-pane .grid {
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  }
  li.selected .tile {
    outline: 2px solid var(--amber);
    outline-offset: 3px;
    border-radius: 12px;
  }
  /* Narrow windows: the pane covers the wall, with a back button. */
  @media (max-width: 900px) {
    .pane-wrap {
      position: fixed;
      inset: 0;
      z-index: 50;
      max-height: none;
      min-width: 0;
      border-radius: 0;
      border: 0;
      padding: 16px 18px 40px;
    }
  }
  /* Middle widths: make room for the pane by hiding the deck list while it is open. */
  @media (max-width: 1280px) and (min-width: 901px) {
    .with-pane aside {
      display: none;
    }
  }
  .layout {
    display: flex;
    flex-wrap: wrap;
    gap: 32px;
    padding: 28px 32px 48px;
  }
  aside {
    flex: 1 1 220px;
    max-width: 260px;
    display: flex;
    flex-direction: column;
    gap: 28px;
  }
  main {
    flex: 999 1 560px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }
  h2 {
    margin: 0 0 8px;
    font-size: 12px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ash);
    font-weight: 600;
  }
  section {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .deck {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    min-height: 40px;
    padding: 0 12px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: var(--bone);
    font: inherit;
    font-size: 14px;
    text-align: left;
    cursor: pointer;
  }
  .deck[aria-pressed='true'] {
    background: #2a2d33;
    box-shadow: inset 3px 0 0 var(--amber);
  }
  .n {
    color: var(--ash);
    font-size: 13px;
  }
  .panel {
    gap: 10px;
    padding: 16px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .row {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
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
    color: #d6d1c9;
    font-size: 10px;
    font-weight: 700;
  }
  .cleanup {
    font-size: 14px;
  }
  .secondary {
    min-height: 40px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
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
  .segmented {
    display: flex;
    padding: 3px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--graphite);
  }
  .segmented button {
    min-height: 36px;
    padding: 0 12px;
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
  .grid {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 28px 24px;
  }
  li {
    display: flex;
    flex-direction: column;
    justify-content: flex-end; /* cards of other shapes line up at the bottom, names in a row */
    gap: 10px;
  }
  .tile {
    display: block;
    width: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }
  .foot {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }
  .who {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }
  .who a {
    color: var(--bone);
    text-decoration: none;
    font-weight: 600;
    font-size: 15px;
  }
  .who a:hover {
    text-decoration: underline;
  }
  .sub {
    font-size: 13px;
    color: var(--ash);
  }
  .actions {
    display: flex;
    align-items: center;
    gap: 2px;
    margin: -8px -10px 0 0;
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
  /* Phones: decks become a scrolling row so cards are visible right away. */
  .phone-only {
    display: none;
  }
  @media (max-width: 700px) {
    .phone-only {
      display: flex;
      align-items: center;
      color: var(--ash);
      text-decoration: none;
      white-space: nowrap;
    }
    .layout {
      gap: 16px;
      padding: 16px;
    }
    aside {
      max-width: none;
      flex-basis: 100%;
      gap: 0;
    }
    aside section:first-child {
      flex-direction: row;
      gap: 6px;
      overflow-x: auto;
      padding-bottom: 4px;
    }
    aside section:first-child h2,
    .panel {
      display: none;
    }
    .deck {
      width: auto;
      flex-shrink: 0;
      gap: 8px;
      border: 1px solid var(--line);
      border-radius: 999px;
    }
    .deck[aria-pressed='true'] {
      box-shadow: none;
      border-color: var(--amber);
    }
  }
</style>
