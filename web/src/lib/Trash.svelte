<script lang="ts">
  // Trash: contacts removed from the contacts server, kept here to restore for a while.
  import { api, describe, type TrashItem } from './api'
  import Confirm from './Confirm.svelte'
  import { contactHref, href } from './router.svelte'
  import ScanImage from './ScanImage.svelte'

  let items = $state<TrashItem[] | null>(null)
  let days = $state(30)
  let error = $state('')
  let notice = $state<{ text: string; uid?: string } | null>(null)
  let busy = $state('')
  let confirmForever = $state<TrashItem | null>(null)

  async function load() {
    try {
      const r = await api.trashList()
      items = r.items
      days = r.days
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }
  $effect(() => {
    load()
  })

  async function restore(t: TrashItem) {
    busy = t.uid
    try {
      await api.restoreTrash(t.uid)
      notice = { text: `${t.full_name} is back in your contacts.`, uid: t.uid }
      await load()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = ''
    }
  }

  async function forever(t: TrashItem) {
    busy = t.uid
    try {
      await api.deleteForever(t.uid)
      notice = { text: `${t.full_name} was deleted for good.` }
      confirmForever = null
      await load()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = ''
    }
  }
</script>

<div class="wrap">
  <a class="back" href={href({ name: 'wall' })}>← Back to the wall</a>
  <h1>Trash</h1>
  <p class="lead">
    Contacts here are off your contacts server. Restore one to put it back, with its scans. Each is
    deleted for good {days} days after it was moved here.
  </p>

  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if notice}
    <p class="notice" role="status">
      {notice.text}
      {#if notice.uid}<a href={contactHref(notice.uid)}>Open</a>{/if}
    </p>
  {/if}

  {#if items && !items.length}
    <p class="empty">Trash is empty.</p>
  {:else if items}
    <ul>
      {#each items as t (t.uid)}
        <li>
          <span class="thumb">
            {#if t.card_id}<ScanImage src={api.image(t.card_id, 'thumb')} fit="fill" />{/if}
          </span>
          <div class="who">
            <strong>{t.full_name}</strong>
            {#if t.organization && t.organization !== t.full_name}<span>{t.organization}</span>{/if}
            <span class="left">
              {t.days_left === 0 ? 'Deleted for good today' : `Deleted for good in ${t.days_left} day${t.days_left === 1 ? '' : 's'}`}
            </span>
          </div>
          <div class="acts">
            <button type="button" class="secondary" onclick={() => restore(t)} disabled={busy === t.uid}>Restore</button>
            <button type="button" class="link-danger" onclick={() => (confirmForever = t)} disabled={busy === t.uid}>
              Delete forever
            </button>
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

{#if confirmForever}
  <Confirm
    title={`Delete ${confirmForever.full_name} forever?`}
    confirmLabel="Delete forever"
    danger
    busy={busy === confirmForever.uid}
    onconfirm={() => confirmForever && forever(confirmForever)}
    oncancel={() => (confirmForever = null)}
  >
    <p>This deletes their scans and history from FlipDial too. It can't be undone.</p>
    <p>Backups you already downloaded still include them.</p>
  </Confirm>
{/if}

<style>
  .wrap {
    max-width: 860px;
    margin: 0 auto;
    padding: 24px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .back {
    font-size: 14px;
    text-decoration: none;
  }
  h1 {
    margin: 0;
  }
  .lead,
  .empty {
    margin: 0;
    color: var(--ash);
  }
  .notice {
    margin: 0;
    padding: 10px 14px;
    border-radius: 10px;
    background: #1f2a22;
    border: 1px solid #2f4a36;
  }
  .notice a {
    margin-left: 8px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  li {
    display: flex;
    align-items: center;
    gap: 16px;
    padding: 12px 14px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .thumb {
    position: relative;
    flex: 0 0 96px;
    height: 56px;
    border-radius: 6px;
    overflow: hidden;
    background: #23262c;
  }
  .who {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 14px;
  }
  .who span {
    color: #d6d1c9;
  }
  .who .left {
    color: var(--ash);
    font-size: 12px;
  }
  .acts {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .link-danger {
    min-height: 40px;
    padding: 0;
    border: 0;
    background: transparent;
    color: #e5776b;
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  @media (max-width: 600px) {
    li {
      flex-wrap: wrap;
    }
  }
</style>
