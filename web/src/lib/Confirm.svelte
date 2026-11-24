<script lang="ts">
  // A confirmation dialog. Escape or Cancel closes it; focus starts on Cancel so Enter
  // never confirms by accident.
  import type { Snippet } from 'svelte'

  let {
    title,
    confirmLabel,
    danger = false,
    busy = false,
    onconfirm,
    oncancel,
    children,
  }: {
    title: string
    confirmLabel: string
    danger?: boolean
    busy?: boolean
    onconfirm: () => void
    oncancel: () => void
    children?: Snippet
  } = $props()

  let dialog: HTMLDialogElement
  let cancelBtn: HTMLButtonElement
  $effect(() => {
    dialog.showModal()
    cancelBtn.focus()
    return () => dialog.open && dialog.close()
  })
</script>

<dialog
  bind:this={dialog}
  aria-labelledby="confirm-title"
  oncancel={(e) => {
    e.preventDefault()
    oncancel()
  }}
  onclick={(e) => e.target === dialog && oncancel()}
>
  <div class="box">
    <h2 id="confirm-title">{title}</h2>
    {#if children}<div class="body">{@render children()}</div>{/if}
    <div class="buttons">
      <button type="button" class="secondary" bind:this={cancelBtn} onclick={oncancel}>Cancel</button>
      <button type="button" class={danger ? 'danger' : 'primary'} onclick={onconfirm} disabled={busy}>
        {busy ? 'Working…' : confirmLabel}
      </button>
    </div>
  </div>
</dialog>

<style>
  dialog {
    padding: 0;
    border: 1px solid #3a3d44;
    border-radius: 14px;
    background: var(--panel);
    color: inherit;
    max-width: min(440px, calc(100vw - 32px));
  }
  dialog::backdrop {
    background: rgba(0, 0, 0, 0.55);
  }
  .box {
    display: flex;
    flex-direction: column;
    gap: 14px;
    padding: 22px 24px;
  }
  h2 {
    margin: 0;
    font-size: 18px;
  }
  .body {
    font-size: 14px;
    line-height: 1.5;
    color: #d6d1c9;
  }
  .body :global(p) {
    margin: 0 0 8px;
  }
  .buttons {
    display: flex;
    justify-content: flex-end;
    gap: 10px;
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
</style>
