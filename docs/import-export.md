# Import, export and backup

Open **Import and export** from the Wall sidebar (on a phone, it's the last chip in the deck row). Everything here also works from the command line.

## Import

| File | Where it comes from | Notes |
|---|---|---|
| vCard (`.vcf`) | Apple Contacts, Google Contacts, Synology, most phones | vCard 3.0 and 4.0. Every field is kept, including ones FlipDial doesn't show (birthdays, notes, photos). vCard 2.1 from older phones is skipped: open it in another contacts app and export again |
| Google Contacts CSV | Google Contacts, Export, Google CSV | Labels become tags. Google's own labels (like "myContacts") are dropped |
| Outlook CSV | Outlook, Export contacts | Business and mobile phones both come in |
| LinkedIn connections | LinkedIn, Settings, Data privacy, Get a copy of your data, Connections | Upload `Connections.csv` from the download. The profile URL, company, position and "connected on" date come in. LinkedIn leaves out most email addresses |
| Any other CSV | A spreadsheet | FlipDial guesses which column is which. Change any column before importing |

How it works:

1. **Preview.** Choosing a file shows what was recognized, how many contacts are new, and which ones look like contacts you already have (same email, same phone, or same name). Nothing is saved yet.
2. **Columns.** For CSV files, each column has a menu. Pick "Ignore" to leave a column out. Several columns can feed the same field (for example, three email columns).
3. **Deck.** Optionally put every imported contact in a deck. LinkedIn imports suggest a "LinkedIn" deck.
4. **Duplicates.** Likely duplicates are skipped unless you tick the box. To combine them with existing contacts instead, import them and then use **Possible duplicates**.
5. **Undo.** Every import is listed under **Recent imports** and can be undone. Undo removes the contacts that import created, except any you have edited since.

Limits: 10 MB and 10,000 contacts per file. Imported files are treated as untrusted: values are length-limited and never run or rendered as HTML.

FlipDial reads LinkedIn's official data export only. It never signs in to LinkedIn or reads LinkedIn pages.

## Export

- **vCard (.vcf):** every contact exactly as stored on your contacts server, ready for any contacts app.
- **Spreadsheet (.csv):** one row per contact. Several emails or phones are joined with ` ; `. Cells that a spreadsheet could treat as a formula are prefixed with `'`. FlipDial can import this file again.

## Full backup

A backup is one zip file:

| File | Contents |
|---|---|
| `manifest.json` | App version, counts, and the size and SHA-256 fingerprint of every other file |
| `contacts.vcf` | Every contact |
| `flipdial.db` | FlipDial's history: review queue, extraction results, merges and imports |
| `archive/` | Every original scan, the crops, and each card's manifest |

The backup holds all your contacts and scans. Store it somewhere private and encrypted. Forgetting a contact later does not change backups you already have: delete or replace old backups if someone asks to be removed.

### Restore

```sh
FLIPDIAL_DATA_DIR=/path/to/empty/folder flipdial restore flipdial-backup-20261123.zip
```

Restore only writes into an empty data folder. Before anything is put in place it checks that every file is listed in the manifest, has the right size and fingerprint, and has a safe path. If any check fails, nothing is restored.

Contacts are not pushed to your contacts server automatically, since it usually still has them. If you are moving to a new, empty address book, import the restored file:

```sh
flipdial import /path/to/empty/folder/restored-contacts.vcf
```

## Command line

```sh
flipdial import FILE [--deck NAME] [--include-duplicates] [--dry-run]
flipdial export --out contacts.vcf    # or contacts.csv
flipdial backup --out flipdial-backup.zip
flipdial restore flipdial-backup.zip
```

`import`, `export` and `backup` refresh the local copy of your contacts first. Output is counts only.
