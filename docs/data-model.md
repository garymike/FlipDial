# Data model

Contacts are vCards stored on a CardDAV server. FlipDial reads and writes vCard 4.0 where the server supports it and falls back to 3.0.

## Standard properties used

| Property | Use |
|---|---|
| `UID` | Stable contact ID; links the contact to its scan folder |
| `FN`, `N` | Name |
| `ORG`, `TITLE` | Company and role |
| `EMAIL`, `TEL`, `URL`, `ADR` | Contact details |
| `SOCIALPROFILE`, `IMPP` | Social handles (`URL` as a fallback) |
| `NOTE` | Free-text notes |
| `CATEGORIES` | Tags, event decks, and `Starred` |
| `PHOTO` | A small thumbnail or a URL to one. Full scans are never embedded. |
| `RELATED` | Relationships between contacts (v2) |

## FlipDial extensions

Extensions use the `X-FLIPDIAL-` prefix so other clients keep them intact.

| Property | Meaning |
|---|---|
| `X-FLIPDIAL-SCAN` | `yes` or `no` |
| `X-FLIPDIAL-SCAN-DATE` | When the card was scanned |
| `X-FLIPDIAL-EVENT` | Event deck name |
| `X-FLIPDIAL-MET-ON` | Date met |
| `X-FLIPDIAL-MET-AT` | Where met (place text) |
| `X-FLIPDIAL-INTRODUCED-BY` | UID of the contact who introduced you |
| `X-FLIPDIAL-SOURCE` | `scan`, `google`, `linkedin`, `manual`, `import` |
| `X-FLIPDIAL-STARRED` | `yes` when starred (mirrors `CATEGORIES:Starred`) |
| `X-FLIPDIAL-FOLLOW-UP` | Next follow-up date |
| `X-FLIPDIAL-MERGED-FROM` | UIDs merged into this contact |
| `X-FLIPDIAL-SCHEMA` | Extension schema version |

Per-field provenance (which source set each value, and when) and extraction confidence are kept in FlipDial's local database, not in the vCard.

## Archive layout

```
archive/<card-id>/
  front.orig.<ext>    original, never modified
  back.orig.<ext>     original, never modified
  front.crop.jpg      derived
  back.crop.jpg       derived
  thumb.jpg           derived
  manifest.json       card-id, vCard UID, hashes of originals, timestamps
```

## Schema changes

The extension schema is versioned. Migrations run on startup and are logged; they never delete original scans.
