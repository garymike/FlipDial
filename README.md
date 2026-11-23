<p><img src="web/public/favicon.svg" width="72" height="72" alt="FlipDial icon"></p>

# FlipDial

**A self-hosted, visual contact manager for the business cards you collect.**

**[Try the live demo](https://garymike.github.io/FlipDial/)** with invented people. It runs entirely in your browser, and nothing you do there is saved.
Scan, review, dial through, and sync to any CardDAV server.

> Status: pre-release. Every v1 feature is built; v1 ships once the [release checklist](docs/release-checklist.md) passes, including accuracy testing on real cards.

## What it does

- **Keeps the card.** The original front and back scans are stored untouched, so the art on a card is never lost.
- **Reads it on your own hardware.** Name, title, company, email, phone and links are read from the card on a machine you control. Nothing leaves your network unless you turn that on.
- **You review before anything is saved.** Fields that may be wrong are flagged, and nothing is saved without your OK.
- **Syncs with standards.** Contacts are written as vCards to any CardDAV server (Synology Contacts, Nextcloud, Radicale, Baïkal and others).
- **Three ways to browse:**
  - **Wall:** every contact as a grid of cards
  - **Dial:** spin through your deck one card at a time. Drag, scroll, use the arrow keys, jump by letter, or type a name to dial straight to it
  - **Map:** where you met people
- **Mixes scanned and unscanned contacts.** Contacts without a scan get a generated "house card" so everything browses the same way.
- **Finds duplicates** and merges them field by field, with undo.
- **Sign-in and an activity log.** Sign in through your own identity provider or reverse proxy. Every change, export and sign-in is recorded in a log that can't be quietly edited.
- **Forget a contact.** Remove someone and every scan and record of them in one step.
- **Imports and exports.** Bring in vCard, Google or Outlook CSV, and your LinkedIn connections export; export vCard or CSV; download a full backup of contacts and scans that restores with fingerprint checks.

## How it fits together

```mermaid
flowchart LR
    A["Scanner or phone"] -->|saves images| B["Inbox folder"]
    B --> C["Read and crop<br/>each card"]
    C --> D["Review queue"]
    D -->|you approve| E["Your contacts<br/>(CardDAV server)"]
    C -->|originals kept| F["Card archive"]
    E --> G["FlipDial<br/>Wall, Dial, Map"]
    F --> G
```

1. Scan cards with any scanner or phone that can save to a folder.
2. FlipDial straightens each card, keeps the original images, and reads the contact details.
3. You check the details in the review queue.
4. Approved contacts are saved to your contacts server, and you browse them in FlipDial.

More detail in [docs/architecture.md](docs/architecture.md).

## Try it locally

```sh
# Backend: API and workers
cd backend
uv sync
cp ../config/flipdial.example.env .env   # then fill in your CardDAV server
uv run flipdial worker &                 # watch the inbox and read cards
uv run flipdial                          # API on http://127.0.0.1:8080

# Web app (development)
cd ../web
npm install
npm run dev                              # http://localhost:5173, talks to the API
```

The Docker image serves the built web app and the API together.

## Principles

- **Local first.** No cloud services, no tracking, no outside downloads.
- **Your data stays yours.** Standard vCard and CardDAV, plus full export of contacts and original scans.
- **Card text is untrusted input.** See [docs/threat-model.md](docs/threat-model.md).

## Documentation

| Doc | What it covers |
|---|---|
| [Build plan](docs/build-plan.md) | Phases, milestones, scope |
| [Architecture](docs/architecture.md) | Components and data flow |
| [Ingest](docs/ingest.md) | Scanner setup, pairing modes, what gets refused |
| [Reading cards](docs/extraction.md) | Fields, checks, flags, accuracy testing |
| [Contacts server](docs/carddav.md) | CardDAV setup, Synology, what is written and kept |
| [Duplicates](docs/duplicates.md) | How pairs are found, merging and undo |
| [Sign-in and activity log](docs/sign-in.md) | OpenID Connect or reverse-proxy sign-in, sessions, audit log |
| [Import and export](docs/import-export.md) | vCard, CSV and LinkedIn import, exports, backup and restore |
| [Data model](docs/data-model.md) | vCard fields and FlipDial extensions |
| [Threat model](docs/threat-model.md) | Assets, threats, mitigations |
| [Release checklist](docs/release-checklist.md) | What must pass before v1, including accuracy targets |
| [Contributing](CONTRIBUTING.md) | Setup and the no-private-data rule |
| [Security](SECURITY.md) | Reporting vulnerabilities |

## License

[MIT](LICENSE)
