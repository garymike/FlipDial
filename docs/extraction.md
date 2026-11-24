# Reading cards

After a card is archived, the extraction step reads its contact details and puts the card in the review queue. Nothing is saved to your contacts until you approve it.

```mermaid
flowchart LR
    A["Archived card"] --> B["Send cropped images<br/>to the reader"]
    B --> C["Check every field"]
    C -->|ok| D["Review queue"]
    C -->|odd or unsure| E["Review queue<br/>with flags"]
    B -->|no answer| F["Retry, then<br/>mark as failed"]
```

## Run it

```sh
flipdial extract          # keep watching for new cards
flipdial extract --once   # read what is waiting and exit
flipdial worker           # ingest and extract together
```

## Where it runs

The reader is an Ollama server by default, or any OpenAI-compatible endpoint.

```sh
FLIPDIAL_MODEL_BACKEND=ollama            # or openai_compatible
FLIPDIAL_MODEL_URL=http://127.0.0.1:11434
FLIPDIAL_MODEL_NAME=qwen3.5:9b
```

Any vision model works: one whose `ollama show` lists **vision** under Capabilities. The default is `qwen3.5:9b`; `gemma4:12b` is another good candidate. Compare models on your own cards with `flipdial eval` and keep the one that scores best. Newer Ollama versions can no longer run `llama3.2-vision` (it fails with "unknown model architecture: 'mllama'"). The [Setup check](windows.md#when-cards-arent-being-read) shows Ollama's message when a model can't be loaded.

FlipDial refuses to start if the URL points outside your local network, because card images would leave it. Set `FLIPDIAL_ALLOW_REMOTE_MODEL=true` only if you mean to.

## Fields read from a card

Full name, given and family name, title, company, email addresses, phone numbers, websites, social handles (including messaging apps like WhatsApp), address, and **About**: any other printed description, such as a tagline or a list of services. Each value comes with a confidence score.

**Notes** are yours (where you met, follow-ups) and are never filled in by the model. They're saved as the contact's standard note, which phones and Synology show. About is saved in a FlipDial field that other apps keep but don't display.

## How a card is read

1. The model first copies every printed line of the card, top to bottom, then fills in the fields from that copy. Copying first makes it much less likely to skip a value.
2. **Safety net:** any email address, phone number or website in the copied text that isn't in a field is added by FlipDial and highlighted ("Found in the card's text") for you to check.
3. **Social profiles:** any platform, each with a handle. A row of platform icons next to one handle becomes one entry per platform. Names are tidied (Twitter becomes X), and profile links are built for the contact page. A handle seen only in the card's text is added with the platform left for you to choose. Profiles are saved in the form Apple Contacts uses, so phones show them too.
4. While a card is read, Review shows live progress: the stage, a timer, the lines being copied, then each field as it's found. This is a preview only; the final answer is checked in full before anything is shown for review.

## How the output is checked

Everything the reader returns is treated as untrusted:

- Only the fields above are kept. Anything else is dropped.
- Text is cleaned to a single plain line and capped at 200 characters.
- Emails, phone numbers, websites and handles must look right or they are removed. Links must be `http` or `https` and cannot carry a user name or password.
- The reader gets a fixed set of instructions, the card images and the field list. It cannot call tools, browse, or take any action.

Cards are flagged for a closer look when:

| Flag | Meaning |
|---|---|
| `low_confidence:<field>` | The reader was unsure about this value |
| `suspicious_text:<field>` | The text reads like instructions or code. It is shown as plain text and never acted on |
| `values_dropped` | Some values failed the checks and were removed |
| `no_name_or_company` | Neither a name nor a company was found |

## Retries

If the reader cannot be reached or returns something unusable, the card stays queued and is retried. After `FLIPDIAL_EXTRACT_MAX_ATTEMPTS` (default 3) it is marked as failed so it can be read again later or entered by hand.

## Measuring accuracy

Keep a set of your own scanned cards in a folder **outside this repository**. The easy way is to scan them, then let FlipDial build the folders:

```sh
# Scanner (duplex JPEGs, front then back). Your raw scans are left untouched.
flipdial testset make C:\flipdial-testset\raw C:\flipdial-testset\cards
# Phone photos go into the same test set; numbering continues
flipdial testset make C:\flipdial-testset\phone C:\flipdial-testset\cards --mode single
```

This runs the real ingest steps (pairing, blank-back detection, cropping) on a copy of the scans, so the test uses exactly the images the reader sees in normal use. Each card gets a folder with a blank `expected.json`. Fill each one in by hand from the physical card, not from what FlipDial reads, then check your progress:

```sh
flipdial testset check C:\flipdial-testset\cards
```

`make` refuses to write inside a git repository, so a test set can't end up committed by accident.

The layout, if you build one by hand:

```
my-testset/
  card-01/front.jpg
  card-01/back.jpg          (optional)
  card-01/expected.json     {"full_name": "...", "organization": "...",
                             "emails": ["..."], "phones": ["..."], "websites": ["..."]}
```

```sh
flipdial eval --testset /path/to/my-testset
```

Aim for the mix in the [release checklist](release-checklist.md): at least 30 cards, including artistic cards, cards with backs, tall or square cards, and a few phone photos.

The report lists, per field, how many values were expected, how many were right, and how many extra values appeared that are not on the card. It never prints names, values or folder names, so it is safe to share.

## Read again (saved contacts)

Open a contact and choose **Read again** to read its card once more with the current model,
for example after a model or FlipDial update improves reading. The worker reads it in the
background, then the pane lists only the fields that changed, with the saved value beside
the new one. For each one you pick **Use new**, **Keep current**, or for emails, phones and
websites **Add the new ones**. Only what you choose is saved, through a normal edit.

A new reading never clears a field: if the card no longer seems to show something, the saved
value stays. Notes, the event deck, the star and anything other apps added are never part of
the comparison. The proposal is kept until you apply or discard it, and "Forget this
contact" removes it with everything else.
