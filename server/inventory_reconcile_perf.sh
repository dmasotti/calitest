#!/usr/bin/env bash
set -euo pipefail

PROFILE="${1:-medium}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HTML_DIR="$ROOT_DIR/html"
PERF_DB_CONNECTION="${CALIMOB_PERF_DB_CONNECTION:-mysql}"
PERF_DB_HOST="${CALIMOB_PERF_DB_HOST:-127.0.0.1}"
PERF_DB_PORT="${CALIMOB_PERF_DB_PORT:-3306}"
PERF_DB_DATABASE="${CALIMOB_PERF_DB_DATABASE:-test_caliweb_perf}"
PERF_DB_USERNAME="${CALIMOB_PERF_DB_USERNAME:-root}"
PERF_DB_PASSWORD="${CALIMOB_PERF_DB_PASSWORD:-}"

case "$PROFILE" in
  small)
    CLIENT_BOOKS="${CALIMOB_INVENTORY_PERF_CLIENT_BOOKS:-3000}"
    CLIENT_BATCH="${CALIMOB_INVENTORY_PERF_CLIENT_BATCH_SIZE:-300}"
    SERVER_BATCH="${CALIMOB_INVENTORY_PERF_SERVER_BATCH_SIZE:-150}"
    B_REQ="${CALIMOB_INVENTORY_PERF_BUDGET_REQUEST_P95_MS:-1200}"
    B_CYCLE="${CALIMOB_INVENTORY_PERF_BUDGET_CYCLE_MS:-25000}"
    ;;
  medium)
    CLIENT_BOOKS="${CALIMOB_INVENTORY_PERF_CLIENT_BOOKS:-10000}"
    CLIENT_BATCH="${CALIMOB_INVENTORY_PERF_CLIENT_BATCH_SIZE:-500}"
    SERVER_BATCH="${CALIMOB_INVENTORY_PERF_SERVER_BATCH_SIZE:-200}"
    B_REQ="${CALIMOB_INVENTORY_PERF_BUDGET_REQUEST_P95_MS:-2200}"
    B_CYCLE="${CALIMOB_INVENTORY_PERF_BUDGET_CYCLE_MS:-90000}"
    ;;
  large)
    CLIENT_BOOKS="${CALIMOB_INVENTORY_PERF_CLIENT_BOOKS:-25000}"
    CLIENT_BATCH="${CALIMOB_INVENTORY_PERF_CLIENT_BATCH_SIZE:-800}"
    SERVER_BATCH="${CALIMOB_INVENTORY_PERF_SERVER_BATCH_SIZE:-300}"
    B_REQ="${CALIMOB_INVENTORY_PERF_BUDGET_REQUEST_P95_MS:-4500}"
    B_CYCLE="${CALIMOB_INVENTORY_PERF_BUDGET_CYCLE_MS:-180000}"
    ;;
  *)
    echo "Unknown profile: $PROFILE"
    echo "Usage: $0 [small|medium|large]"
    exit 1
    ;;
esac

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${ROOT_DIR}/tests/server/tmp/inventory_reconcile_perf_${PROFILE}_${TS}.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[inventory_reconcile_perf] profile=$PROFILE client_books=$CLIENT_BOOKS client_batch=$CLIENT_BATCH server_batch=$SERVER_BATCH"
echo "[inventory_reconcile_perf] budgets request_p95=$B_REQ cycle_ms=$B_CYCLE"
echo "[inventory_reconcile_perf] log=$LOG_FILE"
echo "[inventory_reconcile_perf] db=${PERF_DB_CONNECTION}://${PERF_DB_USERNAME}@${PERF_DB_HOST}:${PERF_DB_PORT}/${PERF_DB_DATABASE}"

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
      $db   = getenv("DB_DATABASE") ?: "test_caliweb_perf";
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
  CALIMOB_INVENTORY_PERF_TESTS=1 \
  CALIMOB_INVENTORY_PERF_CLIENT_BOOKS="$CLIENT_BOOKS" \
  CALIMOB_INVENTORY_PERF_CLIENT_BATCH_SIZE="$CLIENT_BATCH" \
  CALIMOB_INVENTORY_PERF_SERVER_BATCH_SIZE="$SERVER_BATCH" \
  CALIMOB_INVENTORY_PERF_BUDGET_REQUEST_P95_MS="$B_REQ" \
  CALIMOB_INVENTORY_PERF_BUDGET_CYCLE_MS="$B_CYCLE" \
  php artisan test tests/Performance/SyncV5InventoryReconcileLoadTest.php
) 2>&1 | tee "$LOG_FILE"

REPORT_PATH="$(rg -o 'report=.*' "$LOG_FILE" | tail -1 | sed 's/^report=//')"
if [[ -n "${REPORT_PATH:-}" && -f "$REPORT_PATH" ]]; then
  echo "[inventory_reconcile_perf] report=$REPORT_PATH"
  if command -v jq >/dev/null 2>&1; then
    jq -r '"[inventory_reconcile_perf] request_p95=\(.request_ms_p95) cycle_ms=\(.cycle_ms) requests=\(.requests_count) client_books=\(.client_books)"' "$REPORT_PATH"
  fi
else
  echo "[inventory_reconcile_perf] WARNING: report path not found in output"
fi
