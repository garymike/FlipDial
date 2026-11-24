# Running FlipDial on Windows

Three double-click scripts in `scripts\windows` handle day-to-day use:

| Script | What it does |
|---|---|
| `start.cmd` | Starts the web app and the scan worker in the background, waits until FlipDial answers, and opens it in your browser |
| `stop.cmd` | Stops both |
| `update.cmd` | Stops FlipDial, gets the latest version, refreshes the Python and web parts, and starts it again |

If something goes wrong, the window stays open with the reason. Logs are saved in your data folder under `logs\` (`server.log`, `worker.log`, plus `.errors.log` files). The previous run's logs are kept as `.previous`.

Tip: right-click `start.cmd`, choose **Send to > Desktop (create shortcut)**, and rename the shortcut "FlipDial".

## One-time setup

1. Install the tools (then open a new PowerShell window):

   ```
   winget install --id Git.Git -e
   winget install --id astral-sh.uv -e
   winget install OpenJS.NodeJS
   ```

   For reading cards you also need [Ollama](https://ollama.com) with a vision model: `ollama pull llama3.2-vision`.

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

## When cards aren't being read

Open **Setup check** (Wall sidebar, or the link in the red bar FlipDial shows when something is wrong). It checks Ollama, the card-reading model, whether that model can read images, the scan worker, the inbox and your contacts server, and says what to do for anything that isn't right. If the model you've set isn't installed, it lists the installed models that can read images.

After fixing the problem, use **Read again** on the Review page for cards that failed.

## Notes

- FlipDial listens only on this computer (`http://127.0.0.1:8080`) unless you set up [sign-in](sign-in.md).
- `stop.cmd` only stops processes `start.cmd` started. A leftover process ID that now belongs to another program is never touched.
- `update.cmd` refuses to run if files in the FlipDial folder were edited by hand, so it never overwrites your changes.
