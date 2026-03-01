#!/usr/bin/env bash
# Wrapper that asks explicit confirmation before running live presigned E2E.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${CALIMOB_E2E_BASE_URL:-https://coral-shark-984693.hostingersite.com}"
TOKEN="${CALIMOB_E2E_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: set CALIMOB_E2E_TOKEN"
  exit 2
fi

echo "⚠️  Live presigned E2E"
echo "This run will upload bytes to object storage and write DB state via /api/sync/uploads/* endpoints."
read -r -p "Type YES to continue: " CONFIRM
if [[ "$CONFIRM" != "YES" ]]; then
  echo "Cancelled."
  exit 0
fi

CALIMOB_E2E_BASE_URL="$BASE_URL" \
CALIMOB_E2E_TOKEN="$TOKEN" \
CALIMOB_E2E_CONFIRM="YES" \
"$SCRIPT_DIR/presigned_upload_e2e.sh"
