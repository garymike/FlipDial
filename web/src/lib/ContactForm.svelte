<script lang="ts">
  // Shared editing form for review and contact detail. Flags mark fields to check.
  import { PLATFORMS, type ContactInput } from './api'

  let {
    value = $bindable(),
    flags = [],
    idPrefix = 'f',
  }: { value: ContactInput; flags?: string[]; idPrefix?: string } = $props()

  const flagFor = (field: string) => {
    const f = flags.filter((x) => x.endsWith(`:${field}`)).map((x) => x.split(':')[0])
    if (f.includes('suspicious_text')) return 'Looks like instructions or code. Check it.'
    if (f.includes('found_in_text'))
      return field === 'socials'
        ? "Found on the card. Pick the platform, or remove it if it isn't one."
        : "Found in the card's text, but not where expected. Check it."
    if (f.includes('low_confidence')) return 'Unsure. Check it against the card.'
    return ''
  }

  const lists = ['emails', 'phones', 'websites'] as const
  const labels: Record<string, string> = {
    full_name: 'Name',
    title: 'Title',
    organization: 'Company',
    address: 'Address',
    emails: 'Email',
    phones: 'Phone',
    websites: 'Website',
    event: 'Event deck',
    met_on: 'Met on',
  }

  function addItem(key: (typeof lists)[number]) {
    value[key] = [...value[key], '']
  }
  function removeItem(key: (typeof lists)[number], i: number) {
    value[key] = value[key].filter((_, j) => j !== i)
  }
</script>

<div class="form">
  {#each ['full_name', 'title', 'organization'] as const as key (key)}
    <div class="field">
      <label for={`${idPrefix}-${key}`}>{labels[key]}</label>
      <input id={`${idPrefix}-${key}`} bind:value={value[key]} maxlength="200" class:flag={!!flagFor(key)} />
      {#if flagFor(key)}<span class="note">{flagFor(key)}</span>{/if}
    </div>
  {/each}

  {#each lists as key (key)}
    <fieldset class="field">
      <legend>{labels[key]}</legend>
      {#each value[key] as _, i (i)}
        <div class="multi">
          <input
            aria-label={`${labels[key]} ${i + 1}`}
            bind:value={value[key][i]}
            maxlength="200"
            class:flag={!!flagFor(key)}
          />
          <button type="button" class="remove" aria-label={`Remove ${labels[key]} ${i + 1}`} onclick={() => removeItem(key, i)}>×</button>
        </div>
      {/each}
      {#if flagFor(key)}<span class="note">{flagFor(key)}</span>{/if}
      <button type="button" class="add" onclick={() => addItem(key)}>+ Add {labels[key].toLowerCase()}</button>
    </fieldset>
  {/each}

  <fieldset class="field">
    <legend>Social</legend>
    {#each value.socials as s, i (i)}
      <div class="multi social">
        <select aria-label={`Platform ${i + 1}`} bind:value={value.socials[i].platform} class:flag={!s.platform && !!flagFor('socials')}>
          <option value="">Choose…</option>
          {#each PLATFORMS as p (p)}<option value={p}>{p}</option>{/each}
          {#if s.platform && !PLATFORMS.includes(s.platform as (typeof PLATFORMS)[number])}<option value={s.platform}>{s.platform}</option>{/if}
        </select>
        <input
          aria-label={`Handle ${i + 1}`}
          bind:value={value.socials[i].handle}
          maxlength="80"
          placeholder="handle or profile link"
          class:flag={!s.platform && !!flagFor('socials')}
        />
        <button type="button" class="remove" aria-label={`Remove social ${i + 1}`} onclick={() => (value.socials = value.socials.filter((_, j) => j !== i))}>×</button>
      </div>
    {/each}
    {#if flagFor('socials')}<span class="note">{flagFor('socials')}</span>{/if}
    <button type="button" class="add" onclick={() => (value.socials = [...value.socials, { platform: '', handle: '' }])}>+ Add social</button>
  </fieldset>

  <div class="field">
    <label for={`${idPrefix}-address`}>Address</label>
    <input id={`${idPrefix}-address`} bind:value={value.address} maxlength="200" class:flag={!!flagFor('address')} />
  </div>
  <div class="field">
    <label for={`${idPrefix}-about`}>About <span class="hint">what the card says: tagline, services</span></label>
    <textarea id={`${idPrefix}-about`} bind:value={value.about} maxlength="2000" rows="2" class:flag={!!flagFor('about')}></textarea>
    {#if flagFor('about')}<span class="note">{flagFor('about')}</span>{/if}
  </div>
  <div class="field">
    <label for={`${idPrefix}-note`}>Notes <span class="hint">yours: where you met, follow-ups</span></label>
    <textarea id={`${idPrefix}-note`} bind:value={value.note} maxlength="2000" rows="2"></textarea>
  </div>
  <div class="two">
    <div class="field">
      <label for={`${idPrefix}-event`}>Event deck</label>
      <input id={`${idPrefix}-event`} bind:value={value.event} maxlength="80" />
    </div>
    <div class="field">
      <label for={`${idPrefix}-met`}>Met on</label>
      <input id={`${idPrefix}-met`} type="date" bind:value={value.met_on} />
    </div>
  </div>
  <label class="check"><input type="checkbox" bind:checked={value.starred} /> Starred</label>
</div>

<style>
  .form {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 5px;
    margin: 0;
    padding: 0;
    border: 0;
    min-width: 0;
  }
  label,
  legend {
    font-size: 12px;
    color: var(--ash);
    padding: 0;
  }
  input,
  textarea,
  select {
    box-sizing: border-box;
    width: 100%;
    min-height: 44px;
    padding: 0 12px;
    border-radius: 9px;
    border: 1px solid var(--line);
    background: var(--graphite);
    color: var(--bone);
    font: inherit;
    font-size: 15px;
  }
  textarea {
    padding-top: 10px;
    padding-bottom: 10px;
    resize: vertical;
    line-height: 1.4;
    font-family: inherit;
  }
  .hint {
    color: var(--ash);
    font-weight: 400;
    margin-left: 6px;
  }
  .social select {
    flex: 0 0 140px;
    width: 140px;
  }
  input.flag,
  textarea.flag,
  select.flag {
    border-color: var(--amber);
  }
  input[type='checkbox'] {
    width: 18px;
    min-height: 18px;
    accent-color: var(--amber);
  }
  .note {
    font-size: 12px;
    color: var(--amber);
  }
  .multi {
    display: flex;
    gap: 6px;
  }
  .remove,
  .add {
    min-height: 44px;
    border-radius: 9px;
    border: 1px solid var(--line);
    background: transparent;
    color: var(--bone);
    font: inherit;
    cursor: pointer;
  }
  .remove {
    width: 44px;
    flex-shrink: 0;
    font-size: 18px;
  }
  .add {
    align-self: flex-start;
    padding: 0 12px;
    min-height: 36px;
    font-size: 13px;
    border-style: dashed;
  }
  .two {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }
  .check {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 14px;
    color: var(--bone);
  }
</style>
