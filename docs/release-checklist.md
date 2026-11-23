# Release checklist (v1 go-live)

v1 ships when every box below is checked. Copy this list into the release issue and tick items there.

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
- [ ] Release images signed, with an SBOM attached
- [ ] Default config binds to localhost and blocks remote model endpoints

## 3. Functionality

- [ ] Milestones 1 to 7 done
- [ ] CardDAV round-trip tests pass against Synology Contacts, Nextcloud and Radicale
- [ ] Full export and restore tested on a copy of real data
- [ ] Fresh install from the docs works on a clean machine, start to first card

## 4. Docs and demo

- [ ] README, setup guides and screenshots match the release
- [ ] Live demo on GitHub Pages uses demo data only
- [ ] Known limitations listed in the release notes
