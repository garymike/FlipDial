# Release checklist (v1 go-live)

v1 ships when every box below is checked. Copy this list into the release issue and tick items there.

## Version numbers

Versions are `MAJOR.MINOR.PATCH`, tagged `v` plus the version (`v0.13.0`). The release title is the tag.

- **Before 1.0:** raise the middle number for any release with something new (`0.13.0`), and the last number for releases with fixes only (`0.13.1`).
- **1.0.0** is the public launch: from then on, stored data and setup stay compatible within a major version.
- **Test builds** add `-rc1`, `-a1` or `-b1` (`1.0.0-rc1`) and publish as pre-releases.
- Every version is released. A run that fails creates no tag, so the same version can simply be run again.

## How a release is made

1. Work through this list in a release issue.
2. Set the version in `backend/pyproject.toml` (and `web/package.json`) and merge to main. Then go to **Actions → Release → Run workflow** and type the version, for example `1.0.0` (or push a tag `v1.0.0` yourself). The workflow checks the version matches the code, reruns every CI check, creates the tag once they pass, builds the container image, signs it with Sigstore (keyless, tied to this repository's workflow), attaches an SBOM and build provenance, builds the Python package and web app, and signs their checksums.
3. The workflow leaves a **draft** release. Add the accuracy report, recommended model and known limitations, then publish.

## 1. Accuracy gate

Run `flipdial eval` against the private test set (kept outside the repository) with the model and settings the release recommends.

**Test set requirements**

- [ ] At least 30 cards
- [ ] At least 10 stylized or artistic cards (unusual fonts, low contrast, busy backgrounds)
- [ ] At least 5 cards with information on the back
- [ ] At least 5 tall or square cards
- [ ] Both scanner and phone-photo captures

**Targets** (starting points; adjust after the first full run and record the reason)

| Field | Minimum accuracy |
|---|---|
| Full name | 95% |
| Email | 97% |
| Phone | 95% |
| Company | 90% |
| Website | 90% |
| Title | 85% |

- [ ] Every field meets its target
- [ ] Extra values (values the reader produced that are not on the card) total under 2% of expected values
- [ ] No reader errors on the test set
- [ ] Every card with a wrong value carried at least one review flag, or the miss is listed in the release notes as a known limitation
- [ ] The eval report (counts only) is attached to the release notes, with the model name and FlipDial version

## 2. Security and privacy

- [ ] Threat model reviewed and updated for every milestone shipped
- [ ] gitleaks and the private-file check pass on the full history, not only the latest commit
- [ ] No personal data anywhere in the repository, issues, screenshots or demo
- [ ] Dependencies current; no open high or critical advisories
- [ ] Release images signed, with an SBOM attached (check with the `cosign verify` command in the release notes)
- [ ] Default config binds to localhost, refuses to run without sign-in elsewhere, and blocks remote model endpoints
- [ ] Sign-in tested against the identity provider the release recommends
- [ ] `flipdial audit verify` passes on a long-running install

## 3. Functionality

- [ ] Milestones 1 to 8 done
- [ ] CardDAV round-trip tests pass against Synology Contacts, Nextcloud and Radicale
- [ ] Full export and restore tested on a copy of real data
- [ ] Fresh install from the docs works on a clean machine, start to first card

## Phone sync on real devices

Run once per release that changes phone sync, and whenever iOS, Android, DAVx5 or Synology has a major update. Use invented test contacts where you can.

**Before you start**
- [ ] FlipDial on the new version; Setup check all green (except Ollama, if not needed).
- [ ] Contacts server: the built-in one (Setup > Contacts server) or your own, reachable from the phones on home Wi-Fi.
- [ ] Windows: when asked about Python on networks, **Private networks** only. Afterwards, Windows Security > Firewall > Allow an app: Python is ticked for Private, not Public.
- [ ] Make a FlipDial backup (Import / export > Full backup).

**Setup**
- [ ] Setup > Phone > Set up phone sync: phone book made (or chosen), phone account made.
- [ ] Check the account (own server): it opens the phone book and **can't** see the main address book.
- [ ] Switch on one test deck with 3 to 5 contacts. Sync now: the first sync lists them and waits for confirmation.

**Android (DAVx5)**
- [ ] DAVx5: Login with URL and user name, using the wizard's address and user name. It asks to accept the certificate: check it names your server, accept.
- [ ] Only the phone book appears; turn it on. Limit sync to home Wi-Fi in the account settings.
- [ ] The test contacts appear in the phone's Contacts app, under the DAVx5 account, not in Google.

**iPad or iPhone, by hand**
- [ ] Settings > Apps > Contacts > Contacts Accounts > Add Account > Other > Add CardDAV Account, with the wizard's server and user name.
- [ ] If it can't verify the server: Details shows your server's name (and "FlipDial contacts server CA" for the built-in one). Accept. Note what iOS showed.
- [ ] The test contacts appear in Contacts under that account.

**iPad or iPhone, quick profile** (on a second device, or after removing the account above)
- [ ] Make the iPhone link; scan the code; the wizard shows "Opened at …".
- [ ] Settings > Profile Downloaded > Install. It shows one CardDAV account and (built-in server) one certificate. It asks for the password.
- [ ] Note whether Settings > General > About > Certificate Trust Settings needed turning on.
- [ ] The test contacts appear. The same link opened again shows it has expired.

**Two-way sync, on each device**
- [ ] Edit a test contact in FlipDial (title). Sync now; it changes on the device after the device syncs.
- [ ] Add a phone number on the device. Sync now in FlipDial: it appears in FlipDial; Activity shows it with Undo; Undo works.
- [ ] Change the same field on both sides: it waits in Review > From your phone with both versions. Try both choices.
- [ ] Add a new contact on the device: it waits in Review. Save it to FlipDial.
- [ ] Delete a contact on the device: in FlipDial it is still there, switched off for the phone, and isn't added back.
- [ ] Switch a contact off in FlipDial: it leaves the device and stays in FlipDial.
- [ ] Delete 12 or more test contacts on the device at once: sync stops and asks (sudden drop). Choose "I removed them on purpose".

**Security checks**
- [ ] From another device on the Wi-Fi, open `https://<server>:5232/` with the phone account: it can't open the main address book.
- [ ] Wrong password is refused, and the server log doesn't contain passwords.
- [ ] Without sign-in, FlipDial opened by an unknown name (for example a hosts-file entry pointing a made-up name at the computer) answers "unknown_host".
- [ ] Port 5232 isn't forwarded on the router (router settings, or a port check from outside your network).
- [ ] On a public network (or with the Windows network set to Public), the phone can't reach the server.
- [ ] Turn the built-in server off and on: contacts and accounts come back.

## 4. Docs and demo

- [ ] README, setup guides and screenshots match the release
- [ ] Live demo on GitHub Pages uses demo data only
- [ ] Known limitations listed in the release notes
