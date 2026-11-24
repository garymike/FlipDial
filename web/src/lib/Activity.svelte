<script lang="ts">
  // The audit log: every change, import, export and sign-in, newest first.
  import { api, describe, type AuditEntry } from './api'
  import { contactHref } from './router.svelte'

  const LABELS: Record<string, string> = {
    'contact.edit': 'Edited a contact',
    'contact.merge': 'Merged two contacts',
    'contact.merge_undo': 'Undid a merge',
    'contact.forget': 'Forgot a contact',
    'contacts.sync': 'Synced with the contacts server',
    'contacts.copy_to_server': 'Copied contacts from this computer to the server',
    'card.approve': 'Saved a scanned card',
    'card.dismiss': 'Dismissed a scanned card',
    'card.split': 'Split a card from the wrong back',
    'phone.sync': 'Synced the phone book',
    'phone.add': 'Added to the phone book',
    'phone.update': 'Updated on the phone book',
    'phone.remove': 'Removed from the phone book (still in FlipDial)',
    'phone.off': 'Deleted on the phone, so switched off for the phone',
    'phone.rule': 'Changed which contacts go to the phone',
    'phone.choice': 'Changed whether a contact goes to the phone',
    'phone.confirm': 'Confirmed phone book changes',
    'phone.edit': 'Took in an edit made on the phone',
    'phone.ignored': 'Ignored an edit made on the phone (not usable)',
    'phone.added': 'A contact was added on the phone (in Review)',
    'phone.conflict': 'Changed on the phone and in FlipDial (in Review)',
    'phone.accept': 'Saved a contact added on the phone',
    'phone.dismiss': 'Left a phone contact out of FlipDial',
    'phone.use_phone': "Used the phone's version",
    'phone.keep_flipdial': "Kept FlipDial's version",
    'phone.undo': 'Undid an edit from the phone',
    'phone.inbox_accept': 'Decided on a change from the phone',
    'phone.inbox_dismiss': 'Decided on a change from the phone',
    'card.attach': 'Added a scan to a contact',
    'duplicate.not_same': 'Marked two contacts as different people',
    import: 'Imported contacts',
    'import.undo': 'Undid an import',
    'export.vcard': 'Exported contacts (vCard)',
    'export.csv': 'Exported contacts (CSV)',
    'export.changes': 'Exported changes (vCard, for Google Contacts)',
    'export.backup': 'Downloaded a full backup',
    restore: 'Restored a backup',
    'update.start': 'Started an update',
    'card.retry': 'Asked to read cards again',
    'card.restore': 'Brought a dismissed card back',
    'card.delete': 'Deleted a scan',
    sign_in: 'Signed in',
    sign_out: 'Signed out',
    'sign_in.denied': 'Sign-in refused',
  }

  let entries = $state<AuditEntry[]>([])
  let check = $state<{ ok: boolean; entries: number; broken_at: number | null } | null>(null)
  let more = $state(true)
  let error = $state('')

  async function load(before?: number) {
    try {
      const page = (await api.audit(before)).entries
      entries = before ? [...entries, ...page] : page
      more = page.length === 100
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }
  $effect(() => {
    load()
    api.auditVerify().then((c) => (check = c)).catch(() => (check = null))
  })

  function summary(e: AuditEntry): string {
    const d = e.detail
    const n = (k: string) => (typeof d[k] === 'number' ? (d[k] as number) : 0)
    switch (e.action) {
      case 'contact.edit':
        return Array.isArray(d.fields) ? `Changed: ${(d.fields as string[]).join(', ').replaceAll('_', ' ')}` : ''
      case 'contacts.sync':
        return `${n('added')} added, ${n('updated')} updated, ${n('removed')} removed`
      case 'phone.sync':
        return `${n('added')} added, ${n('updated')} updated, ${n('removed')} removed, ${n('switched_off')} switched off`
      case 'phone.edit':
      case 'phone.ignored':
      case 'phone.use_phone':
      case 'phone.keep_flipdial':
      case 'phone.conflict': {
        const f = Array.isArray(d.fields) ? (d.fields as string[]) : []
        const ig = Array.isArray(d.ignored) ? (d.ignored as string[]) : []
        return [f.length && `Fields: ${f.join(', ').replaceAll('_', ' ')}`, ig.length && `ignored: ${ig.join(', ')}`]
          .filter(Boolean)
          .join('; ')
      }
      case 'phone.rule':
      case 'phone.choice':
        return `${e.action === 'phone.rule' ? (e.target === '*' ? 'Every contact' : e.target) + ': ' : ''}${d.state === 'follow' ? 'follow tags' : d.state === 'on' ? 'on the phone' : 'off the phone'}`
      case 'import':
        return `${n('created')} added, ${n('updated')} updated, ${n('skipped')} skipped (${String(d.format ?? '')})`
      case 'import.undo':
        return `${n('removed')} removed, ${n('kept_edited')} kept`
      case 'export.vcard':
      case 'export.csv':
        return `${n('contacts')} contacts${d.filtered ? ' (filtered)' : ''}`
      case 'contact.forget':
        return `${n('scans')} scan${n('scans') === 1 ? '' : 's'} deleted`
      case 'export.backup':
      case 'restore':
        return `${n('contacts')} contacts, ${n('scans')} scans`
      case 'sign_in.denied':
        return String(d.reason ?? '').replaceAll('_', ' ')
      default:
        return ''
    }
  }

  function when(iso: string) {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  }

  function link(e: AuditEntry): string | null {
    const contact = e.action.startsWith('contact.') && !['contact.merge_undo', 'contact.forget'].includes(e.action)
    const fromPhone = ['phone.edit', 'phone.use_phone', 'phone.keep_flipdial', 'phone.accept', 'phone.undo'].includes(e.action)
    return (contact || fromPhone) && e.target ? contactHref(e.target) : null
  }

  // Edits taken in from the phone can be undone for 30 days.
  let undone = $state(new Set<number>())
  async function undoPhone(e: AuditEntry) {
    try {
      await api.phoneUndo(Number(e.detail.undo))
      undone = new Set([...undone, e.id])
      error = ''
    } catch (err) {
      error = describe(err)
    }
  }
</script>

<div class="wrap">
  <h1>Activity log</h1>
  <p class="lead">Every change, import, export and sign-in. Entries cannot be edited or removed from the app.</p>

  {#if check}
    <p class="check" class:bad={!check.ok} role="status">
      {#if check.ok}
        Integrity check passed: {check.entries} {check.entries === 1 ? 'entry' : 'entries'}, unchanged since written.
      {:else}
        Integrity check failed at entry {check.broken_at}. The log was changed outside FlipDial.
      {/if}
    </p>
  {/if}
  {#if error}<p class="error" role="alert">{error}</p>{/if}

  <ol class="log">
    {#each entries as e (e.id)}
      <li>
        <div class="what">
          {#if link(e)}<a href={link(e)}>{LABELS[e.action] ?? e.action}</a>{:else}{LABELS[e.action] ?? e.action}{/if}
          {#if summary(e)}<span class="detail">{summary(e)}</span>{/if}
          {#if Number(e.detail.undo) > 0 && e.action !== 'phone.undo'}
            {#if undone.has(e.id)}<span class="detail">Undone.</span>{:else}
              <button type="button" class="undo" onclick={() => undoPhone(e)}>Undo</button>{/if}
          {/if}
        </div>
        <div class="meta"><span>{e.actor}</span><time datetime={e.ts}>{when(e.ts)}</time></div>
      </li>
    {:else}
      {#if !error}<li class="empty">Nothing recorded yet.</li>{/if}
    {/each}
  </ol>
  {#if more && entries.length}
    <button type="button" class="secondary" onclick={() => load(entries[entries.length - 1].id)}>Show older</button>
  {/if}
</div>

<style>
  .undo {
    margin-left: 8px;
    padding: 2px 10px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: transparent;
    color: var(--amber);
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .wrap {
    max-width: 900px;
    margin: 0 auto;
    padding: 28px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 30px;
    font-weight: 600;
  }
  .lead {
    margin: -6px 0 0;
    color: var(--ash);
  }
  .check {
    margin: 0;
    padding: 12px 16px;
    border-radius: 10px;
    background: #22302a;
    border: 1px solid #3d5a4b;
    font-size: 14px;
  }
  .check.bad,
  .error {
    background: #3a2422;
    border: 1px solid #6b3a35;
  }
  .error {
    margin: 0;
    padding: 12px 16px;
    border-radius: 10px;
  }
  .log {
    list-style: none;
    margin: 0;
    padding: 0;
    border: 1px solid #2c2f36;
    border-radius: 14px;
    background: var(--panel);
  }
  .log li {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 6px 16px;
    padding: 12px 18px;
    border-bottom: 1px solid #2a2d33;
  }
  .log li:last-child {
    border-bottom: 0;
  }
  .what {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 15px;
  }
  .what a {
    color: var(--bone);
  }
  .detail {
    color: var(--ash);
    font-size: 13px;
  }
  .meta {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 2px;
    color: var(--ash);
    font-size: 13px;
    overflow-wrap: anywhere;
  }
  .empty {
    color: var(--ash);
  }
  .secondary {
    align-self: center;
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
    .meta {
      flex-direction: row;
      align-items: center;
      gap: 10px;
    }
  }
</style>
