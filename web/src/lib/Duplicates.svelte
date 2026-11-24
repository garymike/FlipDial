<script lang="ts">
  // Possible duplicates: review each pair, pick the values to keep, merge, and undo if needed.
  import { api, describe, kindName, REASONS, type Contact, type ContactInput, type DuplicatePair, type MergeRecord } from './api'
  import FlipCard from './FlipCard.svelte'
  import ScanImage from './ScanImage.svelte'
  import { contactHref } from './router.svelte'

  let pairs = $state<DuplicatePair[]>([])
  let merges = $state<MergeRecord[]>([])
  let loaded = $state(false)
  let error = $state('')
  let notice = $state<{ text: string; mergeId?: number } | null>(null)

  // merge editor state
  let open = $state<DuplicatePair | null>(null)
  let keep = $state<'a' | 'b'>('a')
  let showCard = $state('') // when both have a scan: the card to show (both are kept)
  let pick = $state<Record<string, 'a' | 'b'>>({})
  let listPick = $state<Record<string, Record<string, boolean>>>({})
  let busy = $state(false)

  async function load() {
    try {
      const [d, m] = await Promise.all([api.duplicates(), api.merges()])
      pairs = d.pairs
      merges = m.merges.filter((x) => !x.undone).slice(0, 5)
      loaded = true
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }
  $effect(() => {
    load()
  })

  const scalars = [
    ['full_name', 'Name'],
    ['title', 'Title'],
    ['organization', 'Company'],
    ['address', 'Address'],
    ['event', 'Event deck'],
    ['met_on', 'Met on'],
  ] as const
  const lists = [
    ['emails', 'Email'],
    ['phones', 'Phone'],
    ['websites', 'Website'],
  ] as const

  function strength(score: number) {
    return score >= 0.9 ? 'Strong match' : score >= 0.75 ? 'Likely match' : 'Possible match'
  }

  function startMerge(p: DuplicatePair) {
    open = p
    keep = p.b.card_id && !p.a.card_id ? 'b' : 'a'
    // Default to the newer card (card ids start with the scan time).
    showCard = [p.a.card_id, p.b.card_id].filter((x): x is string => !!x).sort().at(-1) ?? ''
    const choice: Record<string, 'a' | 'b'> = {}
    for (const [key] of scalars) choice[key] = p.a[key] ? 'a' : p.b[key] ? 'b' : 'a'
    pick = choice
    const lp: Record<string, Record<string, boolean>> = {}
    for (const [key] of lists) {
      lp[key] = {}
      for (const v of [...p.a[key], ...p.b[key]]) lp[key][v.value] = true
    }
    listPick = lp
  }

  function valuesFor(key: (typeof lists)[number][0]) {
    if (!open) return []
    const seen = new Set<string>()
    return [...open.a[key], ...open.b[key]].filter((v) => {
      const k = v.value.toLowerCase()
      if (seen.has(k)) return false
      seen.add(k)
      return true
    })
  }

  function result(p: DuplicatePair): ContactInput {
    const side = (key: string) => (pick[key] === 'b' ? p.b : p.a) as Contact
    const chosen = (key: (typeof lists)[number][0]) => valuesFor(key).filter((v) => listPick[key]?.[v.value])
    const socials = [...p.a.socials, ...p.b.socials].filter(
      (s, i, all) => all.findIndex((x) => x.handle === s.handle) === i,
    )
    return {
      full_name: side('full_name').full_name,
      title: side('title').title,
      organization: side('organization').organization,
      addresses: side('address').addresses,
      about: side('about').about || p.a.about || p.b.about,
      note: [...new Set([p.a.note, p.b.note].filter(Boolean))].join('\n\n'),
      event: side('event').event,
      met_on: side('met_on').met_on,
      emails: chosen('emails'),
      phones: chosen('phones'),
      websites: chosen('websites'),
      socials,
      starred: p.a.starred || p.b.starred,
      tags: [...new Set([...p.a.categories, ...p.b.categories])].filter(
        (t) => t !== side('event').event,
      ),
    }
  }

  async function doMerge() {
    if (!open) return
    busy = true
    const p = open
    const [k, d] = keep === 'a' ? [p.a, p.b] : [p.b, p.a]
    try {
      const r = await api.merge(k.uid, d.uid, result(p), p.a.card_id && p.b.card_id ? showCard : '')
      notice = { text: `Merged into ${r.contact.full_name}.`, mergeId: r.merge_id }
      open = null
      await load()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  async function notSame(p: DuplicatePair) {
    try {
      await api.notDuplicates(p.a.uid, p.b.uid)
      notice = { text: `${p.a.full_name} and ${p.b.full_name} will not be suggested again.` }
      await load()
    } catch (e) {
      error = describe(e)
    }
  }

  async function undo(id: number) {
    try {
      await api.undoMerge(id)
      notice = { text: 'Merge undone. Both contacts are back.' }
      await load()
    } catch (e) {
      error = describe(e)
    }
  }
</script>

<div class="wrap">
  <h1>Possible duplicates <span class="count">{pairs.length}</span></h1>
  <p class="lead">Nothing is merged unless you choose to. Every merge can be undone.</p>

  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if notice}
    <div class="notice" role="status">
      <span>{notice.text}</span>
      {#if notice.mergeId}<button type="button" class="link" onclick={() => undo(notice!.mergeId!)}>Undo</button>{/if}
      <button type="button" class="link" aria-label="Close message" onclick={() => (notice = null)}>×</button>
    </div>
  {/if}

  {#if loaded && pairs.length === 0}
    <p class="empty">No duplicates found. Your contacts look tidy.</p>
  {/if}

  <ul class="pairs">
    {#each pairs as p (p.a.uid + p.b.uid)}
      <li class="pair" class:active={open === p}>
        <div class="head">
          <span class="strength">{strength(p.score)}</span>
          <ul class="reasons">{#each p.reasons as r (r)}<li>{REASONS[r] ?? r}</li>{/each}</ul>
        </div>
        <div class="sides">
          {#each [p.a, p.b] as c (c.uid)}
            <div class="side">
              <FlipCard contact={c} />
              <a href={contactHref(c.uid)}>{c.full_name}</a>
              <span class="sub">{[c.organization, c.emails[0]?.value].filter(Boolean).join(' · ')}</span>
            </div>
          {/each}
        </div>

        {#if open === p}
          <form class="editor" onsubmit={(e) => { e.preventDefault(); doMerge() }}>
            <fieldset>
              <legend>Keep which record</legend>
              <label><input type="radio" bind:group={keep} value="a" /> {p.a.full_name} ({p.a.card_id ? 'has scan' : p.a.source})</label>
              <label><input type="radio" bind:group={keep} value="b" /> {p.b.full_name} ({p.b.card_id ? 'has scan' : p.b.source})</label>
            </fieldset>
            {#if p.a.card_id && p.b.card_id}
              <fieldset>
                <legend>Card to show <span class="hint">both are kept; the other stays in their card history</span></legend>
                <div class="cardpick">
                  {#each [p.a, p.b] as c (c.uid)}
                    <label class:chosen={showCard === c.card_id}>
                      <input type="radio" bind:group={showCard} value={c.card_id} />
                      <span class="pickimg"><ScanImage src={api.image(c.card_id ?? '', 'thumb')} alt={`Card from ${c.full_name}`} /></span>
                    </label>
                  {/each}
                </div>
              </fieldset>
            {/if}
            {#each scalars as [key, label] (key)}
              {#if p.a[key] || p.b[key]}
                <fieldset>
                  <legend>{label}</legend>
                  {#if p.a[key] === p.b[key]}
                    <span class="same">{p.a[key]}</span>
                  {:else}
                    <label><input type="radio" bind:group={pick[key]} value="a" /> {p.a[key] || '(empty)'}</label>
                    <label><input type="radio" bind:group={pick[key]} value="b" /> {p.b[key] || '(empty)'}</label>
                  {/if}
                </fieldset>
              {/if}
            {/each}
            {#each lists as [key, label] (key)}
              {#if valuesFor(key).length}
                <fieldset>
                  <legend>{label}</legend>
                  {#each valuesFor(key) as v (v.value)}
                    <label><input type="checkbox" bind:checked={listPick[key][v.value]} /> {v.value} <span class="kind">{kindName(key, v)}</span></label>
                  {/each}
                </fieldset>
              {/if}
            {/each}
            <div class="buttons">
              <button type="button" class="secondary" onclick={() => (open = null)}>Cancel</button>
              <button type="submit" class="primary" disabled={busy}>{busy ? 'Merging…' : 'Merge'}</button>
            </div>
          </form>
        {:else}
          <div class="buttons">
            <button type="button" class="secondary" onclick={() => notSame(p)}>Not the same person</button>
            <button type="button" class="primary" onclick={() => startMerge(p)}>Merge…</button>
          </div>
        {/if}
      </li>
    {/each}
  </ul>

  {#if merges.length}
    <section class="history">
      <h2>Recent merges</h2>
      <ul>
        {#each merges as m (m.id)}
          <li>
            <span>Merged {m.drop_name}</span>
            <button type="button" class="link" onclick={() => undo(m.id)}>Undo</button>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</div>

<style>
  .cardpick {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
  }
  .cardpick label {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px;
    border: 2px solid transparent;
    border-radius: 10px;
    cursor: pointer;
  }
  .cardpick label.chosen {
    border-color: var(--amber);
  }
  .pickimg {
    display: block;
    width: 160px;
    border-radius: 6px;
    overflow: hidden;
    background: #111214;
  }
  legend .hint {
    font-weight: 400;
    color: var(--ash);
    font-size: 12px;
  }
  .wrap {
    max-width: 1100px;
    margin: 0 auto;
    padding: 28px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 18px;
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
  .lead {
    margin: -8px 0 0;
    color: var(--ash);
  }
  .pairs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .pair {
    display: flex;
    flex-direction: column;
    gap: 16px;
    padding: 20px;
    border-radius: 14px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .pair.active {
    border-color: var(--amber);
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .strength {
    font-weight: 600;
  }
  .reasons {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .reasons li {
    font-size: 12px;
    padding: 4px 10px;
    border-radius: 999px;
    background: #23262c;
    border: 1px solid var(--line);
    color: #d6d1c9;
  }
  .sides {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 16px;
  }
  .side {
    display: flex;
    flex-direction: column;
    gap: 6px;
    min-width: 0;
  }
  .side a {
    color: var(--bone);
    font-weight: 600;
    text-decoration: none;
  }
  .sub {
    font-size: 13px;
    color: var(--ash);
    overflow-wrap: anywhere;
  }
  .editor {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding-top: 14px;
    border-top: 1px solid #2c2f36;
  }
  fieldset {
    margin: 0;
    padding: 0;
    border: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  legend {
    margin-bottom: 4px;
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ash);
  }
  fieldset label {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 36px;
    font-size: 15px;
    overflow-wrap: anywhere;
  }
  input[type='radio'],
  input[type='checkbox'] {
    width: 18px;
    height: 18px;
    accent-color: var(--amber);
    flex-shrink: 0;
  }
  .same {
    font-size: 15px;
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
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
  .link {
    min-height: 36px;
    padding: 0 8px;
    border: 0;
    background: transparent;
    color: var(--amber);
    font: inherit;
    cursor: pointer;
  }
  .notice {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 14px;
    border-radius: 10px;
    background: #1f2e27;
    color: #9be0bc;
  }
  .notice span {
    flex: 1;
  }
  .history h2 {
    margin: 0 0 8px;
    font-size: 12px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ash);
  }
  .history ul {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .history li {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 0;
    border-bottom: 1px solid #2c2f36;
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
  @media (max-width: 700px) {
    .wrap {
      padding: 16px;
    }
    .sides {
      grid-template-columns: 1fr;
    }
  }
</style>
