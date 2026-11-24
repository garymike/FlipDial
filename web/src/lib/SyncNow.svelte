<script lang="ts">
  // Phone sync at a glance: when it last ran, and a button to sync right away.
  import { api, describe, type PhoneStatus } from './api'
  import { href } from './router.svelte'

  let { compact = false }: { compact?: boolean } = $props()
  let st = $state<PhoneStatus | null>(null)
  let busy = $state(false)
  let note = $state('')
  let now = $state(Date.now())

  async function load() {
    try {
      st = await api.phone()
    } catch {
      st = null
    }
  }
  $effect(() => {
    load()
    const every = setInterval(() => {
      now = Date.now()
      load()
    }, 60_000)
    return () => clearInterval(every)
  })

  function ago(iso?: string | null): string {
    if (!iso) return 'not yet'
    const min = Math.round((now - new Date(iso).getTime()) / 60_000)
    if (min < 1) return 'just now'
    if (min < 60) return `${min} min ago`
    const h = Math.round(min / 60)
    return h < 24 ? `${h} h ago` : new Date(iso).toLocaleDateString()
  }

  async function sync() {
    busy = true
    note = ''
    try {
      const r = await api.phoneSync({})
      st = r.state
      now = Date.now()
      note =
        r.status === 'confirm'
          ? 'Waiting for you'
          : r.status === 'stopped'
            ? 'Stopped'
            : r.status === 'busy'
              ? 'Already syncing'
              : ''
      window.dispatchEvent(new CustomEvent('flipdial:server-changed'))
    } catch (e) {
      note = describe(e)
    } finally {
      busy = false
    }
  }
</script>

{#if st?.enabled}
  <span class="sync" class:compact>
    <button type="button" onclick={sync} disabled={busy} aria-label="Sync with your phone now" title="Sync with your phone now">
      <svg class:spin={busy} width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4" /></svg>
      {#if compact}Sync phone now{/if}
    </button>
    <small aria-live="polite">
      {#if note}<a href={href({ name: 'setup' })}>{note}</a>
      {:else if st.problem || st.pending}<a href={href({ name: 'setup' })}>Needs a look</a>
      {:else if st.last_success}Phone synced {ago(st.last_success)}
      {:else}Phone not synced yet{/if}
    </small>
  </span>
{/if}

<style>
  .sync {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--ash);
    white-space: nowrap;
  }
  small {
    font-size: 12px;
  }
  small a {
    color: var(--amber);
  }
  button {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 6px;
    border: 0;
    border-radius: 8px;
    background: transparent;
    color: var(--bone);
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  button:hover {
    background: var(--graphite);
  }
  .compact {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
    padding: 4px 0;
  }
  .compact button {
    padding: 8px 0;
  }
  .spin {
    animation: spin 1s linear infinite;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .spin {
      animation: none;
    }
  }
</style>
