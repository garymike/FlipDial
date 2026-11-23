<script lang="ts">
  type View = 'wall' | 'dial' | 'map'
  let view = $state<View>('wall')
  const views: { id: View; label: string }[] = [
    { id: 'wall', label: 'Wall' },
    { id: 'dial', label: 'Dial' },
    { id: 'map', label: 'Map' },
  ]
</script>

<header>
  <a class="brand" href="/" aria-label="FlipDial home">
    <img src="/favicon.svg" alt="" width="30" height="30" />
    <span>Flip<span class="accent">Dial</span></span>
  </a>
  <nav aria-label="View">
    {#each views as v (v.id)}
      <button type="button" aria-pressed={view === v.id} onclick={() => (view = v.id)}>
        {v.label}
      </button>
    {/each}
  </nav>
</header>

<main>
  <p class="placeholder">{views.find((v) => v.id === view)?.label} view is coming in a later milestone.</p>
</main>

<style>
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
  nav {
    display: flex;
    margin-left: auto;
    padding: 3px;
    border: 1px solid var(--line);
    border-radius: 10px;
    background: var(--graphite);
  }
  nav button {
    min-height: 36px;
    padding: 0 14px;
    border: 0;
    border-radius: 7px;
    background: transparent;
    color: #bdb8af;
    font: inherit;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  nav button[aria-pressed='true'] {
    background: #2e3239;
    color: var(--bone);
  }
  main {
    padding: 32px;
  }
  .placeholder {
    color: var(--ash);
  }
</style>
