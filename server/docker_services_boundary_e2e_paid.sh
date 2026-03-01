#!/usr/bin/env bash
# Paid live E2E for Laravel <-> Docker boundary services.
# This script forces real indexing (fake=false) and requires explicit user confirmation.
#
# Usage:
#   CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
#   CALIMOB_E2E_TOKEN="<superadmin-or-user-token>" \
#   ./tests/server/docker_services_boundary_e2e_paid.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_URL="${CALIMOB_E2E_BASE_URL:-https://coral-shark-984693.hostingersite.com}"
TOKEN="${CALIMOB_E2E_TOKEN:-}"

if [[ -z "$TOKEN" ]]; then
  echo "ERROR: set CALIMOB_E2E_TOKEN"
  exit 2
fi

echo "⚠️  Paid E2E execution"
echo "This run will execute real indexing with fake=false for EPUB and PDF."
echo "It may consume paid resources (LLM/OCR/embedding depending on backend settings)."
read -r -p "Type YES to continue: " CONFIRM
if [[ "$CONFIRM" != "YES" ]]; then
  echo "Cancelled."
  exit 0
fi

echo "[PAID-E2E] Running EPUB real indexing flow"
CALIMOB_E2E_BASE_URL="$BASE_URL" \
CALIMOB_E2E_TOKEN="$TOKEN" \
CALIMOB_E2E_FAKE_INDEXING="false" \
CALIMOB_E2E_TEXT_FORMAT="EPUB" \
CALIMOB_E2E_REQUIRE_TEXT_FORMAT="true" \
CALIMOB_E2E_STRICT_INDEXING="true" \
"$SCRIPT_DIR/docker_services_boundary_e2e.sh"

echo "[PAID-E2E] Running PDF real indexing flow"
CALIMOB_E2E_BASE_URL="$BASE_URL" \
CALIMOB_E2E_TOKEN="$TOKEN" \
CALIMOB_E2E_FAKE_INDEXING="false" \
CALIMOB_E2E_TEXT_FORMAT="PDF" \
CALIMOB_E2E_REQUIRE_TEXT_FORMAT="true" \
CALIMOB_E2E_STRICT_INDEXING="true" \
"$SCRIPT_DIR/docker_services_boundary_e2e.sh"

echo "✓ Paid E2E completed (EPUB + PDF, fake=false)"
