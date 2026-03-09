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
    BOOKS="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BOOKS:-10000}"
    ITERS="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_ITERATIONS:-5}"
    BUDGET_NUMERIC_P95="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_NUMERIC_P95_MS:-5000}"
    BUDGET_UUID_P95="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_UUID_P95_MS:-5000}"
    ;;
  medium)
    BOOKS="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BOOKS:-50000}"
    ITERS="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_ITERATIONS:-5}"
    BUDGET_NUMERIC_P95="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_NUMERIC_P95_MS:-15000}"
    BUDGET_UUID_P95="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_UUID_P95_MS:-15000}"
    ;;
  large)
    BOOKS="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BOOKS:-100000}"
    ITERS="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_ITERATIONS:-3}"
    BUDGET_NUMERIC_P95="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_NUMERIC_P95_MS:-30000}"
    BUDGET_UUID_P95="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_UUID_P95_MS:-30000}"
    ;;
  *)
    echo "Unknown profile: $PROFILE"
    echo "Usage: $0 [small|medium|large]"
    exit 1
    ;;
esac

CHUNK="${CALIMOB_SYNCV5_LIBRARY_HASH_PERF_INSERT_CHUNK:-1000}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${ROOT_DIR}/tests/server/tmp/library_hash_endpoint_perf_${PROFILE}_${TS}.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[library_hash_endpoint_perf] profile=$PROFILE books=$BOOKS iters=$ITERS chunk=$CHUNK"
echo "[library_hash_endpoint_perf] budgets numeric_p95<=$BUDGET_NUMERIC_P95 uuid_p95<=$BUDGET_UUID_P95"
echo "[library_hash_endpoint_perf] log=$LOG_FILE"
echo "[library_hash_endpoint_perf] db=${PERF_DB_CONNECTION}://${PERF_DB_USERNAME}@${PERF_DB_HOST}:${PERF_DB_PORT}/${PERF_DB_DATABASE}"

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
  CALIMOB_SYNCV5_LIBRARY_HASH_PERF_TESTS=1 \
  CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BOOKS="$BOOKS" \
  CALIMOB_SYNCV5_LIBRARY_HASH_PERF_ITERATIONS="$ITERS" \
  CALIMOB_SYNCV5_LIBRARY_HASH_PERF_INSERT_CHUNK="$CHUNK" \
  CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_NUMERIC_P95_MS="$BUDGET_NUMERIC_P95" \
  CALIMOB_SYNCV5_LIBRARY_HASH_PERF_BUDGET_UUID_P95_MS="$BUDGET_UUID_P95" \
  php artisan test tests/Performance/SyncV5LibraryHashEndpointLoadTest.php
) 2>&1 | tee "$LOG_FILE"

REPORT_PATH="$(rg -o 'report=.*' "$LOG_FILE" | tail -1 | sed 's/^report=//')"
if [[ -n "${REPORT_PATH:-}" && -f "$REPORT_PATH" ]]; then
  echo "[library_hash_endpoint_perf] report=$REPORT_PATH"
  if command -v jq >/dev/null 2>&1; then
    jq -r '"[library_hash_endpoint_perf] numeric_p95_ms=\(.numeric_ms_p95) uuid_p95_ms=\(.uuid_ms_p95) books=\(.books) iters=\(.iterations)"' "$REPORT_PATH"
  fi
else
  echo "[library_hash_endpoint_perf] WARNING: report path not found in output"
fi
