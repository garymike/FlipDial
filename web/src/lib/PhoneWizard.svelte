<script lang="ts">
  // Phone setup wizard (docs/sync.md): the phone book, the phone's own account, and adding
  // the account to an iPhone (one-tap profile) or an Android phone (DAVx5).
  import { untrack } from 'svelte'
  import { api, describe, type PhoneSetupInfo } from './api'

  let { start = 'book', ondone }: { start?: 'book' | 'phone'; ondone?: () => void } = $props()

  let step = $state<'book' | 'account' | 'phone'>(untrack(() => (start === 'phone' ? 'phone' : 'book')))
  let info = $state<PhoneSetupInfo | null>(null)
  let error = $state('')
  let busy = $state(false)

  // Step 1
  let choice = $state('')
  let newName = $state('Phone')
  // Step 2
  let username = $state('')
  let password = $state('')
  let test = $state<{ sees_phone_book: boolean; sees_main_book: boolean } | null>(null)
  let made = $state<{ username: string; password: string } | null>(null)
  let phoneName = $state('My phone')
  // Step 3 (chosen in step 1 on FlipDial's own server)
  let device = $state<'iphone' | 'android'>('android')
  let iosWay = $state<'profile' | 'manual'>('profile')
  let opened = $state<string | null>(null)
  let link = $state<{ url: string; expires_at: string; qr_svg: string; via: 'flipdial' | 'network' } | null>(null)
  let copied = $state('')

  async function load() {
    try {
      info = await api.phoneSetup()
      const others = info.books.filter((b) => b !== info?.main_book)
      choice = info.book || (others.length ? others[0] : '__new')
      username = info.phone_username
      if (info.phone_name) phoneName = info.phone_name
      error = ''
    } catch (e) {
      error = describe(e)
    }
  }
  $effect(() => {
    load()
  })

  async function run(fn: () => Promise<void>) {
    busy = true
    error = ''
    try {
      await fn()
    } catch (e) {
      error = describe(e)
    } finally {
      busy = false
    }
  }

  const useBook = () =>
    run(async () => {
      const create = choice === '__new'
      info = await api.phoneSetupBook(create ? newName : choice, create)
      step = 'account'
    })

  const makeAccount = () =>
    run(async () => {
      const r = await api.phoneSetupAccount(phoneName.trim() || 'My phone')
      made = { username: r.username, password: r.password }
      await load()
      ondone?.()
    })

  const newPassword = () =>
    run(async () => {
      made = await api.phoneNewPassword()
    })

  const hasAccount = $derived(!!info?.phone_username && !!info?.bundled)
  const renamed = $derived(hasAccount && phoneName.trim() !== (info?.phone_name || ''))
  const where = $derived(device === 'android' ? 'in the DAVx5 app' : 'on the iPhone or iPad, when it asks')

  const check = () =>
    run(async () => {
      test = await api.phoneSetupTest(username, password)
      password = ''
    })

  const saveAccount = () =>
    run(async () => {
      await api.phoneSetupUsername(username)
      if (info) info.phone_username = username
      step = 'phone'
      ondone?.()
    })

  const local = typeof location !== 'undefined' && ['localhost', '127.0.0.1', '[::1]'].includes(location.hostname)
  const makeLink = () =>
    run(async () => {
      link = await api.phoneProfileLink(location.origin)
      opened = null
    })

  // Show when the link is opened, so it's clear if anything other than your phone did.
  $effect(() => {
    const l = link
    if (!l || opened) return
    const token = l.url.split('/phone-profile/')[1] ?? ''
    const every = setInterval(async () => {
      try {
        const c = await api.phoneProfileLinkCheck(token)
        if (c.used_at) opened = c.used_at
        if (c.used_at || c.expired) clearInterval(every)
      } catch {
        clearInterval(every)
      }
    }, 3000)
    return () => clearInterval(every)
  })

  async function copy(text: string, what: string) {
    try {
      await navigator.clipboard.writeText(text)
      copied = what
    } catch {
      copied = ''
    }
  }
  const isSynology = $derived(info?.server_kind === 'synology')
  // A phone book on FlipDial's own server is given by its path; it's called Phone there.
  const bookName = $derived(info?.book?.startsWith('/') ? 'Phone' : (info?.book ?? ''))
  // The phone reaches the contacts server directly, so its address has to work from the phone.
  const bookHost = $derived.by(() => {
    try {
      return new URL(info?.book_url ?? '').hostname
    } catch {
      return ''
    }
  })
  const bookLocal = $derived(['localhost', '127.0.0.1', '[::1]', '::1'].includes(bookHost))
  const bookPlain = $derived((info?.book_url ?? '').startsWith('http://'))
