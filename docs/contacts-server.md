# Bundled contacts server

FlipDial works without a contacts server: it keeps contacts in its data folder. To sync contacts to phones ([phone sync](sync.md)) you need one. If you don't have Synology Contacts, Nextcloud or similar, FlipDial can run [Radicale](https://radicale.org) for you, set up so that:

- It only answers over HTTPS, with a certificate made for this server only.
- FlipDial has its own account. Each phone gets its own account that can open only its own phone book, never your other contacts.
- Passwords are random, shown once, and stored only as bcrypt hashes.
- Contacts are plain `.vcf` files in the data folder.
- It is for your home network. Don't forward its port (5232) on your router.

## Turn it on (the easy way)

1. Open **Setup**. Under **Contacts server**, pick how your phone reaches this computer (FlipDial suggests its address on your network and its name), read **Good to know**, and choose **Turn on the built-in contacts server**.
2. **On Windows,** Windows Security asks whether to allow Python on networks. Python is what runs FlipDial. Your phone connects to this computer to sync, so Windows has to let that in. Choose **Private networks** and leave **Public networks** unticked, so nobody on café, hotel or airport Wi-Fi can reach it. If you choose Cancel, FlipDial still works on this computer but phones can't sync; change it later in Windows Security, Firewall & network protection, Allow an app through firewall.
3. **With Docker,** publish port 5232 for the FlipDial service (see `docker/compose.example.yml`).
4. Under **Phone**, choose **Set up phone sync**, then **Make the phone's account**, and add it to the phone as the wizard shows.

FlipDial then runs the server as a separate process alongside itself, starts it with FlipDial, restarts it if it stops, and stops it when FlipDial stops. It saves its own sign-in in a private file in the server's folder, so there's nothing to copy into the settings file. A contacts server set in the settings file always wins over the built-in one.

**Things to keep in mind**

- **The address can change.** If your router gives this computer a different address now and then, reserve it in the router (a DHCP reservation), or use the computer's name. Changing the address in FlipDial makes new certificates, so phones already set up need setting up again.
- **The certificate on your phone.** The phone is asked to trust the server's certificate authority once. It is limited by name constraints to this server's names, and its private key is deleted as soon as the certificate is made, so it can't vouch for any other website.
- **Others on your Wi-Fi** can reach the server but need a password to see anything. Don't run it on a network you don't trust, and never forward port 5232 on your router.
- **Backups:** the contacts are plain files in `contacts-server/` in FlipDial's data folder. FlipDial's backup includes every contact.
- **Setting up an iPhone** while FlipDial is opened as localhost: the one-time profile link is offered on your home network (port 5233) for up to 15 minutes, then closes. It holds no password. Install it right away, at home.
- **Windows file permissions:** the server's folder is limited to your account (and Windows' own SYSTEM and Administrators). If FlipDial's data folder is outside your user profile (for example C:\_dev\flipdial-data), other accounts on the computer may be able to read the rest of it; keep it in your profile or limit it the same way.
- **Turning it off** stops it and phones stop syncing. The contacts stay in its folder and come back when you turn it on again.

## Run it separately (for power users)

For running it as its own service, which you then keep up to date yourself:

1. Run the setup once, giving the name or address your phones use to reach this computer (repeat `--host` for more than one):

   ```sh
   flipdial contacts-server init --host nas.local --host 192.168.1.20
   ```

   It writes the settings to add to your settings file into `settings-to-add.env` in the server's folder (an owner-only file; with Docker, that's `data/contacts-server/` next to your compose file). Copy the lines into your settings file, then delete it: it holds FlipDial's password for the server, which isn't stored anywhere else.

2. Start it:
   - **Docker:** `docker compose run --rm flipdial flipdial contacts-server init --host ...` for step 1, then `docker compose --profile contacts-server up -d` (see `docker/compose.example.yml`).
   - **Windows scripts:** nothing to do. With `FLIPDIAL_RADICALE_DIR` in the settings file, `start` runs it alongside FlipDial and `stop` stops it.
   - **Anything else:** `flipdial contacts-server run`.

3. Restart FlipDial. It makes its own address book on first use.

To add a phone account by hand: `flipdial contacts-server add-user phone2`. Its password goes into `phone2-password.txt` in the same folder; delete the file once you've used it.

## What's in the folder

| File | Contents |
|---|---|
| `config` | Radicale's settings |
| `rights` | Access rules: FlipDial's account opens everything; every other account only its own address books |
| `users` | Account names and bcrypt password hashes (owner-only file) |
| `flipdial-password` | FlipDial's own password, for the built-in server (owner-only file) |
| `server.log` | The built-in server's log |
| `ca.pem` | The certificate authority made for this server only, limited to its names (its private key is not kept) |
| `server.pem`, `server.key` | The server's certificate and private key (owner-only) |
| `collections/` | The contacts |

The server certificate lasts 825 days, the most Apple accepts. To replace it, move the folder aside, run `init` again, and copy `collections/` back.

## How it's built

The Docker image (`docker/contacts-server/Dockerfile`) installs Radicale from PyPI at pinned versions with every file's hash checked (`requirements.txt`), runs as a non-root user with a read-only filesystem and no added privileges, and has no other software. Dependabot keeps the versions current.
