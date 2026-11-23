# Architecture

## Components

| Component | Runs on | Job |
|---|---|---|
| Capture | Any scanner or phone | Saves images to the inbox folder. FlipDial does not drive scanners. |
| Ingest worker | Machine with the model (GPU optional) | Watches the inbox, pairs front/back, crops, calls the model, writes review items |
| Model | Ollama or OpenAI-compatible endpoint | Reads card images and returns fields matching a fixed schema |
| FlipDial server | NAS, server or container | API, review queue, web app, CardDAV sync, search index |
| CardDAV server | Your existing contacts server | Source of truth for contact fields |
| Archive | Network share or volume | Original scans (never modified) and derived images |

The ingest worker and the server can run on the same machine or on different ones. They share only the inbox and archive folders and the server's internal API.

## Data flow

1. A scanner or phone writes images to `inbox/`.
2. The worker groups images into a card (front, optional back) and moves the originals to `archive/<card-id>/` as `front.orig.*` and `back.orig.*`.
3. The worker writes derived files next to them: straightened crops and thumbnails.
4. The worker sends the cropped images to the model with a fixed prompt and JSON schema. The response is validated; anything outside the schema is dropped.
5. A review item is created with fields, confidence, and a duplicate match if one is found.
6. On approval the server writes the vCard to CardDAV and records the vCard UID against the card folder.

## Contracts between parts

- **Folder contract:** capture tools only need to write files. Any scanner, OS or phone app works.
- **vCard contract:** the CardDAV server holds contact fields. FlipDial stores scan paths and its own metadata in `X-FLIPDIAL-*` properties and its local database.
- **Model contract:** a JSON schema in `backend/src/flipdial/extract/`. Swapping models must not change it.

## Local state

FlipDial's own database (SQLite) is a cache plus FlipDial-only metadata: review queue, audit log, duplicate decisions, search index. It can be rebuilt from CardDAV and the archive, except for the audit log and review history.
