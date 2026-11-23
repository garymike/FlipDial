# Threat model

Draft for v1. Review at each milestone.

## Assets

| Asset | Why it matters |
|---|---|
| Contact data | Personal data about third parties who never agreed to be in a database |
| Original scans | Same as above, plus they can include handwriting and photos |
| Relationship data (v2) | Reveals who knows whom; most sensitive data in the app |
| CardDAV and model credentials | Allow reading or changing all contacts |
| Audit log | Proof of what changed and when |

## Trust boundaries

1. Capture devices to the inbox folder
2. Inbox to the ingest worker
3. Worker to the model endpoint
4. Model output to the review queue
5. Browser to the FlipDial server
6. FlipDial server to the CardDAV server

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Card text crafted to manipulate the model (prompt injection) | Model gets no tools and no network access; fixed prompt; output must match a strict JSON schema; values are length-limited and validated; a human reviews before saving |
| Malicious image files (parser exploits, decompression bombs) | Allowlisted formats, size and pixel limits, decoding in the worker process only, maintained image libraries |
| Path traversal through file names | Server-generated card IDs; original file names never used as paths |
| Model output that injects into the web UI | Output treated as text everywhere; no HTML rendering of extracted values; strict Content Security Policy |
| Data leaving the network | No telemetry or CDN; cloud model endpoints off unless configured; CI runs the pipeline with no network |
| Stolen CardDAV credentials | Stored as secrets, not in config files; separate read-only credentials for read-only components |
| Unauthorized access to the web app | Until sign-in ships (milestone 8): bind to localhost and reach it through a private network or a reverse proxy with sign-in. Then OIDC sign-in |
| Cross-site requests from other pages in the same browser | Every write needs the `X-FlipDial-Request` header and a matching `Origin`; strict Content Security Policy; no cookies are used yet |
| Local database holds contact data (a copy of the address book, extraction results) | Keep the data folder on an encrypted volume; it is excluded from the repo; contacts can be re-synced from CardDAV |
| Merge history keeps full copies of both contacts for undo | Stored only in the local database, alongside the contacts copy; same protection as the data folder |
| Original scans downloaded through the web app | Served only from the card's own folder by fixed name; card IDs are validated; sent as downloads, never rendered inline |
| Malicious import files (huge files, odd encodings, crafted CSV or vCard) | 10 MB and 10,000-contact limits; strict parsing; values length-limited; a preview before anything is saved; every import can be undone |
| Spreadsheet formulas in exported CSV (CSV injection) | Cells starting with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'` |
| Backup archive holds every contact and scan | Downloaded on request only, never cached (`no-store`); temporary files removed after sending; documented as sensitive |
| Tampered or hostile backup on restore (zip slip, zip bombs, swapped files) | Restore only into an empty folder; every file must be in the manifest with a safe path, matching size and SHA-256; sizes enforced while reading; nothing is put in place unless all checks pass |
| Over-broad file access by the worker | Worker account can only write the inbox and archive folders |
| Personal data in logs | Logs identify contacts by UID only; card text and model output never logged; debug mode expires |
| Unwanted retention | "Forget this contact" removes the vCard, scans, derived files, index entries and graph edges, and records the deletion in the audit log |
| Supply chain | Pinned dependencies, Dependabot, signed releases with SBOM, secret scanning |
| Private data committed to this repo | `.gitignore` for data paths, secret scanning in pre-commit and CI, CI check that blocks images and vCards outside `demo/` |

## Out of scope for v1

Multi-user permissions, hostile administrators, a compromised host OS.
