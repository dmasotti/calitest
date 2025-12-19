#!/usr/bin/env bash
# tests/opds/opds_full_test.sh
# Usage:
#   HOST=http://caliweb.test USER=alice PASS=secret ./tests/opds/opds_full_test.sh
# Optionally set APP_PASS to test app-password instead of user password.
# This script exercises OPDS root, acquisition feed and downloads the first available entry.

set -euo pipefail
HOST=${HOST:-http://127.0.0.1:8000}
USER=${USER:-}
PASS=${PASS:-}
APP_PASS=${APP_PASS:-}
PER_PAGE=${PER_PAGE:-10}
TMPDIR=$(mktemp -d)
ROOT_XML="$TMPDIR/root.xml"
ALL_XML="$TMPDIR/all.xml"
HTTP_STATUS_FILE="$TMPDIR/status.txt"

if [[ -z "$USER" || -z "$PASS" ]]; then
  echo "ERROR: please set USER and PASS environment variables (e.g. USER=alice PASS=secret)"
  exit 2
fi

CRED="$USER:$PASS"
if [[ -n "$APP_PASS" ]]; then
  echo "Note: testing with app-password provided in APP_PASS env var"
  CRED="$USER:$APP_PASS"
fi

echo "[INFO] Host: $HOST"
echo "[INFO] Using Basic auth: $USER:****"

echo "[STEP 1] GET /opds (root navigation feed)"
curl -s -u "$CRED" -H "Accept: application/atom+xml;profile=opds-catalog;kind=navigation" -D "$TMPDIR/root.headers" "$HOST/opds" -o "$ROOT_XML" -w "%{http_code}\n" > "$HTTP_STATUS_FILE"
HTTP_CODE=$(cat "$HTTP_STATUS_FILE" | tr -d '\r\n')
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "FAIL: /opds returned HTTP $HTTP_CODE"
  echo "Headers:" && cat "$TMPDIR/root.headers"
  echo "Body:" && sed -n '1,200p' "$ROOT_XML"
  exit 3
fi

echo "OK: /opds returned 200"
ENTRY_COUNT=$(grep -c "<entry" "$ROOT_XML" || true)
echo "Entries in root feed: $ENTRY_COUNT"

# Fetch acquisition feed (/opds/all)
echo "[STEP 2] GET /opds/all (acquisition feed)"
curl -s -u "$CRED" -H "Accept: application/atom+xml;profile=opds-catalog;kind=acquisition" -G --data-urlencode "per_page=$PER_PAGE" --data-urlencode "page=1" -D "$TMPDIR/all.headers" "$HOST/opds/all" -o "$ALL_XML" -w "%{http_code}\n" > "$HTTP_STATUS_FILE"
HTTP_CODE=$(cat "$HTTP_STATUS_FILE" | tr -d '\r\n')
if [[ "$HTTP_CODE" != "200" ]]; then
  echo "FAIL: /opds/all returned HTTP $HTTP_CODE"
  echo "Headers:" && cat "$TMPDIR/all.headers"
  echo "Body:" && sed -n '1,200p' "$ALL_XML"
  exit 4
fi

echo "OK: /opds/all returned 200"
ALL_ENTRY_COUNT=$(grep -c "<entry" "$ALL_XML" || true)
echo "Entries in acquisition feed: $ALL_ENTRY_COUNT"
if [[ "$ALL_ENTRY_COUNT" -eq 0 ]]; then
  echo "NOTE: feed has zero results (valid OPDS feed is expected). Exiting successfully."
  exit 0
fi

# Try to extract first acquisition open-access link href
DOWNLOAD_URL=""
# Prefer explicit acquisition open-access link
DOWNLOAD_URL=$(xmllint --xpath "string(//entry[1]//link[@rel='http://opds-spec.org/acquisition/open-access']/@href)" "$ALL_XML" 2>/dev/null || true)
if [[ -z "$DOWNLOAD_URL" ]]; then
  # fallback: look for any link with rel contains acquisition
  DOWNLOAD_URL=$(xmllint --xpath "string(//entry[1]//link[contains(@rel,'acquisition')]/@href)" "$ALL_XML" 2>/dev/null || true)
fi

# If we could not obtain a href try to get <id> or an identifier and construct download endpoint
if [[ -z "$DOWNLOAD_URL" ]]; then
  ENTRY_ID=$(xmllint --xpath "string(//entry[1]/id)" "$ALL_XML" 2>/dev/null || true)
  if [[ -n "$ENTRY_ID" ]]; then
    # try to guess numeric id in the id content
    NUM=$(echo "$ENTRY_ID" | grep -oE '[0-9]+' | head -n1 || true)
    if [[ -n "$NUM" ]]; then
      DOWNLOAD_URL="$HOST/books/$NUM/download"
      echo "Constructed download URL from entry id: $DOWNLOAD_URL"
    fi
  fi
fi

if [[ -z "$DOWNLOAD_URL" ]]; then
  echo "FAIL: could not determine download URL from first entry. Dumping entry XML:"
  xmllint --format "$ALL_XML" | sed -n '1,200p'
  exit 5
fi

# If the href is relative, prefix host
if [[ "$DOWNLOAD_URL" =~ ^/ ]]; then
  DOWNLOAD_URL="$HOST$DOWNLOAD_URL"
fi

echo "[STEP 3] HEAD download URL to inspect headers: $DOWNLOAD_URL"
curl -s -I -u "$CRED" -L "$DOWNLOAD_URL" -o "$TMPDIR/download.headers" -w "%{http_code}\n" > "$HTTP_STATUS_FILE"
HTTP_CODE=$(cat "$HTTP_STATUS_FILE" | tr -d '\r\n')
if [[ "$HTTP_CODE" -ge 400 ]]; then
  echo "FAIL: download HEAD returned HTTP $HTTP_CODE"
  cat "$TMPDIR/download.headers"
  exit 6
fi

echo "Download headers:"
cat "$TMPDIR/download.headers"

# Finally perform the download and save to file
OUTFILE="$TMPDIR/book_download.bin"
echo "[STEP 4] Downloading book to $OUTFILE (may be large, streaming)..."
# Use -L to follow redirects (signed URL to CDN), -u for Basic Auth (in case PHP path used)
curl -s -L -u "$CRED" "$DOWNLOAD_URL" -o "$OUTFILE" -w "%{http_code}\n" > "$HTTP_STATUS_FILE"
HTTP_CODE=$(cat "$HTTP_STATUS_FILE" | tr -d '\r\n')
if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "206" ]]; then
  echo "FAIL: download returned HTTP $HTTP_CODE"
  exit 7
fi

FILESZ=$(stat -c%s "$OUTFILE" 2>/dev/null || stat -f%z "$OUTFILE" 2>/dev/null || true)
echo "Download completed: $OUTFILE ($FILESZ bytes) HTTP $HTTP_CODE"

# Quick validation of file MIME signature (if file non-empty)
if [[ -n "$FILESZ" && "$FILESZ" -gt 4 ]]; then
  echo "File type detection (first bytes):"
  head -c 8 "$OUTFILE" | xxd -p -c 8 || true
fi

# Clean up
# rm -rf "$TMPDIR"

echo "ALL STEPS OK"
exit 0
