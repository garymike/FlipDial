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
    adapt = false,
    tall = 1.75,
  }: {
    contact: Contact
    flipped?: boolean
    size?: 'thumb' | 'large'
    adapt?: boolean
    tall?: number // frame shape (width / height) for a tall card; smaller means taller
  } = $props()


  const front = $derived(
    contact.card_id ? api.image(contact.card_id, size === 'large' ? 'front' : 'thumb', contact.card_view) : null,
  )
  const back = $derived(contact.card_id && contact.has_back ? api.image(contact.card_id, 'back', contact.card_view) : null)

  // The frame takes the shape of the side shown, so a wider or squarer card fills the width
  // with no bars. A tall card does too where `adapt` is set (the reading pane); elsewhere it
  // stands upright inside the usual shape, with nothing drawn around it.
  let frontRatio = $state(1.75)
  let backRatio = $state(1.75)
  const shownRatio = $derived(flipped && back ? backRatio : frontRatio)
  const frameRatio = $derived(adapt || shownRatio >= 1 ? shownRatio : Math.max(shownRatio, tall))

  // A scan with no back: show its details on a back in the front's main color.
  let tint = $state<CardColor | null>(null)
  $effect(() => {
    const id = contact.card_id
    if (!id || back) {
      tint = null
      return
    }
    let live = true
    cardColor(api.image(id, 'thumb', contact.card_view)).then((c) => {
      if (live) tint = c
    })
    return () => {
      live = false
    }
  })
</script>

<div class="frame" class:adapt style:aspect-ratio={frameRatio}>
  <div class="inner" class:flipped>
    <div class="face" class:scan={!!front}>
      {#if front}
        <ScanImage src={front} alt={`Front of ${contact.full_name}'s card`} fit="fill" card onratio={(r) => (frontRatio = r)} />
      {:else}
        <HouseCard {contact} />
      {/if}
    </div>
    <div class="face backface" class:scan={!!back}>
      {#if back}
        <ScanImage src={back} alt={`Back of ${contact.full_name}'s card`} fit="fill" card onratio={(r) => (backRatio = r)} />
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
  .frame.adapt {
    max-height: 70vh;
    margin: 0 auto;
    transition: aspect-ratio 0.3s ease;
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
  /* A scan draws its own rounded edge and shadow, hugging the picture, so a card of another
     shape never shows a dark box around it. */
  .face.scan {
    background: transparent;
    box-shadow: none;
    overflow: visible;
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
    /* A scan draws its own rounded edge and shadow, hugging the picture, so a card of another
     shape never shows a dark box around it. */
  .face.scan {
    background: transparent;
    box-shadow: none;
    overflow: visible;
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
