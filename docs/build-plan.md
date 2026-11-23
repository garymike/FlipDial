# Build plan

## Scope

### v1: capture to contacts

| Area | Included |
|---|---|
| Ingest | Watched inbox folder, front/back pairing (duplex scanners and phone uploads), auto-crop and straighten |
| Extraction | Local vision model via Ollama or any OpenAI-compatible endpoint, strict JSON schema, per-field confidence |
| Review | Review queue (desktop and phone), flagged low-confidence fields, event deck assignment, quick note |
| Storage | Original scans kept untouched; derived crops and thumbnails regenerable |
| Sync | CardDAV read/write (tested against Synology Contacts, Nextcloud, Radicale) |
| Browse | Wall, Dial, card detail, house cards for unscanned contacts, starred contacts, filters |
| Data quality | Duplicate detection, field-by-field merge with undo, attach scan to existing contact |
| Import / export | vCard, CSV with column mapping, LinkedIn data export; full backup archive (contacts + scans + manifest) |
| Operations | Structured JSON logs without PII, audit log, OIDC sign-in, Docker images |

### v2: context and connections

Map view, relationship graph and degrees of separation, enrichment review, visual search (local image embeddings), voice notes (local transcription), follow-up reminders over CalDAV, read-only MCP server, desk mode.

### Out of scope

Scraping LinkedIn or any other site, cloud processing by default, sales pipelines and deal tracking (pair FlipDial with a CRM instead).

## Milestones

| # | Milestone | Done when |
|---|---|---|
| 0 | Scaffold (done) | Repo, docs, CI, config, logging, health endpoint |
| 1 | Ingest (done) | A dropped image pair becomes a cropped, paired item in the review queue |
| 2 | Extraction (done) | Items carry schema-validated fields with confidence; accuracy measured on a private test set |
| 3 | CardDAV (done) | Approved items are written to and read from a CardDAV server; round-trip tests pass |
| 4 | Wall + detail (done) | Browse, filter, star, flip, edit |
| 5 | Dial (done) | Drag, scroll, keyboard, search-to-dial, reduced motion |
| 6 | Duplicates + merge (done) | Ranked duplicate queue, merge with undo |
| 7 | Import / export (done) | vCard, CSV, LinkedIn export in; vCard, CSV, backup archive out |
| 8 | Hardening + v1 | Auth, audit log, threat model review, signed release with SBOM, and every item in the [release checklist](release-checklist.md), including the accuracy gate |

## Repo layout

```
backend/        Python package: API, ingest worker, extraction, CardDAV adapter
web/            Svelte + Vite front end
config/         Example configuration (no real values)
docker/         Container build files and example compose
docs/           Plan, architecture, data model, threat model
demo/           Fake demo data only
```

## Accuracy testing

Run `flipdial eval` on the private test set after any change to extraction (instructions, schema, validation, or the recommended model) and keep the counts-only report with the change. v1 does not ship until the accuracy gate in the [release checklist](release-checklist.md) passes.

## Rules that apply to every milestone

- No private data in the repo. See [CONTRIBUTING.md](../CONTRIBUTING.md).
- Every network call is configurable and off unless needed. CI runs the pipeline with no network.
- Card text, imported files and model output are untrusted input.
