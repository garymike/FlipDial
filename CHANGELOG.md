# Changelog

## 0.16.0

### New

- **Update now shows its progress:** checking the release signature, installing and
  restarting, then opening the new version, each ticked off as it finishes, with the time
  so far.

## 0.15.1

### Fixes

- **Wall rows line up again:** a name on two lines pushed its card up. Cards now line up
  along the bottom of each row and names along the top.

## 0.15.0

### New

- **Choose when your phone syncs:** on its own (as before), or only when you press Sync
  now. In manual mode FlipDial can still check every week or every day (or never) whether
  the phone is behind, and says so in Setup and next to Review ("Phone is behind"), with a
  Check now button.

### Fixes

- **FlipDial remembers which address book it keeps your contacts in.** If that address
  book disappears, it says so in Setup instead of quietly using another one (which would
  look like every contact was gone). Setup can let it pick again when that's what you want.
- **Old phone sign-ins can be removed.** Setting a phone up again could leave earlier
  sign-ins on the built-in contacts server. Setup lists them under Contacts server, each
  with a Remove button.
- Stopping FlipDial on Windows could report a failure when one of its processes had
  already exited, which could also interrupt an update.

## 0.14.1

### Fixes

- **Update now works on Windows.** The app started the updater in a way that gives Windows
  PowerShell no console at all, and it quietly exits before doing anything, so the page
  waited forever. It now starts with a hidden console; a check on Windows in CI makes sure
  it really runs. The updater also writes `logs\update.log` from its very first step.
- If an update doesn't start, the page now says so (with where to look) instead of waiting.
- The check for whether this computer has its home network address no longer binds a
  network socket (flagged by code scanning); it asks the system which address it would use.

## 0.14.0

### New

- **Phone setup explains itself:** it starts by saying how phone sync works, asks whether
  it's an Android or an iPhone/iPad, and lets you name it. The name is what the address
  book is called on the phone, and the sign-in is named after it (`mikes-pixel`, not
  `phone2`). It says what the password is for and where you'll enter it, and you can make
  a new password any time. Renaming replaces the old sign-in and its address book.

- **Setup is compact:** each check is one line, with its details to the right in grey.
  Updates is one line too.

### Fixes

- **Turning on the built-in contacts server moves your contacts onto it.** Contacts saved
  on this computer before there was a server used to stay behind (with a button in Setup to
  copy them), so FlipDial looked empty. Now they're copied as the server starts.
- **FlipDial no longer empties itself** if the contacts server suddenly lacks most of its
  contacts (an emptied or different address book). It keeps them and asks in Setup.
- **Faster on Windows with the built-in contacts server:** FlipDial reached it as
  "localhost", and Windows tries the IPv6 address first and waits about two seconds before
  falling back, on every connection. It now connects over IPv4 directly. This was most of
  the delay after an edit.
- **Stars are instant** and quick clicks end on what you chose. Saving to the built-in
  contacts server took over a second, because every request checked the password from
  scratch; it now remembers a correct sign-in for a minute. A new phone password still
  works only from the moment it's made. The Starred count updates right away.
- The built-in contacts server keeps working for FlipDial when this computer isn't on the
  home network, or its address changed. Before, it stopped completely, so edits like
  starring a contact failed. Now it answers on this computer only until the home address
  is back.
- Whether this computer has the home address is now checked on every network connection,
  not just the main one, so computers with VPNs or virtual network adapters (WSL,
  Hyper-V, Docker) aren't wrongly treated as away from home.

## 0.13.0

### New

- **Setup is one click away:** a gear next to Review opens it. The search box is smaller
  and sits in the middle of the header.

### Fixes

- The built-in contacts server now stops with FlipDial every time, even if FlipDial
  crashes or is ended in Task Manager. Nothing is left running on its own.
- Changing the built-in contacts server's address now restarts it, so it uses the new
  certificate right away. Before, it kept the old one until FlipDial was restarted.

## 0.12.2

### Security

- **The built-in contacts server listens only at home:** on this computer and the home
  address you chose, not on every network. If you chose the address (not the name), it
  pauses on other networks, like café or hotel Wi-Fi, and Setup says so. It starts again
  when you're back home.
