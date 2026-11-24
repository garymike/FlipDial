<script lang="ts">
  // Import contacts (vCard, CSV, LinkedIn export), undo an import, and export or back up.
  import { href } from './router.svelte'
  import { api, ApiError, DEMO, describe, REASONS, type ImportField, type ImportPreview, type ImportRecord } from './api'

  const MAX_BYTES = 10 * 1024 * 1024
  const FORMATS: Record<string, string> = {
    vcard: 'vCard file',
    linkedin: 'LinkedIn connections',
    google: 'Google Contacts CSV',
    outlook: 'Outlook CSV',
    csv: 'CSV file',
  }
  const FIELD_LABELS: Record<ImportField, string> = {
    '': 'Ignore',
    full_name: 'Full name',
    given_name: 'First name',
    middle_name: 'Middle name',
    family_name: 'Last name',
    prefix: 'Name prefix',
    suffix: 'Name suffix',
    nickname: 'Nickname',
    organization: 'Company',
    department: 'Department',
    title: 'Title',
    email: 'Email',
    phone: 'Phone',
    website: 'Website',
    linkedin: 'LinkedIn URL',
    address: 'Address',
    met_on: 'Met on (date)',
    birthday: 'Birthday',
    tags: 'Tags',
    note: 'Note',
  }
  const STATUS: Record<string, string> = {
    new: 'New',
    update: 'Will be updated',
    same: 'Up to date',
    duplicate: 'Looks like one you have',
    invalid: 'Skipped',
  }
  const CHANGE_NAMES: Record<string, string> = {
    name: 'name',
    name_parts: 'name parts',
    organization: 'company',
    title: 'title',
    phones: 'phones',
    emails: 'emails',
    websites: 'websites',
    addresses: 'addresses',
    socials: 'social',
    nickname: 'nickname',
    birthday: 'birthday',
    note: 'notes',
  }
  const SKIP_REASONS: Record<string, string> = {
    ...REASONS,
    same_contact: 'Same contact',
    no_name: 'No name',
    missing_fn: 'No name',
    unsupported_version: 'Old vCard format',
    bad_values: 'Unreadable',
    not_a_vcard: 'Unreadable',
  }

  let fileName = $state('')
  let text = $state('')
  let preview = $state<ImportPreview | null>(null)
  let mapping = $state<ImportField[]>([])
  let deck = $state('')
  let includeDuplicates = $state(false)
  let updateMatches = $state(true)
  let preferFile = $state(false)
  let busy = $state(false)
  let error = $state('')
  let notice = $state<{ text: string; importId?: number } | null>(null)
  let history = $state<ImportRecord[]>([])

  let changes = $state<{ since: string; count: number; phone_sync: boolean; count_phone?: number } | null>(null)
  async function loadChanges() {
    try {
      changes = await api.changesInfo()
    } catch {
      changes = null
    }
  }
  $effect(() => {
    loadChanges()
  })
  const reloadChanges = () => setTimeout(loadChanges, 1500)

  async function loadHistory() {
    try {
      history = (await api.imports()).imports.slice(0, 8)
    } catch {
      history = []
    }
  }
  $effect(() => {
    loadHistory()
  })

  function decode(buf: ArrayBuffer): string {
    try {
      return new TextDecoder('utf-8', { fatal: true }).decode(buf)
    } catch {
      return new TextDecoder('windows-1252').decode(buf) // older Outlook exports
    }
  }

  async function choose(e: Event) {
    const input = e.currentTarget as HTMLInputElement
    const file = input.files?.[0]
    input.value = ''
    if (!file) return
    error = ''
    notice = null
    preview = null
    if (file.size > MAX_BYTES) {
      error = describe(new ApiError(413, 'file_too_large'))
      return
    }
    fileName = file.name
    text = decode(await file.arrayBuffer())
    mapping = []
    const p = await runPreview(false)
    if (p?.format === 'linkedin' && !deck) deck = 'LinkedIn'
  }

  async function runPreview(withMapping = true): Promise<ImportPreview | null> {
    if (!text) return null
    busy = true
    try {
      preview = await api.importPreview({
        text,
        deck,
        mapping: withMapping && mapping.length ? mapping : undefined,
      })
      mapping = [...(preview.mapping ?? [])]
      error = ''
      return preview
    } catch (e) {
      error = describe(e)
      preview = null
      return null
    } finally {
      busy = false
    }
  }

  const toImport = $derived(
    preview
      ? preview.counts.new +
          (includeDuplicates ? preview.counts.duplicate : 0) +
          (updateMatches ? (preview.counts.update ?? 0) : includeDuplicates ? (preview.counts.update ?? 0) + (preview.counts.same ?? 0) : 0)
      : 0,
  )

  async function doImport() {
    if (!preview || !toImport) return
    busy = true
    try {
      const r = await api.importRun({
        text,
        deck,
        mapping: mapping.length ? mapping : undefined,
        include_duplicates: includeDuplicates,
        update: updateMatches,
        prefer_file: preferFile,
      })
      const c = r.counts
      const parts = [`Added ${c.created} contact${c.created === 1 ? '' : 's'}.`]
      if (c.updated) parts.push(`Updated ${c.updated}.`)
      if (c.unchanged) parts.push(`${c.unchanged} already up to date.`)
      if (c.skipped) parts.push(`${c.skipped} skipped.`)
      if (c.failed) parts.push(`${c.failed} could not be saved.`)
      notice = { text: parts.join(' '), importId: r.import_id }
      loadChanges()
      preview = null
      text = ''
      fileName = ''
      await loadHistory()
      loadChanges()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  async function undo(id: number) {
    try {
      const r = await api.undoImport(id)
      notice = {
        text:
          `Removed ${r.removed} imported contact${r.removed === 1 ? '' : 's'}.` +
          (r.restored ? ` Put ${r.restored} updated contact${r.restored === 1 ? '' : 's'} back as they were.` : '') +
          (r.kept_edited ? ` Kept ${r.kept_edited} you edited since.` : ''),
      }
      await loadHistory()
      loadChanges()
    } catch (e) {
      error = describe(e)
    }
  }

  function when(iso: string) {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  }
</script>

<div class="wrap">
  <h1>Import and export</h1>
  <p class="lead">
    Bring contacts in from other apps, or take everything with you. Imports can be undone.
    Every import and export is recorded in the <a href={href({ name: 'activity' })}>activity log</a>.
    If scans aren't being read, run the <a href={href({ name: 'setup' })}>setup check</a>.
  </p>

  {#if DEMO}<p class="notice">Importing, exporting and backups are turned off in the demo, since it runs entirely in your browser.</p>{/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}
  {#if notice}
    <div class="notice" role="status">
      <span>{notice.text}</span>
      {#if notice.importId}<button type="button" class="link" onclick={() => undo(notice!.importId!)}>Undo</button>{/if}
      <button type="button" class="link" aria-label="Close message" onclick={() => (notice = null)}>×</button>
    </div>
  {/if}

  <section class="panel">
    <h2>Import</h2>
    <p class="hint">
      vCard (.vcf) or CSV from Google Contacts, Outlook, a spreadsheet, or LinkedIn. For LinkedIn,
      request your data under Settings, Data privacy, then upload <code>Connections.csv</code>.
    </p>
    <label class="file">
      <input type="file" accept=".vcf,.vcard,.csv,text/vcard,text/csv" onchange={choose} disabled={busy || DEMO} />
      <span>{fileName || 'Choose a file'}</span>
    </label>

    {#if preview}
      <div class="summary">
        <span class="format">{FORMATS[preview.format] ?? preview.format}</span>
        <span><strong>{preview.counts.new}</strong> new</span>
        {#if preview.counts.update}<span><strong>{preview.counts.update}</strong> to update</span>{/if}
        {#if preview.counts.same}<span><strong>{preview.counts.same}</strong> up to date</span>{/if}
        {#if preview.counts.duplicate}<span><strong>{preview.counts.duplicate}</strong> look like ones you have</span>{/if}
        {#if preview.counts.invalid}<span><strong>{preview.counts.invalid}</strong> skipped</span>{/if}
      </div>

      {#if preview.headers?.length}
        <fieldset class="mapping">
          <legend>Columns</legend>
          {#each preview.headers as h, i (i)}
            <label>
              <span class="col">{h || `Column ${i + 1}`}</span>
              <select bind:value={mapping[i]} onchange={() => runPreview()}>
                {#each Object.entries(FIELD_LABELS) as [value, label] (value)}
                  <option {value}>{label}</option>
                {/each}
              </select>
            </label>
          {/each}
        </fieldset>
      {/if}

      <div class="options">
        <label class="text">
          <span>Put them in a deck (optional)</span>
          <input type="text" maxlength="80" bind:value={deck} placeholder="For example: LinkedIn" onchange={() => runPreview()} />
        </label>
        {#if preview.counts.update || preview.counts.same}
          <label class="check">
            <input type="checkbox" bind:checked={updateMatches} />
            Update contacts you already have: add new phones, emails and details, and fill in empty fields. Nothing is removed.
          </label>
          {#if updateMatches}
            <label class="check">
              <input type="checkbox" bind:checked={preferFile} />
              When both have a different value, use the file's (otherwise FlipDial's is kept)
            </label>
          {/if}
        {/if}
        {#if preview.counts.duplicate}
          <label class="check">
            <input type="checkbox" bind:checked={includeDuplicates} />
            Also add the {preview.counts.duplicate} that look like contacts you already have, as separate contacts
          </label>
        {/if}
      </div>

      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Company</th><th>Email</th><th>Status</th></tr></thead>
          <tbody>
            {#each preview.rows as r (r.row)}
              <tr class={r.status}>
                <td>{r.name || '(no name)'}</td>
                <td>{r.organization}</td>
                <td>{r.email}</td>
                <td>
                  <span class="chip">{STATUS[r.status]}</span>
                  {#if r.changes?.length}<span class="why">adds {r.changes.map((x) => CHANGE_NAMES[x] ?? x).join(', ')}</span>
                  {:else if r.reason && r.status !== 'same'}<span class="why">{SKIP_REASONS[r.reason] ?? r.reason}</span>{/if}
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
        {#if preview.counts.total > preview.rows.length}
          <p class="hint">Showing the first {preview.rows.length} of {preview.counts.total}.</p>
        {/if}
      </div>

      <div class="buttons">
        <button type="button" class="secondary" onclick={() => { preview = null; text = ''; fileName = '' }}>Cancel</button>
        <button type="button" class="primary" disabled={busy || !toImport} onclick={doImport}>
          {busy ? 'Working…' : `Import ${toImport} contact${toImport === 1 ? '' : 's'}`}
        </button>
      </div>
    {/if}
  </section>

  {#if history.length}
    <section class="panel">
      <h2>Recent imports</h2>
      <ul class="history">
        {#each history as h (h.id)}
          <li>
            <span>{FORMATS[h.format] ?? h.format}, {h.counts.created} added{h.counts.updated ? `, ${h.counts.updated} updated` : ''}</span>
            <span class="when">{when(h.created_at)}</span>
            {#if h.undone}
              <span class="when">Undone</span>
            {:else if h.counts.created || h.counts.updated}
              <button type="button" class="link" onclick={() => undo(h.id)}>Undo</button>
            {/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  <section class="panel">
    <h2>Export</h2>
    <p class="hint">Exports include every contact on your contacts server, with or without a scan.</p>
    <div class="exports" class:off={DEMO} aria-disabled={DEMO}>
      <a class="secondary" href={api.exportUrl('vcf')} download>vCard (.vcf)</a>
      <a class="secondary" href={api.exportUrl('csv')} download>Spreadsheet (.csv)</a>
    </div>
  </section>

  <section class="panel">
    <h2>Changes for Google Contacts</h2>
    <p class="hint">
      A vCard of contacts changed since you last downloaded this, with standard fields only. Import it at
      contacts.google.com; if Google makes copies, its Merge &amp; fix tool combines them. Nothing is connected to your
      Google account.
    </p>
    {#if changes}
      <p class="hint">
        {changes.count} changed {changes.since ? `since ${when(changes.since)}` : '(first time: every contact)'}{changes.phone_sync
          ? `, ${changes.count_phone} of them on your phone`
          : ''}.
      </p>
      <div class="exports" class:off={DEMO} aria-disabled={DEMO}>
        <a class="secondary" href={api.changesUrl(false)} download onclick={reloadChanges}>Download changes</a>
        {#if changes.phone_sync}
          <a class="secondary" href={api.changesUrl(true)} download onclick={reloadChanges}>Only contacts on my phone</a>
        {/if}
      </div>
    {/if}
  </section>

  <section class="panel">
    <h2>Full backup</h2>
    <p class="hint">
      One zip with every contact, every original scan, and FlipDial's history (reviews, merges,
      imports). Each file is checked against a list of fingerprints when you restore it with
      <code>flipdial restore</code>. Keep it somewhere private: it holds all your contacts.
    </p>
    <div class="exports" class:off={DEMO} aria-disabled={DEMO}>
      <a class="primary" href={api.exportUrl('backup')} download>Download backup</a>
    </div>
  </section>
</div>

<style>
  .wrap {
    max-width: 1000px;
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
  h2 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 19px;
    font-weight: 600;
  }
  .lead {
    margin: -8px 0 0;
    color: var(--ash);
  }
  .panel {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 20px;
    border-radius: 14px;
    background: var(--panel);
    border: 1px solid #2c2f36;
  }
  .hint {
    margin: 0;
    color: var(--ash);
    font-size: 14px;
    line-height: 1.5;
  }
  code {
    font-family: var(--font-mono);
    font-size: 13px;
    color: var(--bone);
  }
  .file {
    position: relative;
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 84px;
    border: 1.5px dashed var(--line);
    border-radius: 12px;
    color: var(--bone);
    font-weight: 600;
    cursor: pointer;
  }
  .file:hover,
  .file:focus-within {
    border-color: var(--amber);
  }
  .file input {
    position: absolute;
    inset: 0;
    opacity: 0;
    cursor: pointer;
  }
  .summary {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px 18px;
    font-size: 14px;
    color: #d6d1c9;
  }
  .format {
    padding: 4px 10px;
    border-radius: 999px;
    background: var(--amber);
    color: var(--ink);
    font-weight: 700;
    font-size: 12px;
  }
  fieldset {
    margin: 0;
    padding: 0;
    border: 0;
  }
  legend {
    margin-bottom: 8px;
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ash);
  }
  .mapping {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 8px 16px;
  }
  .mapping label {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    font-size: 14px;
  }
  .col {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  select,
  .text input {
    min-height: 40px;
    padding: 0 10px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
    font-size: 14px;
  }
  select {
    flex: 0 0 150px;
  }
  .options {
    display: flex;
    flex-wrap: wrap;
    align-items: end;
    gap: 14px 24px;
  }
  .text {
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 13px;
    color: var(--ash);
  }
  .text input {
    width: 260px;
    max-width: 100%;
  }
  .check {
    display: flex;
    align-items: center;
    gap: 10px;
    min-height: 40px;
    font-size: 14px;
  }
  .check input {
    width: 18px;
    height: 18px;
    accent-color: var(--amber);
  }
  .table-wrap {
    max-height: 360px;
    overflow: auto;
    border: 1px solid #2c2f36;
    border-radius: 10px;
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  th {
    position: sticky;
    top: 0;
    background: var(--graphite);
    color: var(--ash);
    font-size: 12px;
    font-weight: 600;
    text-align: left;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }
  th,
  td {
    padding: 8px 12px;
    border-bottom: 1px solid #2a2d33;
    overflow-wrap: break-word;
  }
  tr.duplicate td,
  tr.invalid td {
    color: var(--ash);
  }
  .chip {
    padding: 2px 8px;
    border-radius: 999px;
    border: 1px solid var(--line);
    font-size: 12px;
    white-space: nowrap;
  }
  tr.new .chip {
    border-color: var(--sage);
    color: var(--sage);
  }
  .why {
    margin-left: 6px;
    font-size: 12px;
  }
  .buttons,
  .exports {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
  }
  .buttons {
    justify-content: flex-end;
  }
  .off {
    opacity: 0.45;
    pointer-events: none;
  }
  .primary,
  .secondary {
    display: inline-flex;
    align-items: center;
    min-height: 44px;
    padding: 0 18px;
    border-radius: 10px;
    font: inherit;
    font-size: 14px;
    text-decoration: none;
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
  .link {
    min-height: 36px;
    padding: 0 8px;
    border: 0;
    background: transparent;
    color: var(--amber);
    font: inherit;
    cursor: pointer;
  }
  .history {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .history li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    min-height: 40px;
    font-size: 14px;
  }
  .when {
    color: var(--ash);
    font-size: 13px;
  }
  .notice,
  .error {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 0;
    padding: 12px 16px;
    border-radius: 10px;
  }
  .notice {
    background: #22302a;
    border: 1px solid #3d5a4b;
  }
  .notice span {
    flex: 1;
  }
  .error {
    background: #3a2422;
    border: 1px solid #6b3a35;
  }
  @media (max-width: 640px) {
    .wrap {
      padding: 20px 16px 40px;
    }
    .panel {
      padding: 16px;
    }
    th:nth-child(3),
    td:nth-child(3) {
      display: none;
    }
    th,
    td {
      padding: 8px;
    }
    .why {
      display: block;
      margin: 4px 0 0;
    }
  }
</style>
