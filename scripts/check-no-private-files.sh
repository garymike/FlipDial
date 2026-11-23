#!/usr/bin/env bash
# Fail if card images, vCards, contact exports or env files are tracked outside allowed folders.
# Allowed: demo/ (invented data only) and web/public/ (app assets).
set -euo pipefail

pattern='\.(jpe?g|png|heic|heif|webp|tiff?|bmp|gif|pdf|vcf|vcard|csv)$|(^|/)\.env$'
allowed='^(demo/|web/public/)'

bad=$(git ls-files | grep -Ei "$pattern" | grep -Ev "$allowed" || true)

if [[ -n "$bad" ]]; then
  echo "These files look like personal data or secrets and are outside demo/ or web/public/:"
  echo "$bad"
  echo "Move invented demo data into demo/. Never commit real contacts, scans or .env files."
  exit 1
fi
echo "No personal data files found outside allowed folders."
