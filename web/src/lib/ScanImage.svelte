<script lang="ts">
  // A scanned card image with 2px trimmed off every edge, to hide the thin white line many
  // scanners leave. Display only: the files are never changed.
  //
  // The trim has to follow the picture, not the box it sits in: a tall card shown in a wide
  // frame is letterboxed, and its edges are inside the frame. So the image gets its own box,
  // sized to its shape and fitted into the frame, and is drawn 2px larger on each side
  // inside it.
  //
  // fit="fill": fill the positioned parent (the flip card).
  // fit="frame": a box of the given aspect ratio, full width (thumbnails).
  // fit="natural": the image's own shape, full width (the large review image).
  let {
    src,
    alt = '',
    fit = 'frame',
    aspect = 1.75,
    lazy = true,
    onratio,
    card = false,
  }: {
    src: string
    alt?: string
    fit?: 'fill' | 'frame' | 'natural'
    aspect?: number
    lazy?: boolean
    onratio?: (r: number) => void
    card?: boolean // rounded corners and a shadow on the picture itself
  } = $props()

  let ratio = $state(1.75)
  function loaded(e: Event) {
    const img = e.currentTarget as HTMLImageElement
    if (img.naturalWidth && img.naturalHeight) {
      ratio = img.naturalWidth / img.naturalHeight
      onratio?.(ratio)
    }
  }
</script>

<span class="scan {fit}" class:card style:--frame={aspect} style:--r={ratio}>
  <span class="box">
    <img {src} {alt} loading={lazy ? 'lazy' : 'eager'} draggable="false" onload={loaded} />
  </span>
</span>

<style>
  .scan {
    display: grid;
    place-items: center;
    container-type: size;
    width: 100%;
  }
  .fill {
    position: absolute;
    inset: 0;
  }
  .frame {
    aspect-ratio: var(--frame);
  }
  .natural {
    aspect-ratio: var(--r);
    max-height: inherit;
  }
  .box {
    position: relative;
    overflow: hidden;
    border-radius: inherit;
    /* object-fit: contain, done by hand so the box hugs the picture */
    width: min(100cqw, 100cqh * var(--r));
    height: min(100cqh, 100cqw / var(--r));
  }
  .card .box {
    border-radius: 10px;
    box-shadow: 0 10px 24px rgba(0, 0, 0, 0.35);
  }
  img {
    position: absolute;
    left: -2px;
    top: -2px;
    width: calc(100% + 4px);
    height: calc(100% + 4px);
    object-fit: cover;
    display: block;
    -webkit-user-drag: none;
    user-select: none;
  }
</style>
