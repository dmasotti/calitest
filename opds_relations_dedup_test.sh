#!/bin/bash
# Test: OPDS feed relations (authors, series, tags) must not have duplicates.
#
# RD-01: Authors per entry must not exceed 10 on average
# RD-02: Series per entry must not exceed 3 on average
# RD-03: Tags per entry must not exceed 10 on average
# RD-04: After fix, authors count should match unique author names

set -e
OPDS_URL="https://new.caliwebapp.com/opds/all?page=1"
CREDS="dmasotti@gmail.com:Pisello72!"

FEED=$(curl -s -u "$CREDS" "$OPDS_URL")
ENTRIES=$(echo "$FEED" | grep -c "<entry>")
echo "Entries on page: $ENTRIES"

echo ""
echo "=== RD-01: Authors per entry ==="
TOTAL_AUTHORS=$(echo "$FEED" | grep -c "<author>")
if [ "$ENTRIES" -gt 0 ]; then
  AVG=$((TOTAL_AUTHORS / ENTRIES))
  echo "Total <author> tags: $TOTAL_AUTHORS, Average: $AVG/entry"
  if [ "$AVG" -gt 10 ]; then
    echo "FAIL RD-01: $AVG authors/entry — cartesian product duplicates"
    exit 1
  else
    echo "PASS RD-01"
  fi
fi

echo ""
echo "=== RD-02: Series per entry ==="
TOTAL_SERIES=$(echo "$FEED" | grep -c "schema:Series" || true)
if [ "$ENTRIES" -gt 0 ] && [ "$TOTAL_SERIES" -gt 0 ]; then
  AVG=$((TOTAL_SERIES / ENTRIES))
  echo "Total series refs: $TOTAL_SERIES, Average: $AVG/entry"
  if [ "$AVG" -gt 3 ]; then
    echo "FAIL RD-02: $AVG series/entry — likely duplicates"
    exit 1
  else
    echo "PASS RD-02"
  fi
else
  echo "PASS RD-02 (no series in feed or no entries)"
fi

echo ""
echo "=== RD-03: Tags/categories per entry ==="
TOTAL_TAGS=$(echo "$FEED" | grep -c "<category" || true)
if [ "$ENTRIES" -gt 0 ] && [ "$TOTAL_TAGS" -gt 0 ]; then
  AVG=$((TOTAL_TAGS / ENTRIES))
  echo "Total <category> tags: $TOTAL_TAGS, Average: $AVG/entry"
  if [ "$AVG" -gt 10 ]; then
    echo "FAIL RD-03: $AVG tags/entry — likely duplicates"
    exit 1
  else
    echo "PASS RD-03"
  fi
else
  echo "PASS RD-03 (no tags in feed or no entries)"
fi

echo ""
echo "=== RD-04: Author names should be unique per entry ==="
# Extract first entry's authors and check uniqueness
FIRST_ENTRY=$(echo "$FEED" | sed -n '/<entry>/,/<\/entry>/p' | head -100)
AUTHOR_COUNT=$(echo "$FIRST_ENTRY" | grep -c "<author>" || true)
UNIQUE_AUTHORS=$(echo "$FIRST_ENTRY" | grep -o '<name>[^<]*</name>' | sort -u | wc -l | tr -d ' ')
echo "First entry: $AUTHOR_COUNT authors, $UNIQUE_AUTHORS unique"
if [ "$AUTHOR_COUNT" -gt 0 ] && [ "$AUTHOR_COUNT" -ne "$UNIQUE_AUTHORS" ]; then
  echo "FAIL RD-04: $AUTHOR_COUNT authors but only $UNIQUE_AUTHORS unique — duplicates present"
  exit 1
else
  echo "PASS RD-04"
fi
