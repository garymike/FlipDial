<script lang="ts">
  // A card that flips between front and back. Scans show the real images; contacts
  // without a scan show the generated house card.
  import { api, type Contact } from './api'
  import HouseCard from './HouseCard.svelte'
  import ScanImage from './ScanImage.svelte'
  import { cardColor, type CardColor } from './cardColor'

  let {
    contact,
    flipped = false,
    size = 'thumb',
  }: { contact: Contact; flipped?: boolean; size?: 'thumb' | 'large' } = $props()

  const front = $derived(
    contact.card_id ? api.image(contact.card_id, size === 'large' ? 'front' : 'thumb') : null,
  )
  const back = $derived(contact.card_id && contact.has_back ? api.image(contact.card_id, 'back') : null)

  // A scan with no back: show its details on a back in the front's main color.
  let tint = $state<CardColor | null>(null)
  $effect(() => {
    const id = contact.card_id
    if (!id || back) {
      tint = null
      return
    }
    let live = true
    cardColor(api.image(id, 'thumb')).then((c) => {
      if (live) tint = c
    })
    return () => {
      live = false
    }
  })
</script>

<div class="frame">
  <div class="inner" class:flipped>
    <div class="face">
      {#if front}
        <ScanImage src={front} alt={`Front of ${contact.full_name}'s card`} fit="fill" />
      {:else}
        <HouseCard {contact} />
      {/if}
    </div>
    <div class="face backface">
      {#if back}
        <ScanImage src={back} alt={`Back of ${contact.full_name}'s card`} fit="fill" />
      {:else}
        <HouseCard {contact} side="back" {tint} />
      {/if}
    </div>
  </div>
</div>

<style>
  .frame {
    position: relative;
    width: 100%;
    aspect-ratio: 1.75;
    perspective: 1200px;
  }
  .inner {
    position: relative;
    width: 100%;
    height: 100%;
    transform-style: preserve-3d;
    transition: transform 0.6s cubic-bezier(0.2, 0.7, 0.2, 1);
  }
  .inner.flipped {
    transform: rotateY(180deg);
  }
  .face {
    position: absolute;
    inset: 0;
    backface-visibility: hidden;
    border-radius: 10px;
    overflow: hidden;
    background: #111214;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
  }
  .backface {
    transform: rotateY(180deg);
  }
  /* Animations turned off in the system: swap sides with a quick fade instead of a turn. */
  @media (prefers-reduced-motion: reduce) {
    .inner {
      transition: none;
    }
    .face {
      transition: opacity 0.2s ease;
    }
    .inner.flipped {
      transform: none;
    }
    .backface {
      transform: none;
      opacity: 0;
    }
    .inner.flipped .face:not(.backface) {
      opacity: 0;
    }
    .inner.flipped .backface {
      opacity: 1;
    }
  }
</style>
