# FlipDial

**A self-hosted, visual contact manager for the business cards you collect.**
Scan, review, dial through, and sync to any CardDAV server.

> Status: early scaffold. Nothing here is usable yet. See [docs/build-plan.md](docs/build-plan.md).

## What it does

- **Keeps the card.** The original front and back scans are stored untouched, so the art on a card is never lost.
- **Reads it locally.** A local vision model (Ollama by default) extracts name, title, company, email, phone and links. Nothing leaves your network unless you turn that on.
- **You review before anything is saved.** Low-confidence fields are flagged; nothing is written silently.
- **Syncs with standards.** Contacts are written as vCards to any CardDAV server (Synology Contacts, Nextcloud, Radicale, Baïkal and others).
- **Three ways to browse:**
  - **Wall:** every contact as a grid of cards
  - **Dial:** spin through your deck one card at a time
  - **Map:** where you met people
- **Mixes scanned and unscanned contacts.** Contacts without a scan get a generated "house card" so everything browses the same way.
- **Finds duplicates** and merges them field by field, with undo.

## How it fits together

```
scanner / phone  ──▶  inbox folder  ──▶  ingest + extraction  ──▶  review queue
                                                                       │
                       Wall · Dial · Map  ◀──  FlipDial web  ◀──────────┤
                                                                       ▼
                                                          CardDAV server (your contacts)
```

Any scanner that can save to a folder works. See [docs/architecture.md](docs/architecture.md).

## Principles

- **Local first.** No cloud model, no telemetry, no CDN.
- **Your data stays yours.** Standard vCard and CardDAV, plus full export of contacts and original scans.
- **Card text is untrusted input.** See [docs/threat-model.md](docs/threat-model.md).

## Documentation

| Doc | What it covers |
|---|---|
| [Build plan](docs/build-plan.md) | Phases, milestones, scope |
| [Architecture](docs/architecture.md) | Components and data flow |
| [Data model](docs/data-model.md) | vCard fields and FlipDial extensions |
| [Threat model](docs/threat-model.md) | Assets, threats, mitigations |
| [Contributing](CONTRIBUTING.md) | Setup and the no-private-data rule |
| [Security](SECURITY.md) | Reporting vulnerabilities |

## License

[MIT](LICENSE)
