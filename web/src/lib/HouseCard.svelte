<script lang="ts">
  // The card FlipDial draws for a contact without a scan.
  import type { Contact } from './api'
  import type { CardColor } from './cardColor'

  // `tint`: the back of a scanned card that has no back, in the front's main color.
  let {
    contact,
    side = 'front',
    tint = null,
  }: { contact: Contact; side?: 'front' | 'back'; tint?: CardColor | null } = $props()

  const initials = $derived(
    contact.full_name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((w) => w[0]?.toUpperCase())
      .join(''),
  )
</script>

<div
  class="house"
  class:back={side === 'back'}
  class:tinted={!!tint}
  style:background={tint?.background}
  style:color={tint?.text}
>
  {#if side === 'front'}
    <div class="top">
      <span class="bar" aria-hidden="true"></span>
      <span class="mark" aria-hidden="true">{initials}</span>
    </div>
    <div>
      <div class="name">{contact.full_name}</div>
      {#if contact.title || contact.organization}
        <div class="sub">{[contact.title, contact.organization].filter(Boolean).join(' · ')}</div>
      {/if}
    </div>
    <span class="label">No scan · {contact.source}</span>
  {:else}
    <div class="org">{contact.organization || contact.full_name}</div>
    <div class="lines">
      {#each contact.emails.slice(0, 2) as e, i (i)}<span>{e.value}</span>{/each}
      {#each contact.phones.slice(0, 1) as p, i (i)}<span>{p.value}</span>{/each}
      {#each contact.websites.slice(0, 1) as w, i (i)}<span>{w.value.replace(/^https?:\/\//, '')}</span>{/each}
    </div>
  {/if}
</div>

<style>
  .house {
    position: absolute;
    inset: 0;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 22px 24px;
    border: 1.5px dashed #555a63;
    border-radius: 10px;
    background: #22252b;
    color: var(--bone);
    text-align: left;
    overflow: hidden;
  }
  .tinted {
    border: 0;
    transition: background-color 0.3s ease;
  }
  .tinted :global(*) {
    color: inherit;
  }
  .top {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }
  .bar {
    width: 44px;
    height: 6px;
    border-radius: 3px;
    background: #6b7079;
  }
  .mark {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    border: 2px solid #6b7079;
    font-size: 14px;
    font-weight: 600;
  }
  .name {
    font-size: 22px;
    font-weight: 600;
    line-height: 1.15;
  }
  .sub {
    margin-top: 6px;
    font-size: 13px;
    color: #d6d1c9;
  }
  .label {
    position: absolute;
    right: 18px;
    bottom: 16px;
    font-size: 11px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #b5b0a8;
  }
  .org {
    font-size: 12px;
    letter-spacing: 0.12em;
    text-transform: uppercase;
  }
  .lines {
    display: flex;
    flex-direction: column;
    gap: 2px;
    font-size: 13px;
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
</style>
