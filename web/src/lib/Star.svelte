<script lang="ts">
  let { on, label, onclick }: { on: boolean; label: string; onclick: () => void } = $props()
</script>

<button type="button" class="star" aria-pressed={on} aria-label={label} {onclick}>
  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
    <path
      d="M10 2.5l2.3 4.8 5.2.7-3.8 3.6.9 5.2L10 14.3l-4.6 2.5.9-5.2L2.5 8l5.2-.7z"
      fill={on ? 'var(--amber)' : 'none'}
      stroke={on ? 'var(--amber)' : '#8f8a82'}
      stroke-width="1.5"
      stroke-linejoin="round"
    />
  </svg>
</button>

<style>
  .star {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    padding: 0;
    border: 0;
    border-radius: 10px;
    background: transparent;
    cursor: pointer;
  }
</style>
