<script lang="ts">
  import { api, describe, type ContactInput, type ReviewItem } from './api'
  import ContactForm from './ContactForm.svelte'

  let { onchange }: { onchange?: () => void } = $props()

  let items = $state<ReviewItem[]>([])
  let index = $state(0)
  let form = $state<ContactInput | null>(null)
  let showBack = $state(false)
  let busy = $state(false)
  let error = $state('')

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

  let lastEvent = ''
  $effect(() => {
    if (current) {
      const next = toForm(current)
      next.event = lastEvent // keep the deck while working through a stack
      form = next
      showBack = false
    } else {
      form = null
    }
  })

  async function approve() {
    if (!current || !form) return
    busy = true
    try {
      lastEvent = form.event
      const cleaned = {
        ...form,
        emails: form.emails.filter(Boolean),
        phones: form.phones.filter(Boolean),
        websites: form.websites.filter(Boolean),
      }
      await api.approve(current.card_id, cleaned)
      await load()
      if (index >= ready.length) index = Math.max(0, ready.length - 1)
      onchange?.()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  async function dismiss() {
    if (!current) return
    busy = true
    try {
      await api.dismiss(current.card_id)
      await load()
      onchange?.()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }
</script>

<div class="wrap">
  <h1>Review <span class="count">{ready.length} ready{waiting.length ? `, ${waiting.length} being read` : ''}</span></h1>
  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if !current}
    <p class="empty">Nothing to review. New scans appear here after they are read.</p>
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
        <p class="pos">{index + 1} of {ready.length}</p>
      </section>
      <section class="details" aria-label="Contact details">
        <ContactForm bind:value={form} flags={current.flags} idPrefix="review" />
        <div class="buttons">
          <button type="button" class="secondary" onclick={dismiss} disabled={busy}>Dismiss</button>
          <button type="button" class="primary" onclick={approve} disabled={busy || !form.full_name.trim()}>
            {busy ? 'Saving…' : 'Approve and save'}
          </button>
        </div>
      </section>
    </div>
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
</style>
