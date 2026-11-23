# Threat model

Reviewed for v1 (milestones 0 to 8, November 2026). Review again whenever a milestone ships or a trust boundary changes.

## Assets

| Asset | Why it matters |
|---|---|
| Contact data | Personal data about third parties who never agreed to be in a database |
| Original scans | Same as above, plus they can include handwriting and photos |
| Relationship data (v2) | Reveals who knows whom; most sensitive data in the app |
| CardDAV and model credentials | Allow reading or changing all contacts |
| Audit log | Proof of what changed and when |
| Sessions and sign-in | Whoever holds a session can read and change every contact |
| Backups and exports | A full copy of everything above, outside FlipDial's control once downloaded |

## Trust boundaries

1. Capture devices to the inbox folder
2. Inbox to the ingest worker
3. Worker to the model endpoint
4. Model output to the review queue
5. Browser to the FlipDial server
6. FlipDial server to the CardDAV server
7. Browser to the identity provider, and the provider back to FlipDial (sign-in)
8. Reverse proxy to FlipDial (proxy sign-in mode)
9. Files the person imports, and backups they restore

## Threats and mitigations

| Threat | Mitigation |
|---|---|
| Card text crafted to manipulate the model (prompt injection) | Model gets no tools and no network access; fixed prompt; output must match a strict JSON schema; values are length-limited and validated; a human reviews before saving |
| Malicious image files (parser exploits, decompression bombs) | Allowlisted formats, size and pixel limits, decoding in the worker process only, maintained image libraries |
| Path traversal through file names | Server-generated card IDs; original file names never used as paths |
| Model output that injects into the web UI | Output treated as text everywhere; no HTML rendering of extracted values; strict Content Security Policy |
| Data leaving the network | No telemetry or CDN; cloud model endpoints off unless configured; CI runs the pipeline with no network |
| Stolen CardDAV credentials | Kept in `.env` outside the repo, held as secrets in memory and never logged; use an app password for FlipDial, not your main password |
| Unauthorized access to the web app | Sign-in by OpenID Connect or a trusted reverse proxy; FlipDial refuses to start without sign-in on any address but localhost unless told the port is local only; every data route under `/api` requires a signed-in user (see [sign-in](sign-in.md)) |
| Forged or replayed sign-in (stolen code, swapped tokens, login CSRF) | PKCE, one-time state bound to the starting browser by a cookie, nonce; ID token signature checked against the provider's keys; issuer, audience, expiry checked; unsigned and shared-secret tokens refused; only https providers outside the local network |
| Someone with a provider account who should not have access | Explicit allow-list; empty list allows nobody; emails count only when verified; removal takes effect on the next request |
| Stolen session cookie | HttpOnly, SameSite=Lax, Secure with the `__Host-` prefix over https; random 256-bit token stored only as a hash; idle and absolute expiry; sign-out deletes it server-side |
| Spoofed user header in proxy mode | Header trusted only from configured proxy addresses; FlipDial ignores forwarded-for headers so the peer address cannot be faked; keep FlipDial reachable only through the proxy |
| Open redirect after sign-in | The return address must be an in-app screen (`#/...`); anything else goes to the Wall |
| Cross-site requests from other pages in the same browser | Every write needs the `X-FlipDial-Request` header (which other sites cannot send without permission) and a matching `Origin`; session cookie is SameSite=Lax; strict Content Security Policy |
| Local database holds contact data (a copy of the address book, extraction results) | Keep the data folder on an encrypted volume; it is excluded from the repo; contacts can be re-synced from CardDAV |
| Merge history keeps full copies of both contacts for undo | Stored only in the local database, alongside the contacts copy; same protection as the data folder |
| Original scans downloaded through the web app | Served only from the card's own folder by fixed name; card IDs are validated; sent as downloads, never rendered inline |
| Malicious import files (huge files, odd encodings, crafted CSV or vCard) | 10 MB and 10,000-contact limits; strict parsing; values length-limited; a preview before anything is saved; every import can be undone |
| Spreadsheet formulas in exported CSV (CSV injection) | Cells starting with `=`, `+`, `-`, `@`, tab or carriage return are prefixed with `'` |
| Backup archive holds every contact and scan | Downloaded on request only, never cached (`no-store`); temporary files removed after sending; documented as sensitive |
| Tampered or hostile backup on restore (zip slip, zip bombs, swapped files) | Restore only into an empty folder; every file must be in the manifest with a safe path, matching size and SHA-256; sizes enforced while reading; nothing is put in place unless all checks pass |
| Over-broad file access by the worker | Deployment guidance: run as an unprivileged account that can write only the inbox, archive and data folders; the container runs as a non-root user with a read-only root filesystem and no added capabilities |
| Personal data in logs | Logs identify contacts by UID only; card text and model output never logged; a filter masks email addresses and phone numbers as a safety net; tests run with logging on so a logging mistake fails CI |
| Unwanted retention | "Forget this contact" removes the vCard, every linked scan and derived file, extraction results, merge history and import records, and records only the UID in the audit log. Backups already downloaded are not changed |
| Changes nobody can account for | Audit log of every change, import, export, backup and sign-in (including refused ones); append-only in the database; hash-chained so edits made with other tools are detected (`flipdial audit verify`) |
| Tampered audit log by someone with file access | Detected, not prevented: the chain breaks at the edited entry; removal from the end is caught by comparing the noted `head` fingerprint. Keep the data folder on a volume only FlipDial's account can write |
| Supply chain | Locked dependencies installed with hash checks in the image; GitHub Actions pinned to commit SHAs; Dependabot; weekly advisory scan of Python and npm packages; container image and release files signed with Sigstore (keyless), with SBOMs and build provenance attached |
| Private data committed to this repo | `.gitignore` for data paths, secret scanning in pre-commit and CI, CI check that blocks images and vCards outside `demo/` |

## Out of scope for v1

Multi-user permissions, hostile administrators, a compromised host OS.
