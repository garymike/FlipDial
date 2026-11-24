<script lang="ts">
  // Phone sync settings (docs/sync.md): which contacts go to the phone book, and syncing.
  import { api, describe, type PhonePending, type PhoneStatus } from './api'

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
  })

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
  {#if st && !st.enabled}
    <p class="detail">
      Send only the contacts you choose to your phone, so its address book stays short. Make a second
      address book on your contacts server (for example "Phone"), then set
      <code>FLIPDIAL_PHONE_ADDRESSBOOK=Phone</code> and restart FlipDial.
      <a href="https://github.com/garymike/FlipDial/blob/main/docs/sync.md" target="_blank" rel="noreferrer">How phone sync works</a>
    </p>
  {:else if st}
    <p class="detail">
      {st.on_phone} on your phone now, {st.wanted} after the next sync. Last synced {when(st.last_success)}.
      FlipDial sends changes within a minute and checks the phone book every day after {st.check_hour}:00.
    </p>

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
  code {
    font-size: 13px;
  }
</style>
