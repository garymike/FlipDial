<script lang="ts">
  // Dial view: spin through contacts one card at a time.
  // Drag (with momentum), scroll, arrow keys, A to Z letters and the header search all move it.
  import { untrack } from 'svelte'
  import { api, describe, type Contact, type ContactList } from './api'
  import ContactPane from './ContactPane.svelte'
  import { layout, touch } from './layout.svelte'
  import Sheet from './Sheet.svelte'
  import { countMatches, letterIndex, mod, nearest, offset, seek, settle, slot } from './dial'
  import FlipCard from './FlipCard.svelte'
  import { href } from './router.svelte'

  let { query = '' }: { query?: string } = $props()

  // Drum shape: a tighter drum on narrow screens so the front card stays clear.
  const narrowQuery = window.matchMedia('(max-width: 700px)')
  let narrow = $state(narrowQuery.matches)
  $effect(() => {
    const update = () => (narrow = narrowQuery.matches)
    narrowQuery.addEventListener('change', update)
    return () => narrowQuery.removeEventListener('change', update)
  })
  const SPACING = $derived(narrow ? 24 : 17) // degrees between cards
  const RADIUS = $derived(narrow ? 240 : 420) // drum radius in px
  const PX_PER_CARD = 70 // drag distance that moves one card

  type Scan = 'all' | 'yes' | 'no'
  let deck = $state('')
  let starredOnly = $state(false)
  let scan = $state<Scan>('all')
  let data = $state<ContactList | null>(null)
  let error = $state('')

  let pos = $state(0)
  let dragging = $state(false)
  let flipped = $state(false)

  const cards = $derived(data?.contacts ?? [])
  const n = $derived(Math.max(cards.length, 1))
  const index = $derived(cards.length ? mod(Math.round(pos), cards.length) : 0)
  const current = $derived<Contact | null>(cards[index] ?? null)
  const letters = $derived(letterIndex(cards.map((c) => c.full_name)))

  // Only the newest request may update the dial. Switching filters quickly sends several,
  // and an older, slower answer must not land on top of the newer one.
  let latest = 0
  async function load() {
    const ticket = ++latest
    try {
      const next = await api.contacts({ deck, scan, starred: starredOnly })
      if (ticket !== latest) return
      data = next
      pos = 0
      flipped = false
      error = ''
    } catch (e) {
      if (ticket === latest) error = describe(e)
    }
  }

  $effect(() => {
    void [deck, scan, starredOnly]
    load()
  })

  // The header search dials to the first match instead of filtering.
  // Runs only when the query or the card list changes, not on every move.
  let details = $state(false) // phone and tablet: the full pane, opened from the strip
  let noMatch = $state(false)
  const matchCount = $derived(countMatches(query, cards))

  function changed(c: Contact) {
    const i = cards.findIndex((x) => x.uid === c.uid)
    if (i >= 0 && data) data.contacts[i] = c
  }
  async function forgotten() {
    await load()
  }
  $effect(() => {
    const i = seek(query, cards)
    noMatch = !!query.trim() && cards.length > 0 && i < 0
    if (i >= 0) untrack(() => goTo(i))
  })

  function goTo(i: number) {
    pos = nearest(i, pos, n)
    flipped = false
  }
  function step(k: number) {
    pos = Math.round(pos) + k
    flipped = false
  }

  // -- drag with momentum -------------------------------------------------------------
  let drag: { y: number; start: number; lastY: number; lastT: number; v: number; moved: boolean; hit: number } | null =
    null

  function onpointerdown(e: PointerEvent) {
    const el = (e.target as HTMLElement).closest('[data-i]')
    drag = { y: e.clientY, start: pos, lastY: e.clientY, lastT: performance.now(), v: 0, moved: false, hit: el ? Number(el.getAttribute('data-i')) : -1 }
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  function onpointermove(e: PointerEvent) {
    if (!drag) return
    const dy = e.clientY - drag.y
    if (!drag.moved && Math.abs(dy) < 5) return
    const now = performance.now()
    const dt = Math.max(8, now - drag.lastT) // ignore bursts of events a few ms apart
    drag.v = 0.8 * ((drag.lastY - e.clientY) / PX_PER_CARD / dt) + 0.2 * drag.v
    drag.lastY = e.clientY
    drag.lastT = now
    drag.moved = true
    dragging = true
    flipped = false
    pos = drag.start - dy / PX_PER_CARD
  }

  function onpointercancel() {
    // The browser took over the gesture: settle on the nearest card, no throw.
    if (drag?.moved) pos = Math.round(pos)
    drag = null
    dragging = false
  }

  function onpointerup() {
    const g = drag
    drag = null
    if (!g) return
    if (!g.moved) {
      if (g.hit < 0) return
      if (g.hit === index) flipped = !flipped
      else goTo(g.hit)
      return
    }
    dragging = false
    // Held still before letting go: no throw.
    const still = performance.now() - g.lastT > 90
    pos = settle(pos, still ? 0 : g.v)
  }

  // -- wheel (needs a non-passive listener so the page does not scroll) ---------------
  function wheel(node: HTMLElement) {
    let acc = 0
    let last = 0
    const handler = (e: WheelEvent) => {
      e.preventDefault()
      acc += e.deltaY
      const now = performance.now()
      if (Math.abs(acc) > 36 && now - last > 70) {
        step(acc > 0 ? 1 : -1)
        acc = 0
        last = now
      }
    }
    node.addEventListener('wheel', handler, { passive: false })
    return { destroy: () => node.removeEventListener('wheel', handler) }
  }

  function onkeydown(e: KeyboardEvent) {
    const keys: Record<string, () => void> = {
      ArrowDown: () => step(1),
      ArrowRight: () => step(1),
      ArrowUp: () => step(-1),
      ArrowLeft: () => step(-1),
      PageDown: () => step(3),
      PageUp: () => step(-3),
      Home: () => goTo(0),
      End: () => goTo(cards.length - 1),
      Enter: () => (flipped = !flipped),
      ' ': () => (flipped = !flipped),
    }
    const action = keys[e.key]
    if (action) {
      e.preventDefault()
      action()
    }
  }



  function pickDeck(name: string, starred = false) {
    deck = name
    starredOnly = starred
  }

  const scanOptions: { id: Scan; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'yes', label: 'Has scan' },
    { id: 'no', label: 'No scan' },
  ]
