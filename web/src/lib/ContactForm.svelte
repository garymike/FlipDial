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

  // Name parts follow the Name field until someone edits them directly.
  let partsTouched = false
  let showName = $state(!!(value.prefix || value.middle_name || value.suffix || value.nickname))
  const touched = () => (partsTouched = true)
  function nameChanged() {
    if (partsTouched) return
    let name = value.full_name.trim()
    const pre = (value.prefix ?? '').trim()
    const suf = (value.suffix ?? '').trim()
    if (pre && name.toLowerCase().startsWith(pre.toLowerCase())) name = name.slice(pre.length)
    if (suf && name.toLowerCase().endsWith(suf.toLowerCase())) name = name.slice(0, -suf.length)
    const words = name.replace(/^[\s,]+|[\s,]+$/g, '').split(/\s+/).filter(Boolean)
    const middle = !!value.middle_name && words.length >= 3
    value.given_name = words.length < 2 ? words.join(' ') : middle ? words[0] : words.slice(0, -1).join(' ')
    value.middle_name = middle ? words.slice(1, -1).join(' ') : ''
    value.family_name = words.length < 2 ? '' : words[words.length - 1]
  }

  // Birthday as month, day and an optional year; stored as YYYY-MM-DD or --MM-DD.
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
  type Parts = { year: string; month: string; day: string }
  function parseBirthday(v: string): Parts {
    const m = /^(\d{4}|-)-(\d{2})-(\d{2})$/.exec(v)
    return m ? { year: m[1] === '-' ? '' : m[1], month: m[2], day: String(Number(m[3])) } : { year: '', month: '', day: '' }
  }
  // What's typed so far, which can be incomplete (a month with no day yet).
  let bday = $state<Parts>({ year: '', month: '', day: '' })
  let written: string | null = null
  $effect(() => {
    const v = value.birthday ?? ''
    if (v !== written) {
      bday = parseBirthday(v)
      written = v
    }
  })
  function setBirthday(part: keyof Parts, v: string) {
    bday[part] = v.trim()
    const day = Number(bday.day)
    let next = value.birthday ?? ''
    if (bday.month && day >= 1 && day <= 31) {
      const dd = String(day).padStart(2, '0')
      next = /^\d{4}$/.test(bday.year) ? `${bday.year}-${bday.month}-${dd}` : `--${bday.month}-${dd}`
    } else if (!bday.month && !bday.day && !bday.year) {
      next = ''
    }
    written = next
    value.birthday = next
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
  <div class="field">
    <label for={`${idPrefix}-full_name`}>Name</label>
    <input id={`${idPrefix}-full_name`} bind:value={value.full_name} oninput={nameChanged} maxlength="200" class:flag={!!flagFor('full_name')} />
    {#if flagFor('full_name')}<span class="note">{flagFor('full_name')}</span>{/if}
    {#if showName}
      <div class="name-parts">
        <input aria-label="Prefix" placeholder="Prefix" bind:value={value.prefix} oninput={nameChanged} maxlength="80" />
        <input aria-label="First name" placeholder="First" bind:value={value.given_name} oninput={touched} maxlength="200" />
        <input aria-label="Middle name" placeholder="Middle" bind:value={value.middle_name} oninput={touched} maxlength="200" />
        <input aria-label="Last name" placeholder="Last" bind:value={value.family_name} oninput={touched} maxlength="200" />
        <input aria-label="Suffix" placeholder="Suffix" bind:value={value.suffix} oninput={nameChanged} maxlength="80" />
      </div>
      <input aria-label="Nickname" placeholder="Nickname" bind:value={value.nickname} maxlength="200" />
    {:else}
      <button type="button" class="add" onclick={() => (showName = true)}>+ Name parts and nickname</button>
    {/if}
  </div>
  <div class="field">
    <label for={`${idPrefix}-title`}>Title</label>
    <input id={`${idPrefix}-title`} bind:value={value.title} maxlength="200" class:flag={!!flagFor('title')} />
    {#if flagFor('title')}<span class="note">{flagFor('title')}</span>{/if}
  </div>
  <div class="two">
    <div class="field">
      <label for={`${idPrefix}-organization`}>Company</label>
      <input id={`${idPrefix}-organization`} bind:value={value.organization} maxlength="200" class:flag={!!flagFor('organization')} />
      {#if flagFor('organization')}<span class="note">{flagFor('organization')}</span>{/if}
    </div>
    <div class="field">
      <label for={`${idPrefix}-department`}>Department</label>
      <input id={`${idPrefix}-department`} bind:value={value.department} maxlength="200" class:flag={!!flagFor('department')} />
    </div>
  </div>

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
  <fieldset class="field">
    <legend>Birthday</legend>
    <div class="birthday">
      <select aria-label="Birthday month" value={bday.month} onchange={(e) => setBirthday('month', e.currentTarget.value)}>
        <option value="">Month</option>
        {#each MONTHS as m, i (m)}<option value={String(i + 1).padStart(2, '0')}>{m}</option>{/each}
      </select>
      <input aria-label="Birthday day" placeholder="Day" inputmode="numeric" maxlength="2" value={bday.day} onchange={(e) => setBirthday('day', e.currentTarget.value)} />
      <input aria-label="Birthday year (optional)" placeholder="Year" inputmode="numeric" maxlength="4" value={bday.year} onchange={(e) => setBirthday('year', e.currentTarget.value)} />
      {#if value.birthday}
        <button type="button" class="remove" aria-label="Clear birthday" onclick={() => (value.birthday = '')}>×</button>
      {/if}
    </div>
  </fieldset>
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
  .name-parts {
    display: grid;
    grid-template-columns: 0.7fr 1fr 1fr 1fr 0.7fr;
    gap: 6px;
  }
  .name-parts input {
    min-width: 0;
  }
  @media (max-width: 700px) {
    .name-parts {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
  .birthday {
    display: grid;
    grid-template-columns: 2fr 1fr 1fr auto;
    gap: 6px;
  }
  .birthday input,
  .birthday select {
    min-width: 0;
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
