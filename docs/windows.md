# Running FlipDial on Windows

Three double-click scripts in `scripts\windows` handle day-to-day use:

| Script | What it does |
|---|---|
| `start.cmd` | Starts the web app and the scan worker in the background, waits until FlipDial answers, and opens it in your browser |
| `stop.cmd` | Stops both |
| `update.cmd` | Installs the newest published release (checking its signature first), and starts FlipDial again. If the new version doesn't start, the previous one is put back |

If something goes wrong, the window stays open with the reason. Logs are saved in your data folder under `logs\` (`server.log`, `worker.log`, plus `.errors.log` files). The previous run's logs are kept as `.previous`.

Tip: right-click `start.cmd`, choose **Send to > Desktop (create shortcut)**, and rename the shortcut "FlipDial".

## One-time setup

1. Install the tools (then open a new PowerShell window):

   ```
   winget install --id Git.Git -e
   winget install --id astral-sh.uv -e
   winget install OpenJS.NodeJS
   ```

   For reading cards you also need [Ollama](https://ollama.com) with a vision model: `ollama pull qwen3.5:9b` (or any model whose `ollama show` lists **vision**; the Setup check confirms it). Newer Ollama versions can no longer run `llama3.2-vision`.

2. Get FlipDial, for example into `C:\_dev`:

   ```
   git clone https://github.com/garymike/FlipDial.git C:\_dev\FlipDial
   ```

3. Create `backend\.env` with at least:

   ```
   FLIPDIAL_DATA_DIR=C:\_dev\flipdial-data
   FLIPDIAL_WEB_DIR=C:\_dev\FlipDial\web\dist
   FLIPDIAL_INGEST_MODE=duplex
   ```

   Keep the data folder outside the FlipDial folder: it holds your contacts and scans. `.env` is never committed. [config/flipdial.example.env](../config/flipdial.example.env) lists every setting, including your contacts server.

4. Double-click `scripts\windows\update.cmd`. The first run installs everything and builds the web app, then starts FlipDial.

## Scanning

Point your scanner's FlipDial profile at the inbox: `<data folder>\inbox` (for example `C:\_dev\flipdial-data\inbox`). Scans are picked up within a few seconds and appear under **Review** once read. See [ingest](ingest.md) for scanner settings.

## Updates

When a new release is published, a banner at the top of FlipDial says so, with a link to what's new and an **Update now** button. The button does the same as `update.cmd`:

1. Downloads the release's signature and checks, with Sigstore, that it was built by this repository's Release workflow from the exact commit being installed. If it doesn't match, nothing changes.
2. Stops FlipDial, installs the release, and starts it again. The page shows progress and reloads when it's back.
3. If the new version doesn't start, puts the previous version back.

Details of each update are in `logs\update.log`. **Later** hides the banner until the next release. FlipDial checks GitHub for a newer version at most once a day, and the request carries nothing about you or your contacts. To turn the check off, set `FLIPDIAL_UPDATE_CHECK=false`.

Until the first release is published, `update.cmd` installs the latest code instead. `scripts\windows\update.ps1 -Main` always does.

## When cards aren't being read

**No contacts server?** In Setup, **Contacts server**, one button turns on FlipDial's built-in one so phones can sync. The first time, Windows Security asks whether to allow Python on networks: choose **Private networks** only (details in [Bundled contacts server](contacts-server.md)).

Open **Setup check** (Wall sidebar, or the link in the red bar FlipDial shows when something is wrong). It checks Ollama, the card-reading model, whether that model can read images, the scan worker, the inbox and your contacts server, and says what to do for anything that isn't right. If the model you've set isn't installed, it lists the installed models that can read images.

After fixing the problem, use **Read again** on the Review page for cards that failed.

## Notes

- FlipDial listens only on this computer (`http://127.0.0.1:8080`) unless you set up [sign-in](sign-in.md).
- `stop.cmd` only stops processes `start.cmd` started. A leftover process ID that now belongs to another program is never touched.
- `update.cmd` refuses to run if files in the FlipDial folder were edited by hand, so it never overwrites your changes.
