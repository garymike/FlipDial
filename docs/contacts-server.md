# Bundled contacts server

FlipDial works without a contacts server: it keeps contacts in its data folder. To sync contacts to phones ([phone sync](sync.md)) you need one. If you don't have Synology Contacts, Nextcloud or similar, FlipDial can run [Radicale](https://radicale.org) for you, set up so that:

- It only answers over HTTPS, with a certificate made for this server only.
- FlipDial has its own account. Each phone gets its own account that can open only its own phone book, never your other contacts.
- Passwords are random, shown once, and stored only as bcrypt hashes.
- Contacts are plain `.vcf` files in the data folder.
- It is for your home network. Don't forward its port (5232) on your router.

## Set it up

1. Run the setup once, giving the name or address your phones use to reach this computer (repeat `--host` for more than one):

   ```sh
   flipdial contacts-server init --host nas.local --host 192.168.1.20
   ```

   It prints the settings to add to your settings file, including FlipDial's password. That's the only time the password is shown.

2. Start it:
   - **Docker:** `docker compose run --rm flipdial flipdial contacts-server init --host ...` for step 1, then `docker compose --profile contacts-server up -d` (see `docker/compose.example.yml`).
   - **Windows scripts:** nothing to do. With `FLIPDIAL_RADICALE_DIR` in the settings file, `start` runs it alongside FlipDial and `stop` stops it.
   - **Anything else:** `flipdial contacts-server run` (install the `contacts-server` extra first: `uv sync --extra contacts-server`).

3. Restart FlipDial. It makes its own address book on first use.

4. In **Setup > Phone > Set up phone sync**, choose **Make the phone's account**. FlipDial creates the account and its phone book, and shows the password once. Then add it to the phone as the wizard shows (one-tap profile on iPhone, DAVx5 on Android). The phone profile includes the server's certificate so the iPhone can trust it; on Android, DAVx5 asks you to accept it once.

To add a phone account by hand instead: `flipdial contacts-server add-user phone2`.

## What's in the folder

| File | Contents |
|---|---|
| `config` | Radicale's settings |
| `rights` | Access rules: FlipDial's account opens everything; every other account only its own address books |
| `users` | Account names and bcrypt password hashes (owner-only file) |
| `ca.pem` | The certificate authority made for this server only (its private key is not kept) |
| `server.pem`, `server.key` | The server's certificate and private key (owner-only) |
| `collections/` | The contacts |

The server certificate lasts 825 days, the most Apple accepts. To replace it, move the folder aside, run `init` again, and copy `collections/` back.

## How it's built

The Docker image (`docker/contacts-server/Dockerfile`) installs Radicale from PyPI at pinned versions with every file's hash checked (`requirements.txt`), runs as a non-root user with a read-only filesystem and no added privileges, and has no other software. Dependabot keeps the versions current.
