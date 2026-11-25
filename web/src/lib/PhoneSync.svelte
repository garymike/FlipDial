<script lang="ts">
  // Phone sync settings (docs/sync.md): which contacts go to the phone book, and syncing.
  import { api, describe, type PhonePending, type PhoneStatus } from './api'
  import PhoneWizard from './PhoneWizard.svelte'

  let wizard = $state<'' | 'book' | 'phone'>('')
  let st = $state<PhoneStatus | null>(null)
  let counts = $state<[string, number][]>([])
  let busy = $state(false)
  let error = $state('')
  let note = $state('')
  let pending = $state<PhonePending | null>(null)

  async function load() {
    try {
      st = await api.phone()
      pending = st.pending ?? null
      if (st.enabled) {
        const list = await api.contacts()
        const n = new Map<string, number>([['Starred', list.starred]])
        for (const c of list.contacts) for (const t of c.categories) n.set(t, (n.get(t) ?? 0) + 1)
        counts = [...n].filter(([, k]) => k > 0).sort((a, b) => (a[0] === 'Starred' ? -1 : b[0] === 'Starred' ? 1 : a[0].localeCompare(b[0])))
      }
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }
  $effect(() => {
    load()
    const again = () => load()
    window.addEventListener('flipdial:server-changed', again)
    return () => window.removeEventListener('flipdial:server-changed', again)
  })

  async function turnOff() {
    try {
      await api.phoneSetupOff()
      await load()
    } catch (e) {
      error = describe(e)
    }
  }

  async function setSchedule(mode: 'auto' | 'manual', drift: 'off' | 'daily' | 'weekly') {
    try {
      st = await api.phoneSchedule(mode, drift)
      window.dispatchEvent(new CustomEvent('flipdial:server-changed'))
    } catch (e) {
      error = describe(e)
    }
  }
  let checking = $state(false)
  async function checkDrift() {
    checking = true
    try {
      st = await api.phoneDriftCheck()
    } catch (e) {
      error = describe(e)
    } finally {
      checking = false
    }
  }
  const behind = $derived((st?.drift_result?.to_phone ?? 0) + (st?.drift_result?.from_phone ?? 0))

  async function rule(name: string, state: 'on' | 'off' | 'follow') {
    try {
      st = await api.phoneRule(name, state)
      note = ''
    } catch (e) {
      error = describe(e)
    }
  }

  async function sync(body: { confirm?: string; accept_drop?: boolean } = {}) {
    busy = true
    note = ''
    try {
      const r = await api.phoneSync(body)
      st = r.state
      pending = r.status === 'confirm' ? (r.state.pending ?? null) : null
      if (r.status === 'done') {
        const parts = [
          r.added && `${r.added} added`,
          r.updated && `${r.updated} updated`,
          r.removed && `${r.removed} removed from the phone`,
          r.switched_off && `${r.switched_off} switched off (deleted on the phone)`,
          r.from_phone && `${r.from_phone} edited on the phone, now in FlipDial`,
          r.to_review && `${r.to_review} waiting in Review`,
        ].filter(Boolean)
        note = parts.length ? `Synced: ${parts.join(', ')}.` : 'The phone book is up to date.'
      } else if (r.status === 'busy') {
        note = 'A sync is already running. Try again in a minute.'
      }
      error = ''
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  const PROBLEMS: Record<string, string> = {
    master_dropped: 'Your contacts server has far fewer contacts than at the last sync, so nothing was sent to the phone.',
    phone_dropped: 'Many contacts disappeared from the phone book at once, so nothing was changed.',
    auth_failed: "FlipDial couldn't sign in to the contacts server.",
    address_book_not_found: "The phone book wasn't found on the contacts server. Check its name.",
    server_unreachable: "The contacts server couldn't be reached.",
  }
  const when = (iso?: string | null) => (iso ? new Date(iso).toLocaleString() : 'never')
  const ruleOf = (name: string) => st?.tags?.[name] ?? 'follow'
  const listed = (xs: { name: string }[]) =>
    xs.slice(0, 12).map((x) => x.name || 'No name').join(', ') + (xs.length > 12 ? `, and ${xs.length - 12} more` : '')
</script>

<section class="phone" aria-label="Phone">
  <h2>Phone</h2>
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if wizard}
    {#key wizard}<PhoneWizard start={wizard} ondone={load} />{/key}
    <button type="button" class="secondary" onclick={() => { wizard = ''; load() }}>Close setup</button>
  {/if}
  {#if st && !st.enabled}
    <p class="detail">
      Send only the contacts you choose to your phone, so its address book stays short. Nothing is connected to your
      Google or Apple account, and the phone syncs on your home network.
      <a href="https://github.com/garymike/FlipDial/blob/main/docs/sync.md" target="_blank" rel="noreferrer">How phone sync works</a>
    </p>
    {#if !wizard}<button type="button" class="primary" onclick={() => (wizard = 'book')}>Set up phone sync</button>{/if}
  {:else if st}
    {#if !wizard}
      <div class="row">
        <button type="button" class="secondary" onclick={() => (wizard = 'phone')}>Add a phone</button>
        <button type="button" class="secondary" onclick={() => (wizard = 'book')}>Name, sign-in or address book</button>
        <button type="button" class="secondary" onclick={turnOff}>Turn off phone sync</button>
      </div>
    {/if}
    <div class="when">
      <span class="label">When to sync</span>
      <div class="segmented" role="group" aria-label="When to sync">
        <button type="button" aria-pressed={st.mode !== 'manual'} onclick={() => setSchedule('auto', st?.drift ?? 'weekly')}>On its own</button>
        <button type="button" aria-pressed={st.mode === 'manual'} onclick={() => setSchedule('manual', st?.drift ?? 'weekly')}>Only when I press Sync now</button>
      </div>
      {#if st.mode === 'manual'}
        <label class="drift">
          Check whether the phone is behind
          <select value={st.drift ?? 'weekly'} onchange={(e) => setSchedule('manual', (e.currentTarget as HTMLSelectElement).value as 'off' | 'daily' | 'weekly')}>
            <option value="weekly">every week</option>
            <option value="daily">every day</option>
            <option value="off">never</option>
          </select>
        </label>
      {/if}
    </div>
    <p class="detail">
      {st.on_phone} on your phone now, {st.wanted} after the next sync. Last synced {when(st.last_success)}.
      {#if st.mode === 'manual'}
        Nothing is sent until you press Sync now (here, or next to Review).
      {:else}
        FlipDial looks for changes every {st.check_minutes ?? 5} minutes and does a full check every day after
        {st.check_hour}:00. Use Sync now (here, or next to Review) when you don't want to wait.
      {/if}
    </p>
    {#if st.mode === 'manual' && st.drift_result}
      <p class="detail" class:behind={behind > 0}>
        {#if st.drift_result.problem}
          Couldn't check the phone ({st.drift_result.problem}).
        {:else if behind > 0}
          Your phone is behind: {st.drift_result.to_phone} {st.drift_result.to_phone === 1 ? 'change' : 'changes'} to send{#if st.drift_result.from_phone},
            {st.drift_result.from_phone} from the phone{/if}. Press Sync now when you're ready.
        {:else}
          Your phone is up to date.
        {/if}
        <span class="muted">Checked {when(st.drift_result.checked_at)}.</span>
        <button type="button" class="link" disabled={checking} onclick={checkDrift}>{checking ? 'Checking…' : 'Check now'}</button>
      </p>
    {/if}

    {#if st.problem}
      <div class="box warn" role="alert">
        <p>{PROBLEMS[st.problem.code] ?? `Phone sync stopped (${st.problem.code}).`}
          {#if st.problem.before !== undefined}({st.problem.before} before, {st.problem.now} now.){/if}</p>
        {#if st.problem.code === 'master_dropped' || st.problem.code === 'phone_dropped'}
          <button type="button" class="secondary" disabled={busy} onclick={() => sync({ accept_drop: true })}>
            I removed them on purpose. Continue
          </button>
        {/if}
      </div>
    {/if}

    {#if st.waiting}
      <p class="detail"><a href="#/review">{st.waiting} from your phone waiting in Review.</a></p>
    {/if}

    {#if pending}
      <div class="box" role="group" aria-label="Changes to confirm">
        <p><strong>{pending.first ? 'First sync to the phone.' : 'Check these changes first.'}</strong></p>
        {#if pending.add.length}<p>Add {pending.add.length}: {listed(pending.add)}</p>{/if}
        {#if pending.update}<p>Update {pending.update}.</p>{/if}
        {#if pending.remove.length}<p>Remove from the phone {pending.remove.length}: {listed(pending.remove)}</p>{/if}
        {#if pending.pull?.length}<p>Take in edits made on the phone {pending.pull.length}: {listed(pending.pull)}</p>{/if}
        {#if pending.gone.length}<p>Deleted on the phone, so switched off {pending.gone.length}: {listed(pending.gone)}</p>{/if}
        <p class="detail">Contacts stay in FlipDial either way.</p>
        <div class="row">
          <button type="button" class="primary" disabled={busy} onclick={() => sync({ confirm: pending?.token })}>Send to phone</button>
          <button type="button" class="secondary" onclick={() => (pending = null)}>Not now</button>
        </div>
      </div>
    {/if}

    <label class="check">
      <input type="checkbox" checked={st.everything} onchange={(e) => rule('*', e.currentTarget.checked ? 'on' : 'off')} />
      Every contact
    </label>
    <table>
      <thead><tr><th>Tag or deck</th><th>Contacts</th><th>On the phone</th></tr></thead>
      <tbody>
        {#each counts as [name, n] (name)}
          <tr>
            <td>{name}</td>
            <td>{n}</td>
            <td>
              <select aria-label={`${name} on the phone`} value={ruleOf(name)} onchange={(e) => rule(name, e.currentTarget.value as 'on' | 'off' | 'follow')}>
                <option value="follow">{st.everything ? 'Yes (every contact)' : 'No'}</option>
                <option value="on">Yes</option>
                {#if st.everything || ruleOf(name) === 'off'}<option value="off">No</option>{/if}
              </select>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
    <p class="detail">A contact's own choice in its card wins over these.</p>
    <div class="row">
      <button type="button" class="secondary" disabled={busy} onclick={() => sync()}>{busy ? 'Syncing…' : 'Sync now'}</button>
      {#if note}<span role="status">{note}</span>{/if}
    </div>
  {/if}
</section>

<style>
  .phone {
    display: flex;
    flex-direction: column;
    gap: 10px;
    margin-top: 0;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid #2c2f36;
    background: var(--panel);
  }
  h2 {
    margin: 0;
    font-size: 16px;
  }
  .detail {
    margin: 0;
    color: var(--ash);
    font-size: 14px;
    line-height: 1.5;
  }
  .box {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1px solid var(--line);
  }
  .box.warn {
    border-color: var(--amber);
    background: #2a241a;
  }
  .box p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 10px;
  }
  .check {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
  }
  .check input {
    accent-color: var(--amber);
    width: 18px;
    height: 18px;
  }
  table {
    border-collapse: collapse;
    font-size: 14px;
  }
  th {
    text-align: left;
    font-weight: 500;
    color: var(--ash);
    font-size: 12px;
    padding: 4px 8px 4px 0;
  }
  td {
    padding: 4px 8px 4px 0;
    border-top: 1px solid var(--line);
  }
  select {
    min-height: 34px;
    padding: 0 8px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
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
    color: var(--amber);
    margin: 0;
  }
  .when {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 12px;
    font-size: 14px;
  }
  .when .label {
    color: var(--ash);
  }
  .drift select {
    margin-left: 6px;
    padding: 4px 8px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
  }
  .segmented {
    display: inline-flex;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  .segmented button {
    min-height: 34px;
    padding: 0 12px;
    border: 0;
    background: transparent;
    color: var(--ash);
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .segmented button[aria-pressed='true'] {
    background: var(--graphite);
    color: var(--bone);
  }
  .behind {
    color: var(--amber);
  }
  .muted {
    color: var(--ash);
  }
  .link {
    margin-left: 6px;
    padding: 0;
    border: 0;
    background: none;
    color: var(--amber);
    font: inherit;
    text-decoration: underline;
    cursor: pointer;
  }
</style>
