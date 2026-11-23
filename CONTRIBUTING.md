# Contributing

## The no-private-data rule

This repository is public. Nothing personal goes in it, ever:

- No real contacts, business cards, scans, vCards or exports
- No real names, email addresses, phone numbers or company names in tests, fixtures, screenshots or docs. Use the demo data and `.example` domains.
- No hostnames, IP addresses, usernames, folder paths or details of anyone's own setup
- No credentials, tokens or keys, even expired ones
- No logs from a real instance

If you need real cards to measure extraction accuracy, keep them in a folder outside the repo and point the test runner at it with `FLIPDIAL_PRIVATE_TESTSET`.

### Guardrails

- `.gitignore` excludes `data/`, `inbox/`, `archive/`, `.env` and local config files.
- [gitleaks](https://github.com/gitleaks/gitleaks) runs as a pre-commit hook and in CI.
- CI fails if an image or vCard file appears outside `demo/` or `web/public/`.

Install the hooks once:

```sh
pip install pre-commit
pre-commit install
```

## Development

### Backend

```sh
cd backend
uv sync --extra dev
uv run pytest
uv run ruff check .
```

### Web

```sh
cd web
npm install
npm run dev
```

## Pull requests

Keep changes focused, add tests, and update docs when behavior changes.
