<script lang="ts">
  import { api, DEMO, describe, type UpdateInfo } from './lib/api'
  import Dial from './lib/Dial.svelte'
  import Duplicates from './lib/Duplicates.svelte'
  import Review from './lib/Review.svelte'
  import Transfer from './lib/Transfer.svelte'
  import Activity from './lib/Activity.svelte'
  import Setup from './lib/Setup.svelte'
  import Trash from './lib/Trash.svelte'
  import { href, router } from './lib/router.svelte'
  import Wall from './lib/Wall.svelte'

  let query = $state('')
  let reviewCount = $state(0)

  async function refreshCount() {
    try {
      reviewCount = (await api.review()).ready
    } catch {
      reviewCount = 0
    }
  }

  $effect(() => {
    refreshCount()
  })

  let me = $state<{ user: string; mode: string } | null>(null)
  $effect(() => {
    api.me().then((m) => (me = m)).catch(() => (me = null))
  })

  // A plain warning across the app when something essential is broken (checked once per load).
  let broken = $state<string | null>(null)
  $effect(() => {
    api
      .status()
      .then((s) => (broken = s.items.find((i) => i.state === 'fail')?.label ?? null))
      .catch(() => (broken = null))
  })

  // New release banner, and the one-click update.
  let update = $state<UpdateInfo | null>(null)
  let updating = $state<'off' | 'running' | 'slow' | 'rolledback' | 'error'>('off')
  let updateError = $state('')
  const dismissKey = (tag: string) => `flipdial.update.later.${tag}`
  function showUpdate(u: UpdateInfo, asked = false) {
    let later = false
    try {
      later = !asked && !!u.release && localStorage.getItem(dismissKey(u.release.tag)) === '1'
    } catch {
      /* storage unavailable */
    }
    update = u.available && !later ? u : null
  }
  $effect(() => {
    api
      .updateInfo()
      .then((u) => showUpdate(u))
      .catch(() => (update = null))
  })
  // "Check now" on the Setup page: show the banner even if Later was chosen before.
  $effect(() => {
    const onCheck = (e: Event) => showUpdate((e as CustomEvent<UpdateInfo>).detail, true)
    window.addEventListener('flipdial:update-checked', onCheck)
    return () => window.removeEventListener('flipdial:update-checked', onCheck)
  })

  function later() {
    if (!update?.release) return
    try {
      localStorage.setItem(dismissKey(update.release.tag), '1')
    } catch {
      /* storage unavailable */
    }
    update = null
  }

  async function updateNow() {
    if (!update) return
    const from = update.current
    try {
      await api.startUpdate()
    } catch (e) {
      updateError = describe(e)
      updating = 'error'
      return
    }
    updating = 'running'
    const started = Date.now()
    let sawDown = false
    const timer = setInterval(async () => {
      try {
        const r = await fetch('/healthz', { cache: 'no-store' })
        const v = (await r.json()).version as string
        if (v !== from) {
          clearInterval(timer)
          location.reload()
        } else if (sawDown) {
          clearInterval(timer)
          updating = 'rolledback'
        }
      } catch {
        sawDown = true // restarting
      }
      if (Date.now() - started > 10 * 60 * 1000 && updating === 'running') updating = 'slow'
    }, 3000)
  }

  async function signOut() {
    try {
      await api.logout()
    } finally {
      location.assign('/auth/signed-out')
    }
  }

  const views = [
    { name: 'dial', label: 'Dial' },
    { name: 'wall', label: 'Wall' },
    { name: 'map', label: 'Map' },
  ] as const
</script>