</script>

<div class="wizard" aria-label="Phone setup">
  <ol class="steps">
    <li class:on={step === 'book'}>{info?.bundled ? 'Your phone' : 'Phone address book'}</li>
    <li class:on={step === 'account'}>{info?.bundled ? 'Its sign-in' : "The phone's account"}</li>
    <li class:on={step === 'phone'}>Add it to the phone</li>
  </ol>
  {#if error}<p class="error" role="alert">{error}</p>{/if}

  {#if !info}
    <p class="detail">Checking the contacts server…</p>
  {:else if !info.server}
    <p class="detail">
      Phone sync needs a contacts server on your home network. Turn on FlipDial's built-in one under Contacts server
      above, or connect your own (such as Synology Contacts or Nextcloud).
    </p>
  {:else if step === 'book' && info.bundled}
    <p class="detail">
      Here's how it works: FlipDial keeps all your contacts in its main address book. Your phone gets a separate address
      book with only the contacts you pick (nothing goes to the phone until you pick some). The phone signs in with its
      own account, which can open that one address book and nothing else.
    </p>
    <div class="segmented" role="group" aria-label="What kind of phone?">
      <button type="button" aria-pressed={device === 'android'} onclick={() => (device = 'android')}>Android</button>
      <button type="button" aria-pressed={device === 'iphone'} onclick={() => (device = 'iphone')}>iPhone or iPad</button>
    </div>
    <div class="grid">
      <label for="pw-name">Name</label>
      <input id="pw-name" bind:value={phoneName} maxlength="60" placeholder="My phone" />
    </div>
    <p class="hint">
      This is what the address book is called in the phone's Contacts app. Using a phone and a tablet? Give them one name
      (like "My devices") and add the same sign-in to each; they'll show the same contacts.
    </p>
    <button type="button" class="primary" disabled={!phoneName.trim()} onclick={() => (step = 'account')}>Next</button>
  {:else if step === 'account' && info.bundled}
    {#if made}
      <p class="detail">The phone signs in to FlipDial's contacts server with these:</p>
      <div class="grid copy">
        <span>User name</span><code>{made.username}</code>
        <button type="button" class="link" onclick={() => copy(made?.username ?? '', 'user')}>{copied === 'user' ? 'Copied' : 'Copy'}</button>
        <span>Password</span><code>{made.password}</code>
        <button type="button" class="link" onclick={() => copy(made?.password ?? '', 'pass')}>{copied === 'pass' ? 'Copied' : 'Copy'}</button>
      </div>
      <p class="detail">
        You'll enter them once, {where}, in the next step. After that the phone remembers them; you don't need to keep the
        password. If you lose it or add another device later, come back here and make a new one.
      </p>
      <p class="warn">The password is shown only now, so keep this page open until the phone is added.</p>
      <button type="button" class="primary" onclick={() => (step = 'phone')}>Next</button>
    {:else if hasAccount && !renamed}
      <p class="detail">
        <strong>{info.phone_name || info.phone_username}</strong> already has a sign-in (user name
        <code>{info.phone_username}</code>). If you have its password, go on. If not, make a new one; devices already using
        the old password will ask for the new one.
      </p>
      <div class="row">
        <button type="button" class="primary" onclick={() => (step = 'phone')}>I have the password</button>
        <button type="button" class="secondary" disabled={busy} onclick={newPassword}>Make a new password</button>
        <button type="button" class="link" onclick={() => (step = 'book')}>Back</button>
      </div>
    {:else}
      {#if renamed}
        <p class="detail">
          This replaces the current sign-in, <code>{info.phone_username}</code>, and its address book with
          <strong>{phoneName.trim()}</strong>. Your contacts aren't affected; the ones you picked are copied again to the
          new address book. Remove the old account from the phone afterwards.
        </p>
      {:else}
        <p class="detail">
          FlipDial now makes the sign-in for <strong>{phoneName.trim()}</strong> and its address book on its contacts server.
          You'll see the password once, on the next screen.
        </p>
      {/if}
      <div class="row">
        <button type="button" class="primary" disabled={busy} onclick={makeAccount}>{busy ? 'Making it…' : 'Make the sign-in'}</button>
        <button type="button" class="link" onclick={() => (step = 'book')}>Back</button>
      </div>
    {/if}
  {:else if step === 'book'}
    <p class="detail">
      Your phone gets its own address book, next to your main one ({info.main_book || 'the main address book'}). Only the
      contacts you choose are copied into it.
    </p>
    {#if info.book_from_settings_file}
      <p class="detail">It's set in the settings file: <strong>{info.book}</strong>.</p>
      <button type="button" class="primary" onclick={() => (step = 'account')}>Next</button>
    {:else}
      <fieldset>
        <legend>Which address book?</legend>
        {#each info.books.filter((b) => b !== info?.main_book) as b (b)}
          <label class="opt"><input type="radio" bind:group={choice} value={b} /> {b}</label>
        {/each}
        <label class="opt">
          <input type="radio" bind:group={choice} value="__new" /> Make a new one called
          <input class="name" aria-label="New address book name" bind:value={newName} maxlength="60" onfocus={() => (choice = '__new')} />
        </label>
      </fieldset>
      {#if isSynology}
        <p class="hint">
          If Synology doesn't let FlipDial make it: in Synology Contacts, choose the + next to address books, name it, then
          pick it here.
        </p>
      {/if}
      <button type="button" class="primary" disabled={busy || (choice === '__new' && !newName.trim())} onclick={useBook}>
        {busy ? 'Checking…' : 'Use this address book'}
      </button>
    {/if}
  {:else if step === 'account'}
    <p class="detail">
      Give the phone its own account on the contacts server that can open only <strong>{info.book}</strong>. Then a
      phone can never see or change your other contacts, and if it is lost you change just that password.
    </p>
    {#if isSynology}
      <ol class="how">
        <li>In DSM, open Control Panel, then User &amp; Group, and create a user, for example "phone". Give it access to the Contacts app only.</li>
        <li>In Synology Contacts, share <strong>{info.book}</strong> with that user, allowing it to edit. Don't share your main address book.</li>
      </ol>
    {:else}
      <p class="hint">Create a user on your contacts server and give it access to {info.book} only.</p>
    {/if}
    <div class="grid">
      <label for="pw-user">Phone's user name</label>
      <input id="pw-user" bind:value={username} maxlength="200" autocomplete="off" />
      <label for="pw-pass">Its password, to check it</label>
      <input id="pw-pass" type="password" bind:value={password} autocomplete="new-password" />
    </div>
    <p class="hint">The password is used for this check only. FlipDial doesn't keep it.</p>
    {#if test}
      <ul class="result">
        <li class:ok={test.sees_phone_book}>{test.sees_phone_book ? '✓' : '✕'} Can open {info.book}</li>
        <li class:ok={!test.sees_main_book}>
          {test.sees_main_book ? '! Can also see your main address book. The phone would show every contact.' : '✓ Can’t see your main address book'}
        </li>
      </ul>
    {/if}
    {#if username && username === info.flipdial_username}
      <p class="warn">That's the account FlipDial uses, which can see every address book. A separate account is safer.</p>
    {/if}
    <div class="row">
      <button type="button" class="secondary" disabled={busy || !username || !password} onclick={check}>Check the account</button>
      <button type="button" class="primary" disabled={busy || !username} onclick={saveAccount}>Next</button>
      <button type="button" class="link" onclick={() => (step = 'book')}>Back</button>
    </div>
  {:else}
    {#if bookLocal}
      <p class="warn">
        FlipDial reaches the contacts server as {bookHost}, which only works on this computer. Set FLIPDIAL_CARDDAV_URL to
        the server's address on your network so the phone can reach it too.
      </p>
    {/if}
    {#if bookPlain}
      <p class="warn">
        The contacts server uses http, so the phone would send its password unencrypted over your Wi-Fi. Turn on HTTPS on
        the server (Synology: Control Panel, Login Portal) and use its https address.
      </p>
    {/if}
    <div class="segmented" role="group" aria-label="Phone">
      <button type="button" aria-pressed={device === 'iphone'} onclick={() => (device = 'iphone')}>iPhone or iPad</button>
      <button type="button" aria-pressed={device === 'android'} onclick={() => (device = 'android')}>Android</button>
    </div>
    {#if device === 'iphone'}
      <fieldset class="ways">
        <label class="opt"><input type="radio" bind:group={iosWay} value="profile" /> <strong>Quick:</strong> scan a code and install a profile</label>
        <label class="opt"><input type="radio" bind:group={iosWay} value="manual" /> <strong>By hand:</strong> type the account in Settings (no profile to install)</label>
      </fieldset>
    {/if}
    {#if device === 'iphone' && iosWay === 'manual'}
      <ol class="how">
        <li>Open Settings, then Apps, Contacts, Contacts Accounts, Add Account (on older versions: Settings, Contacts, Accounts), then Other, then <em>Add CardDAV Account</em>.</li>
        <li>Enter:
          <div class="grid copy">
            <span>Server</span><code>{info.book_url}</code>
            <button type="button" class="link" onclick={() => copy(info?.book_url ?? '', 'server')}>{copied === 'server' ? 'Copied' : 'Copy'}</button>
            <span>User name</span><code>{info.phone_username}</code>
            <button type="button" class="link" onclick={() => copy(info?.phone_username ?? '', 'user')}>{copied === 'user' ? 'Copied' : 'Copy'}</button>
          </div>
          the account's password, and FlipDial as the description.</li>
        <li>
          If it says <em>Cannot Verify Server Identity</em>, tap Details and check that the certificate is for
          <strong>{bookHost}</strong>{#if info.bundled} and issued by <strong>FlipDial contacts server CA</strong>{/if}, then Trust or Continue.
          Do this only at home: it trusts that one server for this account, and nothing else.
        </li>
      </ol>
      <p class="hint">
        No profile and no certificate authority on the device: the most contained option. The certificate check happens once,
        when you add the account.
      </p>
    {:else if device === 'iphone'}
      {#if local && !link}
        <p class="hint">
          Your phone can't open FlipDial at {location.hostname}, so this computer offers the link on your home network for
          15 minutes (port 5233). On Windows, this is allowed by the same answer you gave for the contacts server.
        </p>
      {/if}
      {#if !link}
        <p class="detail">The iPhone needs to be on your home Wi-Fi. FlipDial makes a link that works once, for 15 minutes.</p>
        <button type="button" class="primary" disabled={busy || !info.phone_username} onclick={makeLink}>Make the iPhone link</button>
      {:else}
        <div class="qr">
          <img src={`data:image/svg+xml;base64,${btoa(link.qr_svg)}`} alt="QR code for the iPhone link" />
          <ol class="how">
            <li>Point the iPhone camera at the code and open the link (or open it on the iPhone).</li>
            <li>Allow the download, then open Settings and tap <em>Profile Downloaded</em>, then Install.</li>
            <li>Enter the password of <strong>{info.phone_username}</strong> when asked.</li>
            <li>If the contacts server uses its own certificate: Settings, General, About, Certificate Trust Settings, and turn it on.</li>
          </ol>
        </div>
        {#if opened}
          <p class="detail">✓ Opened at {new Date(opened).toLocaleTimeString()}. If that wasn't your device, make a new link and set it up again.</p>
        {:else}
          <p class="hint">Waiting for the link to be opened…</p>
        {/if}
        <p class="hint">
          The link expires at {new Date(link.expires_at).toLocaleTimeString()} and works once.
          {#if link.via === 'network'}Install it right away, at home. iOS shows what the profile adds before installing it: one
            contacts account and, for FlipDial's own server, its certificate.{/if}
        </p>
        <button type="button" class="secondary" onclick={() => (link = null)}>Make a new link</button>
      {/if}
    {:else}
      <ol class="how">
        <li>Install DAVx5 from Google Play or F-Droid. It's a free, open-source app that adds address books like this one to Android's Contacts.</li>
        <li>Tap +, choose <em>Login with URL and user name</em>, and enter:
          <div class="grid copy">
            <span>Address</span><code>{info.book_url}</code>
            <button type="button" class="link" onclick={() => copy(info?.book_url ?? '', 'address')}>{copied === 'address' ? 'Copied' : 'Copy'}</button>
            <span>User name</span><code>{info.phone_username}</code>
            <button type="button" class="link" onclick={() => copy(info?.phone_username ?? '', 'user')}>{copied === 'user' ? 'Copied' : 'Copy'}</button>
          </div>
          and the password from the previous step.</li>
        <li>If it asks about the server's certificate, check it's for <strong>{bookHost}</strong>{#if info.bundled}, issued by <strong>FlipDial contacts server CA</strong>,{/if} and accept it. Do this at home.</li>
        <li>Turn on the <strong>{info.phone_name || bookName}</strong> address book. In the account settings you can limit syncing to your home Wi-Fi.</li>
      </ol>
    {/if}
    <p class="detail">
      <strong>Next:</strong> nothing is on the phone yet. Below, choose which contacts go to it (one by one, by tag or deck,
      or all), then press Sync now. They show up in the phone's Contacts app under {info.phone_name || bookName}.
    </p>
    <button type="button" class="link" onclick={() => (step = 'account')}>Back</button>
  {/if}
</div>

<style>
  .wizard {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 14px 16px;
    border-radius: 12px;
    border: 1px solid var(--line);
  }
  .steps {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 16px;
    margin: 0;
    padding: 0;
    list-style: none;
    counter-reset: s;
    font-size: 13px;
    color: var(--ash);
  }
  .steps li {
    counter-increment: s;
  }
  .steps li::before {
    content: counter(s) '. ';
  }
  .steps li.on {
    color: var(--bone);
    font-weight: 600;
  }
  .detail,
  .hint,
  .warn {
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
    align-items: center;
    gap: 8px;
    font-size: 14px;
  }
  input:not([type='radio']) {
    min-height: 38px;
    padding: 0 10px;
    border-radius: 8px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
  }
  .name {
    width: 10em;
  }
  .grid {
    display: grid;
    grid-template-columns: max-content minmax(0, 1fr);
    gap: 8px 12px;
    align-items: center;
    font-size: 14px;
  }
  .grid.copy {
    grid-template-columns: max-content minmax(0, 1fr) max-content;
    margin: 8px 0;
  }
  code {
    overflow-wrap: anywhere;
    font-size: 13px;
  }
  .how {
    margin: 0;
    padding-left: 20px;
    display: flex;
    flex-direction: column;
    gap: 6px;
    font-size: 14px;
    line-height: 1.5;
  }
  .result {
    margin: 0;
    padding: 0;
    list-style: none;
    font-size: 14px;
    color: var(--amber);
  }
  .result .ok {
    color: var(--bone);
  }
  .qr {
    display: flex;
    flex-wrap: wrap;
    gap: 16px;
    align-items: flex-start;
  }
  .qr img {
    width: 180px;
    height: 180px;
    border-radius: 8px;
    flex-shrink: 0;
  }
  .qr .how {
    flex: 1 1 240px;
  }
  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }
  .ways {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin: 0;
    padding: 0;
    border: 0;
  }
  .segmented {
    display: inline-flex;
    align-self: flex-start;
    border: 1px solid var(--line);
    border-radius: 10px;
    overflow: hidden;
  }
  .segmented button {
    min-height: 36px;
    padding: 0 14px;
    border: 0;
    background: transparent;
    color: var(--ash);
    font: inherit;
    font-size: 14px;
    cursor: pointer;
  }
  .segmented button[aria-pressed='true'] {
    background: var(--graphite);
    color: var(--bone);
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
  .primary:disabled,
  .secondary:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .secondary {
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
  }
  .link {
    border: 0;
    background: none;
    color: var(--amber);
    font: inherit;
    font-size: 13px;
    cursor: pointer;
    padding: 0;
    align-self: flex-start;
  }
  .error {
    margin: 0;
    color: var(--amber);
  }
</style>
