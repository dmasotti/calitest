#!/usr/bin/env bash
# tests/opds/opds_download_test.sh
# Simpler script focused on download endpoint validation
# Usage: HOST=http://caliweb.test USER=alice PASS=secret BOOK_ID=123 ./tests/opds/opds_download_test.sh

set -euo pipefail
HOST=${HOST:-http://127.0.0.1:8000}
USER=${USER:-}
PASS=${PASS:-}
APP_PASS=${APP_PASS:-}
BOOK_ID=${BOOK_ID:-}
TMPDIR=$(mktemp -d)

if [[ -z "$USER" || -z "$PASS" ]]; then
  echo "ERROR: set USER and PASS"
  exit 2
fi
if [[ -z "$BOOK_ID" ]]; then
  echo "ERROR: set BOOK_ID env var to the userBook id to download"
  exit 2
fi

CRED="$USER:$PASS"
if [[ -n "$APP_PASS" ]]; then
  CRED="$USER:$APP_PASS"
fi

URL="$HOST/books/$BOOK_ID/download"

echo "HEAD $URL"
curl -s -I -u "$CRED" -L "$URL" -o "$TMPDIR/headers.txt" -w "%{http_code}\n"
cat "$TMPDIR/headers.txt"

echo "Downloading (first 10KB) to show content-disposition and confirm body"
curl -s -u "$CRED" -L "$URL" -o "$TMPDIR/out.bin" --range 0-10239 -w "%{http_code}\n"
stat -c '%n %s bytes' "$TMPDIR/out.bin" 2>/dev/null || stat -f '%N %z bytes' "$TMPDIR/out.bin"

echo "Done"
exit 0
