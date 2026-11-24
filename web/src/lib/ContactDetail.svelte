<script lang="ts">
  import { api, cleanInput, describe, kindName, type Contact, type ContactInput } from './api'
  import ContactForm from './ContactForm.svelte'
  import FlipCard from './FlipCard.svelte'
  import { href } from './router.svelte'
  import Star from './Star.svelte'

  let { uid }: { uid: string } = $props()

  let contact = $state<Contact | null>(null)
  let flipped = $state(false)
  let editing = $state(false)
  let form = $state<ContactInput | null>(null)
  let error = $state('')
  let saving = $state(false)

  $effect(() => {
    api
      .contact(uid)
      .then((c) => {
        contact = c
        error = ''
      })
      .catch((e) => (error = describe(e)))
  })

  function startEdit() {
    if (!contact) return
    const { full_name, title, organization, emails, phones, websites, socials, addresses, about, note, event, met_on, starred } =
      contact
    form = {
      full_name, title, organization, about, note, event, met_on, starred,
      emails: emails.map((t) => ({ ...t })), phones: phones.map((t) => ({ ...t })), websites: websites.map((t) => ({ ...t })),
      addresses: addresses.map((a) => ({ ...a })),
      socials: socials.map((s) => ({ ...s })),
      tags: contact.categories.filter((c) => c !== contact?.event),
    }
    editing = true
  }

  async function save() {
    if (!form || !contact) return
    saving = true
    try {
      contact = await api.update(contact.uid, cleanInput(form))
      editing = false
      error = ''
    } catch (e) {
      error = describe(e)
    } finally {
      saving = false
    }
  }

  async function toggleStar() {
    if (!contact) return
    try {
      contact = await api.update(contact.uid, { starred: !contact.starred })
    } catch (e) {
      error = describe(e)
    }
  }

  let confirming = $state(false)
  let forgetting = $state(false)
  async function forgetContact() {
    if (!contact) return
    forgetting = true
    try {
      await api.forget(contact.uid)
      location.hash = '#/wall'
    } catch (e) {
      error = describe(e)
      forgetting = false
    }
  }

  let storage = $state<'server' | 'local'>('server')
  $effect(() => {
    api.me().then((m) => (storage = m.storage)).catch(() => {})
  })

  const safeUrl = (u: string) => (/^https?:\/\//i.test(u) ? u : `https://${u}`)
</script>

<div class="wrap">
  <a class="back" href={href({ name: 'wall' })}>← Back to the wall</a>
  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if contact}
    <div class="layout">
      <section class="card" aria-label="Card">
        <button type="button" class="tile" aria-label="Flip card" onclick={() => (flipped = !flipped)}>
          <FlipCard {contact} {flipped} size="large" />
        </button>
        {#if contact.card_id}
          <div class="originals">
            <h2>Original scans, never modified</h2>
            <a href={api.original(contact.card_id, 'front')} download>Download front</a>
            {#if contact.has_back}<a href={api.original(contact.card_id, 'back')} download>Download back</a>{/if}
          </div>
        {:else}
          <p class="noscan">No card scanned yet. Scan one and it can be attached to this contact.</p>
        {/if}
      </section>

      <section class="info" aria-label="Contact">
        <div class="head">
          <div>
            <h1>{contact.full_name}</h1>
            <p class="sub">{[contact.title, contact.organization].filter(Boolean).join(', ')}</p>
          </div>
          <div class="headbtns">
            <Star on={contact.starred} label={contact.starred ? 'Unstar' : 'Star'} onclick={toggleStar} />
            {#if !editing}<button type="button" class="secondary" onclick={startEdit}>Edit</button>{/if}
          </div>
        </div>

        {#if editing && form}
          <ContactForm bind:value={form} idPrefix="edit" />
          <div class="buttons">
            <button type="button" class="secondary" onclick={() => (editing = false)}>Cancel</button>
            <button type="button" class="primary" onclick={save} disabled={saving || !form.full_name.trim()}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        {:else}
          <dl>
            {#each contact.emails as e, i (i)}
              <dt>Email <span class="kind">{kindName('emails', e)}</span></dt><dd><a href={`mailto:${e.value}`}>{e.value}</a></dd>
            {/each}
            {#each contact.phones as p, i (i)}
              <dt>Phone <span class="kind">{kindName('phones', p)}</span></dt>
              <dd><a href={`tel:${p.value.replace(/[^\d+]/g, '')}`}>{p.value}</a></dd>
            {/each}
            {#each contact.websites as w, i (i)}
              <dt>Website <span class="kind">{kindName('websites', w)}</span></dt>
              <dd><a href={safeUrl(w.value)} rel="noopener noreferrer" target="_blank">{w.value}</a></dd>
            {/each}
            {#each contact.socials as s (s.platform + s.handle)}
              <dt>{s.platform || 'Social'}</dt>
              <dd>{#if s.url}<a href={s.url} rel="noopener noreferrer" target="_blank">{s.handle}</a>{:else}{s.handle}{/if}</dd>
            {/each}
            {#each contact.addresses as a, i (i)}
              <dt>Address <span class="kind">{kindName('addresses', a)}</span></dt>
              <dd class="multiline">{[a.street, [a.city, [a.region, a.postal_code].filter(Boolean).join(' ')].filter(Boolean).join(', '), a.country].filter(Boolean).join('\n')}</dd>
            {/each}
            {#if contact.about}<dt>About</dt><dd class="multiline">{contact.about}</dd>{/if}
            {#if contact.note}<dt>Notes</dt><dd class="multiline">{contact.note}</dd>{/if}
            <dt>Met at</dt><dd>{contact.event || 'Not set'}</dd>
            <dt>Met on</dt><dd>{contact.met_on || 'Not set'}</dd>
          </dl>
          {#if contact.categories.length}
            <ul class="tags">{#each contact.categories as t (t)}<li>{t}</li>{/each}</ul>
          {/if}
          <div class="panel">
            <span class="badge" aria-hidden="true">S</span>
            {storage === 'local' ? 'Saved on this computer (no contacts server set up yet)' : 'Saved to your contacts server'}
          </div>
          {#if confirming}
            <div class="forget" role="group" aria-label="Forget this contact">
              <p>
                This removes {contact.full_name} from your contacts server and deletes their scans
                and history from FlipDial. It cannot be undone. Backups you already downloaded still
                include them.
              </p>
              <div class="buttons">
                <button type="button" class="secondary" onclick={() => (confirming = false)}>Keep</button>
                <button type="button" class="danger" onclick={forgetContact} disabled={forgetting}>
                  {forgetting ? 'Forgetting…' : 'Forget forever'}
                </button>
              </div>
            </div>
          {:else}
            <button type="button" class="link-danger" onclick={() => (confirming = true)}>Forget this contact…</button>
          {/if}
        {/if}
      </section>
    </div>
  {/if}
</div>

<style>
  .multiline {
    white-space: pre-line;
  }
  .wrap {
    max-width: 1360px;
    margin: 0 auto;
    padding: 24px 32px 56px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }
  .back {
    font-size: 14px;
    text-decoration: none;
  }
  .layout {
    display: flex;
    flex-wrap: wrap;
    gap: 40px;
  }
  .card {
    flex: 1 1 480px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 18px;
    max-width: 640px;
  }
  .tile {
    display: block;
    width: 100%;
    padding: 0;
    border: 0;
    background: transparent;
    cursor: pointer;
  }
  .originals {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
    padding: 14px 16px;
    border: 1px solid #2c2f36;
    border-radius: 12px;
  }
  .originals h2 {
    flex-basis: 100%;
    margin: 0;
    font-size: 12px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--ash);
  }
  .noscan {
    color: var(--ash);
    margin: 0;
  }
  .info {
    flex: 1 1 400px;
    min-width: 0;
    display: flex;
    flex-direction: column;
    gap: 22px;
  }
  .head {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    gap: 12px;
  }
  h1 {
    margin: 0;
    font-family: var(--font-display);
    font-size: 36px;
    font-weight: 600;
  }
  .sub {
    margin: 6px 0 0;
    color: #d6d1c9;
  }
  .headbtns {
    display: flex;
    align-items: center;
    gap: 8px;
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: max-content 1fr;
    gap: 10px 20px;
  }
  dt .kind {
    display: block;
    letter-spacing: 0.04em;
    color: var(--amber);
    font-size: 11px;
  }
  dt {
    font-size: 12px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--ash);
    padding-top: 3px;
  }
  dd {
    margin: 0;
    overflow-wrap: anywhere;
  }
  .tags {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }
  .tags li {
    font-size: 12px;
    padding: 5px 10px;
    border-radius: 999px;
    background: #23262c;
    border: 1px solid var(--line);
  }
  .panel {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 14px 16px;
    border-radius: 12px;
    background: var(--panel);
    border: 1px solid #2c2f36;
    font-size: 14px;
  }
  .badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 6px;
    background: #23262c;
    border: 1px solid var(--line);
    font-size: 10px;
    font-weight: 700;
  }
  .forget {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    border-radius: 12px;
    background: #3a2422;
    border: 1px solid #6b3a35;
  }
  .forget p {
    margin: 0;
    font-size: 14px;
    line-height: 1.5;
  }
  .danger {
    min-height: 44px;
    padding: 0 18px;
    border: 0;
    border-radius: 10px;
    background: #e5776b;
    color: var(--ink);
    font: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  .link-danger {
    align-self: flex-start;
    min-height: 40px;
    padding: 0;
    border: 0;
    background: transparent;
    color: #e5776b;
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .buttons {
    display: flex;
    gap: 10px;
  }
  .primary,
  .secondary {
    min-height: 44px;
    padding: 0 18px;
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
    padding: 12px 14px;
    border-radius: 10px;
    background: #3a2a1a;
    color: var(--signal);
  }
</style>