{#if DEMO}
  <p class="demo-banner">
    Demo with invented people. Changes reset when you reload.
    <a href="https://github.com/garymike/FlipDial">Get FlipDial on GitHub</a>
  </p>
{/if}
<header>
  <a class="brand" href="#/" aria-label="FlipDial home">
    <img src={`${import.meta.env.BASE_URL}favicon.svg`} alt="" width="30" height="30" />
    <span>Flip<span class="accent">Dial</span></span>
  </a>
  <label class="search">
    <span class="sr">Search contacts</span>
    <input type="search" placeholder={router.route.name === 'dial' ? 'Dial to a name or company' : 'Search names, companies, events'} bind:value={query} />
  </label>
  <nav aria-label="View">
    {#each views as v (v.name)}
      <a href={href({ name: v.name })} aria-current={router.route.name === v.name ? 'page' : undefined}>{v.label}</a>
    {/each}
  </nav>
  <a class="review" href={href({ name: 'review' })} aria-current={router.route.name === 'review' ? 'page' : undefined}>
    Review {#if reviewCount}<span class="pill">{reviewCount}</span>{/if}
  </a>
  {#if me && me.mode === 'oidc'}
    <button type="button" class="signout" title={`Signed in as ${me.user}`} onclick={signOut}>Sign out</button>
  {/if}
</header>

{#if update?.release}
  <div class="update-bar" role="status">
    <span>
      <strong>FlipDial {update.release.tag} is available.</strong> You have {update.current}.
      <a href={update.release.url} target="_blank" rel="noopener noreferrer">What's new</a>
    </span>
    {#if update.can_update}
      <span class="update-actions">
        <button type="button" class="link-btn" onclick={later}>Later</button>
        <button type="button" class="update-btn" onclick={updateNow}>Update now</button>
      </span>
    {:else}
      <span class="update-how">
        {update.install === 'docker' ? 'Pull the new image to update.' : 'Run update to install it.'}
        <button type="button" class="link-btn" onclick={later}>Later</button>
      </span>
    {/if}
  </div>
{/if}

{#if updating !== 'off'}
  <div class="updating" role="alertdialog" aria-modal="true" aria-labelledby="updating-title">
    <div class="updating-box">
      {#if updating === 'running' || updating === 'slow'}
        <h2 id="updating-title">Updating FlipDial…</h2>
        <p>Checking the release signature, installing, and restarting. This takes a minute or two, and this page reloads by itself.</p>
        {#if updating === 'slow'}<p>This is taking longer than expected. Details are in <code>logs\update.log</code> in your data folder.</p>{/if}
      {:else if updating === 'rolledback'}
        <h2 id="updating-title">The update didn't finish</h2>
        <p>FlipDial is back on the version you had. Details are in <code>logs\update.log</code> in your data folder.</p>
        <button type="button" class="update-btn" onclick={() => location.reload()}>OK</button>
      {:else}
        <h2 id="updating-title">Couldn't start the update</h2>
        <p>{updateError}</p>
        <button type="button" class="update-btn" onclick={() => (updating = 'off')}>OK</button>
      {/if}
    </div>
  </div>
{/if}

{#if broken && router.route.name !== 'setup'}
  <p class="attention" role="status">
    FlipDial needs attention: {broken}. <a href={href({ name: 'setup' })}>Open the setup check</a>
  </p>
{/if}

{#if router.route.name === 'wall'}
  <Wall {query} open={router.route.uid ?? ''} />
{:else if router.route.name === 'dial'}
  <Dial {query} />
{:else if router.route.name === 'duplicates'}
  <Duplicates />
{:else if router.route.name === 'setup'}
  <Setup />
{:else if router.route.name === 'trash'}
  <Trash />
{:else if router.route.name === 'activity'}
  <Activity />
{:else if router.route.name === 'transfer'}
  <Transfer />
{:else if router.route.name === 'review'}
  <Review onchange={refreshCount} />
{:else}
  <main class="soon">
    <h1>Map view</h1>
    <p>Coming in v2.</p>
  </main>
{/if}

<style>
  .update-bar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 10px 20px;
    margin: 0;
    padding: 10px 32px;
    background: #2a2416;
    border-bottom: 1px solid #6a5426;
    font-size: 14px;
  }
  .update-bar a {
    margin-left: 6px;
  }
  .update-actions,
  .update-how {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .update-how {
    color: var(--ash);
  }
  .update-btn {
    min-height: 36px;
    padding: 0 16px;
    border: 0;
    border-radius: 8px;
    background: var(--amber);
    color: var(--ink);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
  }
  .link-btn {
    border: 0;
    background: transparent;
    color: var(--ash);
    font: inherit;
    cursor: pointer;
  }
  .updating {
    position: fixed;
    inset: 0;
    z-index: 100;
    display: grid;
    place-items: center;
    padding: 24px;
    background: rgba(10, 11, 13, 0.82);
  }
  .updating-box {
    max-width: 440px;
    padding: 28px;
    border-radius: 16px;
    background: var(--panel);
    border: 1px solid var(--line);
    line-height: 1.5;
  }
  .updating-box h2 {
    margin: 0 0 8px;
    font-family: var(--font-display);
  }
  .updating-box p {
    color: #d6d1c9;
  }
  .attention {
    margin: 0;
    padding: 10px 32px;
    background: #3a2422;
    border-bottom: 1px solid #6b3a35;
    font-size: 14px;
  }
  .attention a {
    margin-left: 6px;
  }
  .demo-banner {
    margin: 0;
    padding: 8px 16px;
    background: var(--amber);
    color: var(--ink);
    font-size: 13px;
    font-weight: 600;
    text-align: center;
  }
  .demo-banner a {
    color: var(--ink);
    margin-left: 6px;
  }
  header {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
    padding: 18px 32px;
    border-bottom: 1px solid #2c2f36;
  }
  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    color: var(--bone);
    text-decoration: none;
    font-family: var(--font-display);
    font-size: 22px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .accent {
    color: var(--amber);
  }
  .search {
    flex: 1 1 260px;
  }
  .search input {
    box-sizing: border-box;
    width: 100%;
    min-height: 44px;
    padding: 0 14px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
    font-size: 14px;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  nav {
    display: flex;
    padding: 3px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--graphite);
  }
  nav a {
    display: flex;
    align-items: center;
    min-height: 36px;
    padding: 0 14px;
    border-radius: 7px;
    color: #bdb8af;
    text-decoration: none;
    font-size: 13px;
    font-weight: 600;
  }
  nav a[aria-current='page'] {
    background: #2e3239;
    color: var(--bone);
  }
  .review {
    display: flex;
    align-items: center;
    gap: 8px;
    min-height: 44px;
    padding: 0 16px;
    border-radius: 10px;
    border: 1px solid var(--line);
    color: var(--bone);
    text-decoration: none;
    font-size: 14px;
  }
  .review[aria-current='page'] {
    border-color: var(--amber);
  }
  .signout {
    min-height: 44px;
    padding: 0 14px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: transparent;
    color: var(--ash);
    font: inherit;
    font-size: 13px;
    cursor: pointer;
  }
  .pill {
    padding: 1px 8px;
    border-radius: 999px;
    background: var(--amber);
    color: var(--ink);
    font-size: 12px;
    font-weight: 700;
  }
  .soon {
    padding: 48px 32px;
    color: var(--ash);
  }
  .soon h1 {
    margin: 0 0 8px;
    color: var(--bone);
    font-family: var(--font-display);
  }
</style>
