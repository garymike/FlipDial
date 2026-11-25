<script lang="ts">
  // Setup check: everything FlipDial needs, whether it's in place, and what to do if not.
  import { api, describe, type SetupStatus, type UpdateInfo } from './api'
  import ContactsServer from './ContactsServer.svelte'
  import PhoneSync from './PhoneSync.svelte'

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
    const again = () => run()
    window.addEventListener('flipdial:server-changed', again)
    return () => window.removeEventListener('flipdial:server-changed', again)
  })

  // Updates: the version running here, and a way to look for a new release right now.
  let upd = $state<UpdateInfo | null>(null)
  let updChecking = $state(false)
  let updNote = $state('')
  $effect(() => {
    api.updateInfo().then((u) => (upd = u)).catch(() => {})
  })
  async function checkNow() {
    updChecking = true
    updNote = ''
    try {
      upd = await api.checkUpdate()
      window.dispatchEvent(new CustomEvent('flipdial:update-checked', { detail: upd }))
      updNote = upd.available
        ? `FlipDial ${upd.release?.tag} is available. See the bar at the top of the page.`
        : upd.error
          ? "Couldn't reach GitHub to check. Try again later."
          : "You have the newest version."
    } catch (e) {
      updNote = describe(e)
    } finally {
      updChecking = false
    }
  }

  // Removing contacts the server no longer has: asks once more before doing it.
  let dropAsk = $state(false)
  async function allowDrop() {
    if (!dropAsk) {
      dropAsk = true
      return
    }
    pushing = true
    try {
      const r = await api.syncAllowDrop()
      pushed = `Removed ${r.removed} from FlipDial.`
      dropAsk = false
      await run()
    } catch (e) {
      error = describe(e)
    } finally {
      pushing = false
    }
  }

  async function repick() {
    pushing = true
    try {
      await api.repickMainBook()
      const r = await api.sync()
      pushed = `FlipDial picked its address book again and found ${r.added ?? 0} new contacts.`
      await run()
    } catch (e) {
      error = describe(e)
    } finally {
      pushing = false
    }
  }

  let pushing = $state(false)
  let pushed = $state('')
  async function pushLocal() {
    pushing = true
    try {
      const r = await api.pushLocal()
      pushed =
        `Copied ${r.copied} to the server.` +
        (r.already_there ? ` ${r.already_there} were already there.` : '') +
        (r.failed ? ` ${r.failed} couldn't be copied; try again.` : '')
      await run()
    } catch (e) {
      error = describe(e)
    } finally {
      pushing = false
    }
  }

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
  {#if pushed}<p class="summary ok" role="status">{pushed}</p>{/if}
  {#if status}
    <p class="summary {status.state}" role="status">{SUMMARY[status.state]}</p>
    <ul class="items">
      {#each status.items as item (item.id)}
        <li class={item.state}>
          <span class="icon" aria-hidden="true">{ICON[item.state]}</span>
          <strong>{item.label}</strong>
          <span class="detail">{item.detail}</span>
          {#if item.fix || item.action}
            <div class="more">
              {#if item.fix}<span class="fix">{item.fix}</span>{/if}
              {#if item.action === 'push_local'}
                <button type="button" class="secondary act" onclick={pushLocal} disabled={pushing}>
                  {pushing ? 'Copying…' : item.action_label}
                </button>
              {:else if item.action === 'repick_book'}
                <button type="button" class="secondary act" onclick={repick} disabled={pushing}>{item.action_label}</button>
              {:else if item.action === 'allow_drop'}
                <button type="button" class="secondary act" onclick={allowDrop} disabled={pushing}>
                  {dropAsk ? `Yes, ${item.action_label?.toLowerCase()}` : item.action_label}
                </button>
              {/if}
            </div>
          {/if}
        </li>
      {/each}
    </ul>
  {/if}

  <section class="updates" aria-label="Updates">
    <h2>Updates</h2>
    <span class="detail">
      {#if updNote}<span role="status">{updNote}</span>{:else}FlipDial {upd?.current ?? '…'}{#if upd && !upd.enabled}. Checking
          for new versions is turned off (FLIPDIAL_UPDATE_CHECK=false).{/if}{/if}
    </span>
    {#if !upd || upd.enabled}
      <button type="button" class="secondary small" onclick={checkNow} disabled={updChecking}>
        {updChecking ? 'Checking…' : 'Check now'}
      </button>
    {/if}
  </section>

  <ContactsServer />
  <PhoneSync />
</div>

<style>
  .updates {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 6px 14px;
    padding: 8px 8px 8px 16px;
    border-radius: 12px;
    border: 1px solid #2c2f36;
    background: var(--panel);
  }
  .updates h2 {
    margin: 0;
    font-size: 14px;
  }
  .updates .detail {
    flex: 1 1 auto;
    text-align: right;
    color: var(--ash);
    font-size: 13px;
  }
  .updates button.small {
    min-height: 32px;
    padding: 0 12px;
    font-size: 13px;
  }
  .wrap {
    max-width: 820px;
    margin: 0 auto;
    padding: 20px 32px 48px;
    display: flex;
    flex-direction: column;
    gap: 12px;
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
    font-size: 24px;
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
    padding: 8px 14px;
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
    /* One line per item: icon, name, and the details to the right in grey. */
    display: grid;
    grid-template-columns: 20px auto 1fr;
    align-items: center;
    column-gap: 12px;
    padding: 9px 16px;
    border-bottom: 1px solid #2a2d33;
  }
  .items li:last-child {
    border-bottom: 0;
  }
  .items li strong {
    font-size: 14px;
    white-space: nowrap;
  }
  .items li .detail {
    justify-self: end;
    text-align: right;
    color: var(--ash);
    font-size: 13px;
    min-width: 0;
  }
  .more {
    grid-column: 2 / -1;
    display: flex;
    flex-direction: column;
    gap: 4px;
    margin-top: 4px;
  }
  .icon {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    display: grid;
    place-items: center;
    font-size: 11px;
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
  .act {
    align-self: flex-start;
    margin-top: 6px;
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
    .items li {
      grid-template-columns: 20px 1fr;
    }
    .items li .detail {
      grid-column: 2;
      justify-self: start;
      text-align: left;
    }
  }
</style>
