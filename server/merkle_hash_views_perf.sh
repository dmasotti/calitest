#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HTML_DIR="${ROOT_DIR}/html"
PROFILE="${1:-small}"

case "$PROFILE" in
  small)
    BOOKS="${CALIMOB_MERKLE_PERF_BOOKS:-10000}"
    ITERS="${CALIMOB_MERKLE_PERF_ITERATIONS:-5}"
    B_LEAF="${CALIMOB_MERKLE_PERF_BUDGET_LEAF_P95_MS:-4000}"
    B_BRANCH="${CALIMOB_MERKLE_PERF_BUDGET_BRANCH_P95_MS:-1500}"
    B_ROOT="${CALIMOB_MERKLE_PERF_BUDGET_ROOT_P95_MS:-600}"
    ;;
  medium)
    BOOKS="${CALIMOB_MERKLE_PERF_BOOKS:-50000}"
    ITERS="${CALIMOB_MERKLE_PERF_ITERATIONS:-5}"
    B_LEAF="${CALIMOB_MERKLE_PERF_BUDGET_LEAF_P95_MS:-12000}"
    B_BRANCH="${CALIMOB_MERKLE_PERF_BUDGET_BRANCH_P95_MS:-3000}"
    B_ROOT="${CALIMOB_MERKLE_PERF_BUDGET_ROOT_P95_MS:-1200}"
    ;;
  large)
    BOOKS="${CALIMOB_MERKLE_PERF_BOOKS:-100000}"
    ITERS="${CALIMOB_MERKLE_PERF_ITERATIONS:-3}"
    B_LEAF="${CALIMOB_MERKLE_PERF_BUDGET_LEAF_P95_MS:-25000}"
    B_BRANCH="${CALIMOB_MERKLE_PERF_BUDGET_BRANCH_P95_MS:-6000}"
    B_ROOT="${CALIMOB_MERKLE_PERF_BUDGET_ROOT_P95_MS:-2500}"
    ;;
  *)
    echo "Usage: $0 [small|medium|large]" >&2
    exit 2
    ;;
esac

LOG_DIR="${ROOT_DIR}/tests/server/tmp"
mkdir -p "$LOG_DIR"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/merkle_hash_views_perf_${PROFILE}_${TS}.log"

echo "[merkle_hash_views_perf] profile=$PROFILE books=$BOOKS iters=$ITERS"
echo "[merkle_hash_views_perf] budgets leaf_p95<=$B_LEAF branch_p95<=$B_BRANCH root_p95<=$B_ROOT"
echo "[merkle_hash_views_perf] log=$LOG_FILE"

(
  cd "$HTML_DIR"
  CALIMOB_PERF_TESTS=1 \
  CALIMOB_MERKLE_PERF_BOOKS="$BOOKS" \
  CALIMOB_MERKLE_PERF_ITERATIONS="$ITERS" \
  CALIMOB_MERKLE_PERF_BUDGET_LEAF_P95_MS="$B_LEAF" \
  CALIMOB_MERKLE_PERF_BUDGET_BRANCH_P95_MS="$B_BRANCH" \
  CALIMOB_MERKLE_PERF_BUDGET_ROOT_P95_MS="$B_ROOT" \
  php artisan test tests/Performance/MerkleHashViewsLoadTest.php
) 2>&1 | tee "$LOG_FILE"

REPORT_PATH="$(grep -oE 'report=.*' "$LOG_FILE" | tail -1 | sed 's/^report=//')"
if [[ -n "${REPORT_PATH:-}" && -f "$REPORT_PATH" ]]; then
  echo "[merkle_hash_views_perf] report=$REPORT_PATH"
  if command -v jq >/dev/null 2>&1; then
    jq -r '"[merkle_hash_views_perf] leaf_p95_ms=\(.leaf_ms_p95) branch_p95_ms=\(.branch_ms_p95) root_p95_ms=\(.root_ms_p95) books=\(.books) iters=\(.iterations)"' "$REPORT_PATH"
  fi
else
  echo "[merkle_hash_views_perf] WARNING: report path not found in output" >&2
fi
