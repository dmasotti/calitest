#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-medium}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HTML_DIR="$ROOT_DIR/html"
PERF_DB_CONNECTION="${CALIMOB_PERF_DB_CONNECTION:-mysql}"
PERF_DB_HOST="${CALIMOB_PERF_DB_HOST:-127.0.0.1}"
PERF_DB_PORT="${CALIMOB_PERF_DB_PORT:-3306}"
PERF_DB_DATABASE="${CALIMOB_PERF_DB_DATABASE:-caliweb_perf}"
PERF_DB_USERNAME="${CALIMOB_PERF_DB_USERNAME:-root}"
PERF_DB_PASSWORD="${CALIMOB_PERF_DB_PASSWORD:-}"

case "$PROFILE" in
  small)
    BOOKS="${CALIMOB_CATALOG_PERF_BOOKS:-3000}"
    ITERS="${CALIMOB_CATALOG_PERF_ITERATIONS:-3}"
    PER_PAGE="${CALIMOB_CATALOG_PERF_PER_PAGE:-50}"
    B_SHOW="${CALIMOB_CATALOG_PERF_BUDGET_SHOW_P95_MS:-1000}"
    B_SEARCH="${CALIMOB_CATALOG_PERF_BUDGET_SEARCH_P95_MS:-1200}"
    ;;
  medium)
    BOOKS="${CALIMOB_CATALOG_PERF_BOOKS:-10000}"
    ITERS="${CALIMOB_CATALOG_PERF_ITERATIONS:-5}"
    PER_PAGE="${CALIMOB_CATALOG_PERF_PER_PAGE:-50}"
    B_SHOW="${CALIMOB_CATALOG_PERF_BUDGET_SHOW_P95_MS:-2500}"
    B_SEARCH="${CALIMOB_CATALOG_PERF_BUDGET_SEARCH_P95_MS:-2800}"
    ;;
  large)
    BOOKS="${CALIMOB_CATALOG_PERF_BOOKS:-30000}"
    ITERS="${CALIMOB_CATALOG_PERF_ITERATIONS:-3}"
    PER_PAGE="${CALIMOB_CATALOG_PERF_PER_PAGE:-100}"
    B_SHOW="${CALIMOB_CATALOG_PERF_BUDGET_SHOW_P95_MS:-6000}"
    B_SEARCH="${CALIMOB_CATALOG_PERF_BUDGET_SEARCH_P95_MS:-7000}"
    ;;
  *)
    echo "Unknown profile: $PROFILE"
    echo "Usage: $0 [small|medium|large]"
    exit 1
    ;;
esac

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${ROOT_DIR}/tests/server/tmp/catalog_query_perf_${PROFILE}_${TS}.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[catalog_query_perf] profile=$PROFILE books=$BOOKS iters=$ITERS per_page=$PER_PAGE"
echo "[catalog_query_perf] budgets show_p95=$B_SHOW search_p95=$B_SEARCH"
echo "[catalog_query_perf] log=$LOG_FILE"
echo "[catalog_query_perf] db=${PERF_DB_CONNECTION}://${PERF_DB_USERNAME}@${PERF_DB_HOST}:${PERF_DB_PORT}/${PERF_DB_DATABASE}"

prepare_perf_db() {
  (
    cd "$HTML_DIR"
    DB_CONNECTION="$PERF_DB_CONNECTION" \
    DB_HOST="$PERF_DB_HOST" \
    DB_PORT="$PERF_DB_PORT" \
    DB_DATABASE="$PERF_DB_DATABASE" \
    DB_USERNAME="$PERF_DB_USERNAME" \
    DB_PASSWORD="$PERF_DB_PASSWORD" \
    php -r '
      $driver = getenv("DB_CONNECTION") ?: "mysql";
      if ($driver !== "mysql") { exit(0); }
      $host = getenv("DB_HOST") ?: "127.0.0.1";
      $port = getenv("DB_PORT") ?: "3306";
      $user = getenv("DB_USERNAME") ?: "root";
      $pass = getenv("DB_PASSWORD") ?: "";
      $db   = getenv("DB_DATABASE") ?: "caliweb_perf";
      $pdo = new PDO("mysql:host={$host};port={$port};charset=utf8mb4", $user, $pass, [
        PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
      ]);
      $pdo->exec("CREATE DATABASE IF NOT EXISTS `{$db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci");
    '
    DB_CONNECTION="$PERF_DB_CONNECTION" \
    DB_HOST="$PERF_DB_HOST" \
    DB_PORT="$PERF_DB_PORT" \
    DB_DATABASE="$PERF_DB_DATABASE" \
    DB_USERNAME="$PERF_DB_USERNAME" \
    DB_PASSWORD="$PERF_DB_PASSWORD" \
    php artisan db:wipe --drop-views --force
    DB_CONNECTION="$PERF_DB_CONNECTION" \
    DB_HOST="$PERF_DB_HOST" \
    DB_PORT="$PERF_DB_PORT" \
    DB_DATABASE="$PERF_DB_DATABASE" \
    DB_USERNAME="$PERF_DB_USERNAME" \
    DB_PASSWORD="$PERF_DB_PASSWORD" \
    php artisan migrate --force
  )
}

prepare_perf_db

(
  cd "$HTML_DIR"
  APP_ENV=testing \
  DB_CONNECTION="$PERF_DB_CONNECTION" \
  DB_HOST="$PERF_DB_HOST" \
  DB_PORT="$PERF_DB_PORT" \
  DB_DATABASE="$PERF_DB_DATABASE" \
  DB_USERNAME="$PERF_DB_USERNAME" \
  DB_PASSWORD="$PERF_DB_PASSWORD" \
  CALIMOB_CATALOG_PERF_TESTS=1 \
  CALIMOB_CATALOG_PERF_BOOKS="$BOOKS" \
  CALIMOB_CATALOG_PERF_ITERATIONS="$ITERS" \
  CALIMOB_CATALOG_PERF_PER_PAGE="$PER_PAGE" \
  CALIMOB_CATALOG_PERF_BUDGET_SHOW_P95_MS="$B_SHOW" \
  CALIMOB_CATALOG_PERF_BUDGET_SEARCH_P95_MS="$B_SEARCH" \
  php artisan test tests/Performance/LibraryCatalogQueryLoadTest.php
) 2>&1 | tee "$LOG_FILE"

REPORT_PATH="$(rg -o 'report=.*' "$LOG_FILE" | tail -1 | sed 's/^report=//')"
if [[ -n "${REPORT_PATH:-}" && -f "$REPORT_PATH" ]]; then
  echo "[catalog_query_perf] report=$REPORT_PATH"
  if command -v jq >/dev/null 2>&1; then
    jq -r '"[catalog_query_perf] show_p95=\(.show_ms_p95) search_p95=\(.search_ms_p95) books=\(.books) iters=\(.iterations)"' "$REPORT_PATH"
  fi
else
  echo "[catalog_query_perf] WARNING: report path not found in output"
fi
