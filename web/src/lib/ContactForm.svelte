<script lang="ts">
  // Shared editing form for review and contact detail. Flags mark fields to check.
  import { KINDS, PLATFORMS, blankAddress, blankTyped, type ContactInput } from './api'

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

  // New rows default to the most common type for business contacts.
  function addItem(key: (typeof lists)[number]) {
    const used = new Set(value[key].map((t) => t.kind))
    const kind = key === 'phones' && used.has('work') && !used.has('mobile') ? 'mobile' : 'work'
    value[key] = [...value[key], blankTyped(kind)]
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
        <div class="multi typed">
          <select aria-label={`${labels[key]} ${i + 1} type`} bind:value={value[key][i].kind}>
            {#each KINDS[key] as [k, name] (k)}<option value={k}>{name}</option>{/each}
          </select>
          <input
            aria-label={`${labels[key]} ${i + 1}`}
            bind:value={value[key][i].value}
            maxlength="200"
            class:flag={!!flagFor(key)}
          />
          <button type="button" class="remove" aria-label={`Remove ${labels[key]} ${i + 1}`} onclick={() => removeItem(key, i)}>×</button>
          {#if value[key][i].kind === 'custom'}
            <input
              class="label"
              aria-label={`${labels[key]} ${i + 1} label`}
              placeholder="Label, e.g. Assistant"
              bind:value={value[key][i].label}
              maxlength="40"
            />
          {/if}
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

  <fieldset class="field">
    <legend>Address</legend>
    {#each value.addresses as a, i (i)}
      {@const n = value.addresses.length > 1 ? ` ${i + 1}` : ''}
      <div class="address">
        <div class="multi">
          <select aria-label={`Address${n} type`} bind:value={value.addresses[i].kind}>
            {#each KINDS.addresses as [k, name] (k)}<option value={k}>{name}</option>{/each}
          </select>
          {#if a.kind === 'custom'}
            <input class="grow" aria-label={`Address${n} label`} placeholder="Label" bind:value={value.addresses[i].label} maxlength="40" />
          {:else}<span class="grow"></span>{/if}
          <button type="button" class="remove" aria-label={`Remove address${n}`} onclick={() => (value.addresses = value.addresses.filter((_, j) => j !== i))}>×</button>
        </div>
        <textarea aria-label={`Street${n}`} placeholder="Street" rows="2" maxlength="500" bind:value={value.addresses[i].street} class:flag={!!flagFor('address')}></textarea>
        <div class="parts">
          <input aria-label={`City${n}`} placeholder="City" maxlength="200" bind:value={value.addresses[i].city} />
          <input aria-label={`State or region${n}`} placeholder="State" maxlength="200" bind:value={value.addresses[i].region} />
          <input aria-label={`Postal code${n}`} placeholder="ZIP" maxlength="80" bind:value={value.addresses[i].postal_code} />
        </div>
        <input aria-label={`Country${n}`} placeholder="Country" maxlength="200" bind:value={value.addresses[i].country} />
      </div>
    {/each}
    {#if flagFor('address')}<span class="note">{flagFor('address')}</span>{/if}
    <button type="button" class="add" onclick={() => (value.addresses = [...value.addresses, blankAddress(value.addresses.length ? 'home' : 'work')])}>+ Add address</button>
  </fieldset>
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
  .typed {
    flex-wrap: wrap;
  }
  .typed select {
    flex: 0 0 auto;
    width: 7.5em;
  }
  .typed input:not(.label) {
    flex: 1 1 10em;
    min-width: 0;
  }
  .typed .label {
    flex: 1 0 100%;
  }
  .address {
    display: flex;
    flex-direction: column;
    gap: 6px;
    padding-bottom: 8px;
  }
  .address .grow {
    flex: 1;
  }
  .parts {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr;
    gap: 6px;
  }
  .parts input {
    min-width: 0;
  }
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
