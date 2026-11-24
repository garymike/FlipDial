# Changelog

## 0.11.0

### New

- **Phones and tablets.** On a phone, a bottom bar switches between Dial, Wall and Review,
  with everything else under More. The Dial shows the current contact with call, email and
  Details buttons, the Wall shows two cards per row, and a contact opens full screen. On an
  iPad or other touch tablet, a contact slides in from the right. Computers look the same
  as before.
- **Vertical cards.** Rotate a card that was scanned sideways, and swap front and back when
  they were scanned the wrong way round. The card is shown upright everywhere; the scanned
  files are never changed. Vertical cards are shown larger in the Dial and on the Wall.
- **Trash.** The trash icon in a contact moves it to Trash after you confirm. It can be
  restored with everything it had for 30 days, then it is deleted for good.
- **More contact fields:** middle name, prefix (Dr.), suffix (PhD), nickname, department
  and birthday, stored the way Apple and Google Contacts store them. Scans read the prefix,
  middle name, suffix and department. CSV import and export include them, and search
  matches nickname and department.
- **A back that is a different card** (usually because the scanner skipped a blank back)
  is flagged in Review, with a button to split it into two cards.
- **Check for updates now** on the Setup page.

### Improved

- Cards of any shape fill their frame without dark bars around them.
- The reading pane shows where the contact is saved and whether it is in your latest
  backup, hides empty fields, and has Star, Edit and Trash in the top-right corner.
- Downloads of the original scan are on one line.
- The "Up next" list is gone from the reading pane.
- After "nothing newer", FlipDial checks for updates again within the hour instead of the
  next day.

### Fixed

- Saving an edit dropped a middle name, prefix or suffix set in another app.
- On a phone, the Wall could be wider than the screen.

### Upgrading

The database is updated automatically on start.

## 0.10.0

### New

- **Reading pane.** One click on a card in the Wall opens it on the right: the large card
  (click to flip), details, About and notes, with Star and Edit at the top. Editing happens
  in the pane. Arrow keys move between cards, Escape closes it, and the open contact is in
  the address bar, so back, bookmarks and links work. On a phone it opens full screen.
- **Dial is the default view,** with the same reading pane taking about a third of the
  width. FlipDial reopens whichever of Dial or Wall you used last. A search that matches
  several cards links to all of them on the Wall.
- **Read again** for saved contacts: rereads the card with the current model and lists only
  the fields that changed. Each change can be accepted or kept; nothing is saved until you
  apply.
- **Typed fields that work with Apple and Google Contacts:** phones (mobile, work, home,
  main, fax, pager), emails, websites and addresses each have a type, or a custom label.
  Addresses are split into street, city, state, ZIP and country. Values other apps set are
  kept exactly when you edit.
- **Several cards per person.** A contact keeps every card they have given you. Merging two
  scanned contacts asks which card to show.
- **Review:** Previous and Next buttons (and arrow keys) to move between cards, with edits
  kept per card.

### Improved

- Scanned images hide the thin white line scanners leave at the edges (display only; the
  files are never changed).
- A card with no back shows its details on a back in the front's main color.
- With animations turned off in Windows, cards fade instead of jumping.
- Dial search matches any word of a name or company, then title, email, event and About,
  and says when nothing matches.
- Plain-language messages for errors that used to show a code.
- CSV import reads phone and email types from Google and Outlook exports, and no longer
  skips fax and pager columns.

### Fixed

- Two lines of an address could run together ("Ajo WayTucson").
- Switching filters quickly could show an older list.
- The A to Z column in Dial moved with each contact.
- Opening a single contact could leave out the back of its card.

### Upgrading

The database is updated automatically on start. Contacts saved by 0.9 keep working; their
websites read as Work.

## 0.9.0-rc1

Practice release to test signing, the SBOM and the release workflow.