- The iPhone profile link listens only on the home address.

## 0.12.1

### New

- **Sync now in the app:** next to Review (in the More menu on a phone), with the time of
  the last phone sync beside it. When a sync is waiting for you, it links to Setup.
- **iPhone or iPad by hand:** the phone wizard can show how to add the account in
  Settings instead of installing a profile. Nothing extra is installed on the device; it
  asks once to accept the server's certificate, and the wizard says what to check.
- The wizard shows when a profile link was opened, so you can tell if anything other than
  your device opened it.

### Improved

- FlipDial looks for phone changes every 5 minutes, slowing to 7 or 10 for large address
  books, instead of every minute. Contacts rarely change that often, and Sync now is
  there when you're making a lot of updates.
- A test list for phone sync on real devices, with security checks, in the release
  checklist.

## 0.12.0

### New

- **Phone sync.** Your phone gets its own address book with only the contacts you choose,
  so it stays short while FlipDial keeps every card. Everything is off by default: switch
  on a deck, a tag, Starred, every contact, or one contact from its card (its own choice
  wins). It works both ways on your home network:
  - Changes in FlipDial reach the phone within a minute.
  - Edits made on the phone come back into FlipDial field by field. A field changed in
    both places waits in Review with both versions side by side.
  - Contacts added on the phone wait in Review until you save them to FlipDial or leave
    them on the phone only.
  - Deleting a contact on the phone only takes it off the phone. Nothing is ever deleted
    from FlipDial because of the phone, and every change from the phone can be undone
    from Activity for 30 days.
  - Sync stops and asks when an address book suddenly shrinks, and the first sync and any
    large change wait for you to confirm. A backup is taken before big changes.
  Nothing is connected to your Google or Apple account. See docs/sync.md.
- **Phone setup wizard** (Setup > Phone): choose or make the phone address book, give the
  phone its own account (with a check that it can't see your other contacts), then add it
  to the phone: a QR code and one-tap profile on iPhone, or DAVx5 steps on Android.
- **Built-in contacts server.** No Synology or Nextcloud? Setup > Contacts server turns on
  one that FlipDial runs alongside itself, with one button. It uses HTTPS with a
  certificate made for this server only, gives each phone an account that sees only its
  own contacts, and is meant for your home network only. The setup explains each choice
  first, including the Windows firewall question. Power users can still run it
  separately with `flipdial contacts-server`. See docs/contacts-server.md.
- **Import updates contacts you already have.** Importing a Google Contacts export (or any
  file) adds new phones, emails and details to matching contacts and fills in empty
  fields, without removing anything. FlipDial's value is kept when both differ, unless you
  choose the file's. Undo puts updated contacts back as they were.
- **Changes for Google Contacts** (Import / export): a vCard of only the contacts changed
  since your last download, ready to import at contacts.google.com.

### Improved

- The settings file still decides the contacts server when it names one; everything new
  here can also be set there (FLIPDIAL_PHONE_ADDRESSBOOK, FLIPDIAL_PHONE_CHECK_HOUR,
  FLIPDIAL_PHONE_SERVER_URL, FLIPDIAL_RADICALE_DIR).
- A contacts server with its own certificate is now checked with the current method
  (no deprecation warning).

### Security

- Without sign-in, FlipDial now answers only to IP addresses, localhost and this
  computer's own name. Before, another website could point a name it controls at this
  computer and read your contacts through the browser (DNS rebinding). If you open
  FlipDial by another name, add it to FLIPDIAL_ALLOWED_HOSTS.
- The contacts server's folder is limited to your account on Windows (where file modes
  aren't enforced). If FlipDial's data folder sits outside your user profile, other
  accounts on the computer may be able to read the rest of it; keep it in your profile
  or limit it the same way.

### Upgrading

The database is updated automatically on start. Radicale is now installed with FlipDial
(for the built-in contacts server); nothing else changes unless you turn it on. With
Docker, publish port 5232 only if you use the built-in contacts server for phones.

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
