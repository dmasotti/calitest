#!/usr/bin/env bash
# tests/opds/opds_download_test.sh
# Simpler script focused on download endpoint validation
# Usage: HOST=http://caliweb.test USER=alice PASS=secret BOOK_ID=123 ./tests/opds/opds_download_test.sh

# Tip: puoi caricare `html/.env` prima di eseguire lo script per usare le credenziali/dev defaults:
#   set -a; source html/.env; set +a;

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PRE_APP_PASS="${APP_PASS:-}"
PRE_OPDS_PASS="${OPDS_PASS:-}"
PRE_USER="${USER:-}"
PRE_PASS="${PASS:-}"
if [[ -f "$SCRIPT_DIR/../server/.env" ]]; then
  set -a
  source "$SCRIPT_DIR/../server/.env"
  set +a
fi
if [[ -n "$PRE_APP_PASS" ]]; then
  APP_PASS="$PRE_APP_PASS"
  export APP_PASS
fi
if [[ -n "$PRE_OPDS_PASS" ]]; then
  OPDS_PASS="$PRE_OPDS_PASS"
  export OPDS_PASS
fi
if [[ -n "$PRE_USER" ]]; then
  USER="$PRE_USER"
fi
if [[ -n "$PRE_PASS" ]]; then
  PASS="$PRE_PASS"
fi

HOST=${HOST:-http://caliserver.test}
USER=${OPDS_USER:-${TEST_USER_EMAIL:-}}
PASS=${OPDS_PASS:-${TEST_USER_PASSWORD:-}}
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