</script>

<div class="page">
  <div class="filters">
    <div class="decks" role="group" aria-label="Deck">
      <button type="button" aria-pressed={!deck && !starredOnly} onclick={() => pickDeck('')}>All contacts</button>
      <button type="button" aria-pressed={starredOnly} onclick={() => pickDeck('', true)}>Starred</button>
      {#each data?.decks ?? [] as d (d.name)}
        <button type="button" aria-pressed={deck === d.name} onclick={() => pickDeck(d.name)}>{d.name}</button>
      {/each}
    </div>
    <div class="segmented" role="group" aria-label="Scan filter">
      {#each scanOptions as o (o.id)}
        <button type="button" aria-pressed={scan === o.id} onclick={() => (scan = o.id)}>{o.label}</button>
      {/each}
    </div>
  </div>

  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if data && cards.length === 0}
    <p class="empty">
      {#if starredOnly}No starred contacts yet. Use the star on a contact to add it here.
      {:else if scan === 'yes'}No contacts with a scanned card{deck ? ' in this deck' : ''}.
      {:else if scan === 'no'}Every contact{deck ? ' in this deck' : ''} has a scanned card.
      {:else if deck}No contacts in this deck.
      {:else}No contacts yet. Scan some cards, then approve them in Review.{/if}
    </p>
  {:else}
    <div class="layout">
      <nav class="letters" aria-label="Jump to letter">
        {#each 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('') as ch (ch)}
          <button
            type="button"
            disabled={!letters.has(ch)}
            aria-current={current?.full_name.trim().charAt(0).toUpperCase() === ch ? 'true' : undefined}
            aria-label={`Jump to ${ch}`}
            onclick={() => goTo(letters.get(ch) ?? 0)}>{ch}</button
          >
        {/each}
      </nav>

      <div class="center">
        <div
          class="stage"
          class:dragging
          tabindex="0"
          role="slider"
          aria-label="Dial"
          aria-roledescription="dial"
          aria-valuemin={1}
          aria-valuemax={cards.length}
          aria-valuenow={index + 1}
          aria-valuetext={current ? `${current.full_name}, ${index + 1} of ${cards.length}. Enter flips the card.` : ''}
          use:wheel
          {onpointerdown}
          {onpointermove}
          {onpointerup}
          {onpointercancel}
          ondragstart={(e) => e.preventDefault()}
          {onkeydown}
        >
          <div class="shadow" aria-hidden="true"></div>
          <div class="drum">
            {#each cards as c, i (c.uid)}
              {@const s = slot(offset(i, pos, n), SPACING, RADIUS)}
              <div
                class="slot"
                data-i={i}
                aria-hidden={i !== index}
                style:transform={s.transform}
                style:opacity={s.opacity}
                style:z-index={s.zIndex}
                style:pointer-events={s.visible ? 'auto' : 'none'}
                style:filter={s.shade > 0.01 ? `brightness(${(1 - s.shade).toFixed(2)})` : undefined}
              >
                <FlipCard contact={c} flipped={i === index && flipped} size="large" tall={1} />
              </div>
            {/each}
          </div>
        </div>

        <div class="controls">
          <button type="button" class="round" aria-label="Previous card" onclick={() => step(-1)}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 12l5-5 5 5" /></svg>
          </button>
          <div class="rail">
            <div class="track" aria-hidden="true">
              <span class="fill" style:width={`${cards.length > 1 ? (index / (cards.length - 1)) * 100 : 100}%`}></span>
            </div>
            <span class="pos" aria-live="polite">{index + 1} / {cards.length}{current ? ` · ${current.full_name}` : ''}</span>
          </div>
          <button type="button" class="round" aria-label="Next card" onclick={() => step(1)}>
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 8l5 5 5-5" /></svg>
          </button>
        </div>
        {#if noMatch}<p class="nomatch" role="status">Nothing matches “{query.trim()}” here. Try part of a name, company, email or event.</p>{/if}
        {#if matchCount > 1}
          <a class="towall" href={href({ name: 'wall' })}>Show all {matchCount} matches on the Wall</a>
        {/if}
        {#if current && layout.mode !== 'desktop'}
          <!-- Phone and tablet: a short strip under the dial; Details opens the full pane. -->
          <div class="strip">
            <button type="button" class="who" onclick={() => (details = true)}>
              <strong>{current.full_name}</strong>
              {#if current.title || (current.organization && current.organization !== current.full_name)}
                <span>{[current.title, current.organization !== current.full_name ? current.organization : ''].filter(Boolean).join(', ')}</span>
              {/if}
            </button>
            <div class="quick">
              {#if current.phones[0]}
                <a class="round" href={`tel:${current.phones[0].value.replace(/[^\d+]/g, '')}`} aria-label={`Call ${current.full_name}`}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2" /></svg>
                </a>
              {/if}
              {#if current.emails[0]}
                <a class="round" href={`mailto:${current.emails[0].value}`} aria-label={`Email ${current.full_name}`}>
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 7l9 6 9-6" /></svg>
                </a>
              {/if}
              <button type="button" class="primary" onclick={() => (details = true)}>Details</button>
            </div>
          </div>
        {/if}
        <p class="hint">
          {#if touch}Swipe up or down to dial. Tap the front card to flip it. Type in search to dial to a name.
          {:else}Drag, scroll or use the arrow keys to dial. Click the front card or press Enter to flip it. Type in search to dial to a name.{/if}
        </p>
      </div>

      {#if current && layout.mode === 'desktop'}
        <aside aria-label="Current contact">
          <ContactPane uid={current.uid} initial={current} showCard={false} onchange={changed} onforget={forgotten} />
        </aside>
      {/if}
      {#if current && details && layout.mode !== 'desktop'}
        <Sheet onclose={() => (details = false)}>
          <ContactPane
            uid={current.uid}
            initial={current}
            onclose={() => (details = false)}
            onchange={changed}
            onforget={async () => {
              details = false
              await forgotten()
            }}
          />
        </Sheet>
      {/if}
    </div>
  {/if}
</div>

<style>
  .page {
    padding: 20px 32px 40px;
    display: flex;
    flex-direction: column;
    gap: 12px;
    background: radial-gradient(ellipse at 50% 35%, #262a31 0%, transparent 62%);
  }
  .filters {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .decks {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .decks button {
    min-height: 40px;
    padding: 0 14px;
    border-radius: 999px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
    font-size: 13px;
    font-weight: 500;
    white-space: nowrap;
    flex-shrink: 0;
    cursor: pointer;
  }
  .decks button[aria-pressed='true'] {
    background: var(--amber);
    border-color: var(--amber);
    color: var(--ink);
  }
  .segmented {
    display: flex;
    margin-left: auto;
    padding: 3px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--graphite);
  }
  .segmented button {
    min-height: 34px;
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
  .layout {
    display: flex;
    flex-wrap: wrap;
    gap: 24px;
  }
  /* Centered on the dial itself, not on the row, which grows with the reading pane:
     the letters stay put and only the highlight moves. Same height as .stage. */
  .letters {
    align-self: flex-start;
    height: 600px;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 1px;
  }
  .letters button {
    flex: 0 0 auto;
    width: 36px;
    height: 22px;
    padding: 0;
    border: 0;
    border-radius: 5px;
    background: transparent;
    color: #d6d1c9;
    font-family: var(--font-mono);
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  .letters button:disabled {
    color: #5a5e66;
    cursor: default;
  }
  .letters button[aria-current='true'] {
    background: var(--amber);
    color: var(--ink);
  }
  .center {
    flex: 2 1 560px; /* the dial about 2/3, the reading pane 1/3 */
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 16px;
  }
  .stage {
    position: relative;
    width: 100%;
    height: 600px;
    overflow: hidden; /* keep the cards at the back inside the dial */
    border-radius: 12px;
    touch-action: none;
    user-select: none;
    cursor: grab;
    outline: none;
  }
  .stage:focus-visible {
    outline: 2px solid var(--amber);
    outline-offset: 6px;
    border-radius: 12px;
  }
  .stage.dragging {
    cursor: grabbing;
  }
  .shadow {
    position: absolute;
    left: 50%;
    top: 50%;
    width: min(560px, 80%);
    height: 30px;
    transform: translate(-50%, 196px);
    border-radius: 50%;
    background: rgba(0, 0, 0, 0.5);
    filter: blur(16px);
  }
  /* Each card is projected on its own (no shared 3D space), so cards never cut through each other. */
  .drum {
    position: absolute;
    inset: 0;
    perspective: 1500px;
    perspective-origin: 50% 42%;
  }
  .slot {
    position: absolute;
    left: 50%;
    top: 50%;
    width: min(560px, 86%);
    will-change: transform, opacity;
    transition:
      transform 0.6s cubic-bezier(0.22, 1, 0.36, 1),
      opacity 0.45s ease,
      filter 0.45s ease;
  }
  .dragging .slot {
    transition: none;
  }
  .controls {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .round {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 48px;
    height: 48px;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    cursor: pointer;
  }
  .rail {
    display: flex;
    flex-direction: column;
    gap: 6px;
    width: 240px;
  }
  .track {
    position: relative;
    height: 4px;
    border-radius: 2px;
    background: #2c2f36;
  }
  .fill {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    border-radius: 2px;
    background: var(--amber);
    transition: width 0.4s ease;
  }
  .pos {
    text-align: center;
    font-family: var(--font-mono);
    font-size: 13px;
    color: #d6d1c9;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .hint {
    margin: 0;
    font-size: 13px;
    color: var(--ash);
    text-align: center;
  }
  .towall {
    font-size: 14px;
  }
  aside {
    flex: 1 1 360px;
    max-width: 620px;
    align-self: flex-start;
    position: sticky;
    top: 16px;
    max-height: calc(100vh - 32px);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 24px;
    border-radius: 14px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .error {
    margin: 0;
    padding: 12px 14px;
    border-radius: 10px;
    background: #3a2a1a;
    color: var(--signal);
  }
  .nomatch {
    margin: 0;
    color: var(--amber);
    font-size: 14px;
    text-align: center;
  }
  .empty {
    color: var(--ash);
  }
  .strip {
    width: 100%;
    max-width: 560px;
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 14px;
    border-radius: 14px;
    background: var(--panel);
    border: 1px solid #2c2f36;
    box-sizing: border-box;
  }
  .strip .who {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 0;
    border: 0;
    background: transparent;
    color: inherit;
    font: inherit;
    text-align: left;
    cursor: pointer;
  }
  .strip .who strong {
    font-size: 17px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .strip .who span {
    font-size: 13px;
    color: var(--ash);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .quick {
    display: flex;
    gap: 6px;
    flex-shrink: 0;
  }
  .quick .round {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
  }
  .quick button {
    min-height: 40px;
    padding: 0 14px;
    font-size: 14px;
  }
  @media (max-width: 700px) {
    .page {
      padding: 10px 12px 16px;
      gap: 8px;
    }
    .letters {
      display: none;
    }
    /* The dial fills what's left of the screen above the strip and the tab bar. */
    .stage {
      height: clamp(300px, calc(100svh - 360px), 460px);
    }
    /* Deck and scan filters in one row that scrolls sideways. */
    .filters {
      flex-wrap: nowrap;
      overflow-x: auto;
      scrollbar-width: none;
    }
    .decks {
      flex-wrap: nowrap;
      flex-shrink: 0;
    }
    .segmented {
      margin-left: 0;
      flex-shrink: 0;
    }
    .hint {
      display: none;
    }
    .controls {
      gap: 8px;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .slot,
    .fill {
      transition: none;
    }
  }
</style>
