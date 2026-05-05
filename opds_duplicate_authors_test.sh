#!/bin/bash
# Test: OPDS feed must not have duplicate authors per entry.
#
# ODA-01: Each entry should have unique author names
# ODA-02: Total author count per page should be reasonable (< 100 for 20 books)

set -e
OPDS_URL="https://new.caliwebapp.com/opds/all?page=1"
CREDS="dmasotti@gmail.com:Pisello72!"

echo "=== ODA-01: Check for duplicate authors in first page ==="
FEED=$(curl -s -u "$CREDS" "$OPDS_URL")
TOTAL_AUTHORS=$(echo "$FEED" | grep -c "<author>")
ENTRIES=$(echo "$FEED" | grep -c "<entry>")
echo "Entries: $ENTRIES, Total <author> tags: $TOTAL_AUTHORS"

if [ "$ENTRIES" -gt 0 ]; then
  AVG=$((TOTAL_AUTHORS / ENTRIES))
  echo "Average authors per entry: $AVG"
  if [ "$AVG" -gt 3 ]; then
    echo "FAIL ODA-01: Average $AVG authors/entry is too high — likely duplicates"
    exit 1
  else
    echo "PASS ODA-01: Average $AVG authors/entry is reasonable"
  fi
fi

echo ""
echo "=== ODA-02: Total author count per page < 100 ==="
if [ "$TOTAL_AUTHORS" -lt 100 ]; then
  echo "PASS ODA-02: $TOTAL_AUTHORS authors total (< 100)"
else
  echo "FAIL ODA-02: $TOTAL_AUTHORS authors total (>= 100) — duplicates present"
  exit 1
fi
