<script lang="ts">
  // FlipDial's built-in contacts server: one button, with what it means explained first.
  import { api, describe, type BuiltinServer } from './api'

  let st = $state<BuiltinServer | null>(null)
  let choice = $state('')
  let other = $state('')
  let busy = $state(false)
  let error = $state('')
  let confirmOff = $state(false)
  let changing = $state(false)

  async function load() {
    try {
      st = await api.builtinServer()
      choice = st.host || st.suggestions[0]?.host || '__other'
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }
  $effect(() => {
    load()
  })

  const host = $derived(choice === '__other' ? other.trim() : choice)

  async function run(fn: () => Promise<BuiltinServer>) {
    busy = true
    try {
      st = await fn()
      error = ''
      confirmOff = false
      changing = false
      window.dispatchEvent(new CustomEvent('flipdial:server-changed'))
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  const PROBLEMS: Record<string, string> = {
    stopped_unexpectedly: 'It stopped unexpectedly and is being started again.',
    away_from_home:
      "Phones can't reach it right now: this computer doesn't have the address they use (it isn't on your home network, or its address changed). FlipDial itself keeps working, and phones can connect again once it's back on that address.",
    could_not_start: "It couldn't start. Restart FlipDial; if it keeps happening, see the contacts server log in the data folder.",
  }
</script>

{#if st?.available}
  <section class="server" aria-label="Contacts server">
    <h2>Contacts server</h2>
    {#if error}<p class="error" role="alert">{error}</p>{/if}

    {#if !st.on}
      <p class="detail">
        Your phone syncs contacts with a contacts server. If you don't have one (such as Synology Contacts or Nextcloud),
        FlipDial can run one on this computer. You need it only for syncing with phones.
      </p>

      <fieldset>
        <legend>How your phone reaches this computer</legend>
        {#each st.suggestions as sug (sug.host)}
          <label class="opt"><input type="radio" bind:group={choice} value={sug.host} /> <strong>{sug.host}</strong> <span class="hint">{sug.note}</span></label>
        {/each}
        <label class="opt">
          <input type="radio" bind:group={choice} value="__other" /> Another name or address
          <input aria-label="Another name or address" bind:value={other} maxlength="253" onfocus={() => (choice = '__other')} />
        </label>
      </fieldset>
      <p class="hint">
        If your router sometimes gives this computer a new address, reserve this one for it in the router's settings (often
        called a DHCP reservation). Otherwise phones lose the connection when it changes.
      </p>

      <div class="know">
        <h3>Good to know</h3>
        <ul>
          <li>
            <strong>Home network only.</strong> It listens only on this computer and on the address you pick here. On other
            networks, like a café or hotel Wi-Fi, it answers only on this computer, so FlipDial keeps working and nothing else
            can reach it. Devices on your
            Wi-Fi can reach it, but need a password to see anything, and each phone's account sees only its own contacts. Never
            forward port {st.port} on your router.
          </li>
          <li>
            <strong>Encrypted.</strong> It uses HTTPS with a certificate made for this server only. Your phone is asked to
            trust it once. That certificate can vouch only for this server's addresses, and the key that made it is deleted
            right away, so it can't be used to pretend to be any other website.
          </li>
          <li>
            <strong>Your contacts stay here,</strong> as plain files in FlipDial's data folder (contacts-server). Include that
            folder in your backups, or use FlipDial's backup.
          </li>
          <li>FlipDial keeps its own password for the server in a private file in that folder, so it can sign in.</li>
        </ul>
      </div>

      {#if st.windows}
        <div class="know ask">
          <h3>Windows will ask you a question</h3>
          <p>
            When it starts, Windows Security asks whether to allow Python (which runs FlipDial) on networks.
          </p>
          <ul>
            <li><strong>Why:</strong> your phone connects to this computer to sync contacts, and Windows has to let that connection in.</li>
            <li><strong>Choose Private networks</strong> (your home). Leave <strong>Public networks</strong> unticked, so nobody on café, hotel or airport Wi-Fi can reach it.</li>
            <li>
              <strong>If you choose Cancel,</strong> FlipDial still works on this computer, but phones can't sync. You can change
              it later in Windows Security, Firewall &amp; network protection, Allow an app through firewall.
            </li>
          </ul>
        </div>
      {:else if st.docker}
        <p class="hint">With Docker, publish port {st.port} in your compose file (see docker/compose.example.yml) so phones can reach it.</p>
      {/if}

      <button type="button" class="primary" disabled={busy || !host} onclick={() => run(() => api.builtinServerOn(host))}>
        {busy ? 'Setting it up…' : 'Turn on the built-in contacts server'}
      </button>
    {:else}
      <p class="detail">
        {#if st.running}✓ Running. Phones reach it at <strong>https://{st.host}:{st.port}</strong>.
        {:else}Starting…{/if}
        {#if st.problem}<span class="warn">{PROBLEMS[st.problem] ?? st.problem}</span>{/if}
      </p>
      <p class="hint">Next: set up your phone under Phone below.</p>

      {#if changing}
        <fieldset>
          <legend>New address for phones</legend>
          {#each st.suggestions as sug (sug.host)}
            <label class="opt"><input type="radio" bind:group={choice} value={sug.host} /> {sug.host}</label>
          {/each}
          <label class="opt">
            <input type="radio" bind:group={choice} value="__other" /> Other
            <input aria-label="Other address" bind:value={other} maxlength="253" onfocus={() => (choice = '__other')} />
          </label>
        </fieldset>
        <p class="warn">A new address needs a new certificate, so phones already set up have to be set up again.</p>
        <div class="row">
          <button type="button" class="primary" disabled={busy || !host || host === st.host} onclick={() => run(() => api.builtinServerOn(host))}>Use this address</button>
          <button type="button" class="secondary" onclick={() => (changing = false)}>Cancel</button>
        </div>
      {:else if confirmOff}
        <p class="warn">
          This stops the contacts server and phones stop syncing. Your contacts stay in its folder and come back when you
          turn it on again.
        </p>
        <div class="row">
          <button type="button" class="secondary" disabled={busy} onclick={() => run(() => api.builtinServerOff())}>Turn it off</button>
          <button type="button" class="secondary" onclick={() => (confirmOff = false)}>Keep it on</button>
        </div>
      {:else}
        <div class="row">
          <button type="button" class="secondary" onclick={() => (changing = true)}>Change the address</button>
          <button type="button" class="secondary" onclick={() => (confirmOff = true)}>Turn off</button>
        </div>
      {/if}
    {/if}
  </section>
{/if}

<style>
  .server {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 12px;
    padding: 18px 20px;
    border-radius: 12px;
    border: 1px solid #2c2f36;
    background: var(--panel);
  }
  h2 {
    margin: 0;
    font-size: 16px;
  }
  h3 {
    margin: 0 0 6px;
    font-size: 14px;
  }
  .detail,
  .hint,
  .warn,
  p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
  }
  .hint {
    color: var(--ash);
    font-size: 13px;
  }
  .warn {
    color: var(--amber);
  }
  fieldset {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0;
    padding: 0;
    border: 0;
  }
  legend {
    font-size: 12px;
    color: var(--ash);
    margin-bottom: 4px;
  }
  .opt {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    font-size: 14px;
  }
  .opt input:not([type='radio']) {
    min-height: 36px;
    padding: 0 10px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
  }
  .know {
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid var(--line);
  }
  .know.ask {
    border-color: var(--amber);
  }
  .know ul {
    margin: 0;
    padding-left: 18px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 14px;
    line-height: 1.5;
  }
  .know p {
    margin-bottom: 6px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }
  .primary,
  .secondary {
    align-self: flex-start;
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
  .primary:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .secondary {
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
  }
  .error {
    color: var(--amber);
  }
</style>
