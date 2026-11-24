<script lang="ts">
  // Setup check: everything FlipDial needs, whether it's in place, and what to do if not.
  import { api, describe, type SetupStatus } from './api'

  let status = $state<SetupStatus | null>(null)
  let error = $state('')
  let checking = $state(false)

  async function run() {
    checking = true
    try {
      status = await api.status()
      error = ''
    } catch (e) {
      error = describe(e)
    } finally {
      checking = false
    }
  }
  $effect(() => {
    run()
  })

  const ICON = { ok: '✓', warn: '!', fail: '✕' } as const
  const SUMMARY = {
    ok: 'Everything FlipDial needs is in place.',
    warn: 'FlipDial works, with a few things worth setting up.',
    fail: "Something FlipDial needs isn't working. Fix the red items below.",
  } as const
</script>

<div class="wrap">
  <div class="head">
    <h1>Setup check</h1>
    <button type="button" class="secondary" onclick={run} disabled={checking}>{checking ? 'Checking…' : 'Check again'}</button>
  </div>
  <p class="lead">
    FlipDial reads cards with an AI model running on this computer (through Ollama), picks up scans with a
    background worker, and saves contacts to your contacts server.
  </p>

  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if status}
    <p class="summary {status.state}" role="status">{SUMMARY[status.state]}</p>
    <ul class="items">
      {#each status.items as item (item.id)}
        <li class={item.state}>
          <span class="icon" aria-hidden="true">{ICON[item.state]}</span>
          <div>
            <strong>{item.label}</strong>
            <span class="detail">{item.detail}</span>
            {#if item.fix}<span class="fix">{item.fix}</span>{/if}
          </div>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .wrap {
    max-width: 820px;
    margin: 0 auto;
    padding: 28px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }
  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 30px;
    font-weight: 600;
  }
  .lead {
    margin: -4px 0 0;
    color: var(--ash);
    line-height: 1.5;
  }
  .summary,
  .error {
    margin: 0;
    padding: 12px 16px;
    border-radius: 10px;
    font-size: 14px;
  }
  .summary.ok {
    background: #22302a;
    border: 1px solid #3d5a4b;
  }
  .summary.warn {
    background: #33301f;
    border: 1px solid #6a5e2e;
  }
  .summary.fail,
  .error {
    background: #3a2422;
    border: 1px solid #6b3a35;
  }
  .items {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid #2c2f36;
    border-radius: 14px;
    background: var(--panel);
  }
  .items li {
    display: flex;
    gap: 14px;
    padding: 14px 18px;
    border-bottom: 1px solid #2a2d33;
  }
  .items li:last-child {
    border-bottom: 0;
  }
  .items li div {
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .icon {
    flex: 0 0 26px;
    height: 26px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 13px;
    font-weight: 700;
    color: var(--ink);
  }
  .ok .icon {
    background: var(--sage);
  }
  .warn .icon {
    background: var(--signal);
  }
  .fail .icon {
    background: #e5776b;
  }
  .detail {
    color: #d6d1c9;
    font-size: 14px;
    overflow-wrap: anywhere;
  }
  .fix {
    color: var(--ash);
    font-size: 13px;
    line-height: 1.5;
    overflow-wrap: anywhere;
  }
  .secondary {
    min-height: 44px;
    padding: 0 18px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  @media (max-width: 640px) {
    .wrap {
      padding: 20px 16px 40px;
    }
  }
</style>
