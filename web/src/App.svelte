<script lang="ts">
  import { api, DEMO } from './lib/api'
  import ContactDetail from './lib/ContactDetail.svelte'
  import Dial from './lib/Dial.svelte'
  import Duplicates from './lib/Duplicates.svelte'
  import Review from './lib/Review.svelte'
  import Transfer from './lib/Transfer.svelte'
  import Activity from './lib/Activity.svelte'
  import Setup from './lib/Setup.svelte'
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

  async function signOut() {
    try {
      await api.logout()
    } finally {
      location.assign('/auth/signed-out')
    }
  }

  const views = [
    { name: 'wall', label: 'Wall' },
    { name: 'dial', label: 'Dial' },
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
  <a class="brand" href={href({ name: 'wall' })} aria-label="FlipDial home">
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

{#if broken && router.route.name !== 'setup'}
  <p class="attention" role="status">
    FlipDial needs attention: {broken}. <a href={href({ name: 'setup' })}>Open the setup check</a>
  </p>
{/if}

{#if router.route.name === 'wall'}
  <Wall {query} />
{:else if router.route.name === 'dial'}
  <Dial {query} />
{:else if router.route.name === 'duplicates'}
  <Duplicates />
{:else if router.route.name === 'setup'}
  <Setup />
{:else if router.route.name === 'activity'}
  <Activity />
{:else if router.route.name === 'transfer'}
  <Transfer />
{:else if router.route.name === 'review'}
  <Review onchange={refreshCount} />
{:else if router.route.name === 'contact'}
  {#key router.route.uid}<ContactDetail uid={router.route.uid} />{/key}
{:else}
  <main class="soon">
    <h1>Map view</h1>
    <p>Coming in v2.</p>
  </main>
{/if}

<style>
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
