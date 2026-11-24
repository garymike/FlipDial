<script lang="ts">
  // The reading pane on a phone or tablet: full screen on a phone, sliding in from the right
  // over a dimmed page on a tablet. Escape, the backdrop or the pane's own close button closes
  // it, and the page behind doesn't scroll while it's open.
  import type { Snippet } from 'svelte'
  import { layout } from './layout.svelte'

  let { onclose, children }: { onclose: () => void; children: Snippet } = $props()

  $effect(() => {
    const before = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onkey = (e: KeyboardEvent) => e.key === 'Escape' && onclose()
    window.addEventListener('keydown', onkey)
    return () => {
      document.body.style.overflow = before
      window.removeEventListener('keydown', onkey)
    }
  })
</script>

<div class="sheet-layer {layout.mode}">
  <button type="button" class="backdrop" aria-label="Close" tabindex="-1" onclick={onclose}></button>
  <div class="sheet" role="dialog" aria-modal="true">
    {@render children()}
  </div>
</div>

<style>
  .sheet-layer {
    position: fixed;
    inset: 0;
    z-index: 200;
    isolation: isolate;
  }
  .backdrop {
    position: absolute;
    inset: 0;
    border: 0;
    padding: 0;
    background: rgba(0, 0, 0, 0.5);
    cursor: default;
  }
  .sheet {
    position: absolute;
    top: 0;
    right: 0;
    bottom: 0;
    width: 100%;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
    box-sizing: border-box;
    padding: max(12px, env(safe-area-inset-top)) 18px max(32px, env(safe-area-inset-bottom));
    background: var(--panel);
  }
  .tablet .sheet {
    width: min(560px, 72vw);
    border-left: 1px solid #2c2f36;
    box-shadow: -12px 0 32px rgba(0, 0, 0, 0.4);
    padding: 18px 24px 40px;
    animation: slide-in 0.25s ease;
  }
  @keyframes slide-in {
    from {
      transform: translateX(40px);
      opacity: 0;
    }
  }
  .phone .backdrop {
    display: none;
  }
</style>
