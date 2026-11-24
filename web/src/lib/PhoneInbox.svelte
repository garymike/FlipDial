<script lang="ts">
  // Decisions from phone sync (docs/sync.md): contacts added on the phone, and contacts
  // whose same field was changed both on the phone and in FlipDial.
  import { api, describe, type PhoneInboxItem } from './api'

  let { onchange }: { onchange?: () => void } = $props()
  let items = $state<PhoneInboxItem[]>([])
  let busy = $state(false)
  let error = $state('')

  async function load() {
    try {
      items = (await api.phoneInbox()).items
    } catch {
      items = []
    }
  }
  $effect(() => {
    load()
  })

  async function act(item: PhoneInboxItem, action: 'accept' | 'dismiss') {
    busy = true
    try {
      await api.phoneInboxAction(item.id, action)
      error = ''
      await load()
      onchange?.()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }
</script>

{#if items.length}
  <section class="inbox" aria-label="From your phone">
    <h2>From your phone <span class="n">{items.length}</span></h2>
    {#if error}<p class="error" role="alert">{error}</p>{/if}
    {#each items as item (item.id)}
      <article class="item">
        {#if item.kind === 'added'}
          <p class="what"><strong>{item.name || 'No name'}</strong> was added on your phone.</p>
          <dl>
            {#each item.fields.filter((f) => f.field !== 'Name') as f (f.field)}
              <dt>{f.field}</dt><dd>{f.phone}</dd>
            {/each}
          </dl>
          <div class="row">
            <button type="button" class="primary" disabled={busy} onclick={() => act(item, 'accept')}>Save to FlipDial</button>
            <button type="button" class="secondary" disabled={busy} onclick={() => act(item, 'dismiss')}>Leave it on the phone only</button>
          </div>
        {:else}
          <p class="what"><strong>{item.name}</strong> was changed on your phone and in FlipDial.</p>
          <table>
            <thead><tr><th></th><th>On your phone</th><th>In FlipDial</th></tr></thead>
            <tbody>
              {#each item.fields as f (f.field)}
                <tr><th scope="row">{f.field}</th><td>{f.phone || '(empty)'}</td><td>{f.flipdial || '(empty)'}</td></tr>
              {/each}
            </tbody>
          </table>
          <p class="hint">Other edits made on the phone are kept either way.</p>
          <div class="row">
            <button type="button" class="primary" disabled={busy} onclick={() => act(item, 'accept')}>Use the phone's</button>
            <button type="button" class="secondary" disabled={busy} onclick={() => act(item, 'dismiss')}>Keep FlipDial's</button>
          </div>
        {/if}
      </article>
    {/each}
  </section>
{/if}

<style>
  .inbox {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-bottom: 18px;
  }
  h2 {
    margin: 0;
    font-size: 16px;
  }
  .n {
    color: var(--ash);
    font-weight: 400;
  }
  .item {
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid var(--line);
    background: var(--panel);
  }
  .what,
  .hint {
    margin: 0;
    font-size: 14px;
  }
  .hint {
    color: var(--ash);
    font-size: 13px;
  }
  dl {
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 4px 12px;
    margin: 0;
    font-size: 13px;
  }
  dt,
  th {
    color: var(--ash);
    font-weight: 400;
    text-align: left;
  }
  dd {
    margin: 0;
    white-space: pre-line;
  }
  table {
    border-collapse: collapse;
    font-size: 13px;
  }
  td,
  th {
    padding: 4px 12px 4px 0;
    vertical-align: top;
    white-space: pre-line;
  }
  thead th {
    font-size: 12px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .primary,
  .secondary {
    min-height: 40px;
    padding: 0 16px;
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
    color: var(--amber);
  }
</style>
