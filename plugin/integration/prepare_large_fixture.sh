#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
SRC_DB="${CALIMOB_LARGE_SOURCE_METADATA_DB:-/Users/macbookpro/Library/CloudStorage/Dropbox/Calibre/metadata.db}"
DEST_DIR="${CALIMOB_LARGE_FIXTURE_DIR:-$ROOT_DIR/tests/plugin/fixtures/CalibreLargeLocal}"
DEST_DB="$DEST_DIR/metadata.db"

if [[ ! -f "$SRC_DB" ]]; then
  echo "ERROR: source metadata.db not found: $SRC_DB" >&2
  exit 1
fi

mkdir -p "$DEST_DIR"
cp -f "$SRC_DB" "$DEST_DB"

BOOKS_COUNT=$(sqlite3 "$DEST_DB" "select count(*) from books;" 2>/dev/null || echo "0")
LIB_UUID=$(sqlite3 "$DEST_DB" "select uuid from library_id limit 1;" 2>/dev/null || echo "")

echo "Fixture prepared:"
echo "  source: $SRC_DB"
echo "  target: $DEST_DB"
echo "  books:  $BOOKS_COUNT"
echo "  uuid:   $LIB_UUID"
echo
echo "Exports:"
echo "  export CALIMOB_TEST_LIBRARY_PATH=\"$DEST_DIR\""
echo "  export CALIMOB_LIBRARY_PATH=\"$DEST_DIR\""
echo "  export CALIBRE_LIBRARY_ID=\"$LIB_UUID\""
echo "  export CALIMOB_LIBRARY_ID=\"$LIB_UUID\""
