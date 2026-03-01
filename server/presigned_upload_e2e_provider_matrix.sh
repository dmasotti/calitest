#!/usr/bin/env bash
# Run presigned upload live E2E across multiple real providers (default: r2,s3).
#
# Usage example:
#   CALIMOB_E2E_CONFIRM=YES \
#   CALIMOB_E2E_PROVIDER_MATRIX="r2,s3" \
#   CALIMOB_E2E_R2_BASE_URL="https://env-r2.example.test" \
#   CALIMOB_E2E_R2_TOKEN="<token>" \
#   CALIMOB_E2E_S3_BASE_URL="https://env-s3.example.test" \
#   CALIMOB_E2E_S3_TOKEN="<token>" \
#   ./tests/server/presigned_upload_e2e_provider_matrix.sh

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SINGLE_E2E="$ROOT_DIR/tests/server/presigned_upload_e2e.sh"
CONFIRM="${CALIMOB_E2E_CONFIRM:-NO}"
MATRIX="${CALIMOB_E2E_PROVIDER_MATRIX:-r2,s3}"

fail() { echo "✗ $1"; exit 1; }
log() { echo "[PRESIGNED-MATRIX] $1"; }
pass() { echo "✓ $1"; }

if [[ ! -x "$SINGLE_E2E" ]]; then
  fail "missing executable script: $SINGLE_E2E"
fi

if [[ "$CONFIRM" != "YES" ]]; then
  echo "This matrix test runs real uploads on all listed providers."
  echo "Set CALIMOB_E2E_CONFIRM=YES to proceed."
  exit 2
fi

IFS=',' read -r -a providers <<< "$MATRIX"
[[ ${#providers[@]} -gt 0 ]] || fail "empty provider matrix"

for raw in "${providers[@]}"; do
  provider="$(echo "$raw" | tr '[:upper:]' '[:lower:]' | xargs)"
  [[ -n "$provider" ]] || continue

  upper="$(echo "$provider" | tr '[:lower:]' '[:upper:]')"
  base_var="CALIMOB_E2E_${upper}_BASE_URL"
  token_var="CALIMOB_E2E_${upper}_TOKEN"
  lib_var="CALIMOB_E2E_${upper}_LIBRARY_ID"
  book_var="CALIMOB_E2E_${upper}_BOOK_UUID"
  format_var="CALIMOB_E2E_${upper}_FORMAT"
  content_type_var="CALIMOB_E2E_${upper}_CONTENT_TYPE"

  base_url="${!base_var:-}"
  token="${!token_var:-}"
  library_id="${!lib_var:-}"
  book_uuid="${!book_var:-}"
  format="${!format_var:-${CALIMOB_E2E_FORMAT:-EPUB}}"
  content_type="${!content_type_var:-${CALIMOB_E2E_CONTENT_TYPE:-application/octet-stream}}"

  [[ -n "$base_url" ]] || fail "missing $base_var"
  [[ -n "$token" ]] || fail "missing $token_var"

  log "running provider=$provider base_url=$base_url format=$format"

  CALIMOB_E2E_CONFIRM=YES \
  CALIMOB_E2E_BASE_URL="$base_url" \
  CALIMOB_E2E_TOKEN="$token" \
  CALIMOB_E2E_LIBRARY_ID="$library_id" \
  CALIMOB_E2E_BOOK_UUID="$book_uuid" \
  CALIMOB_E2E_FORMAT="$format" \
  CALIMOB_E2E_CONTENT_TYPE="$content_type" \
  CALIMOB_E2E_EXPECT_PROVIDER="$provider" \
  "$SINGLE_E2E"

  pass "provider=$provider passed"
done

echo "✓ Presigned provider matrix E2E passed for: $MATRIX"
