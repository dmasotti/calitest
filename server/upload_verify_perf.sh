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
    SESSIONS="${CALIMOB_UPLOAD_PERF_SESSIONS:-200}"
    B_START="${CALIMOB_UPLOAD_PERF_BUDGET_START_P95_MS:-300}"
    B_COMPLETE="${CALIMOB_UPLOAD_PERF_BUDGET_COMPLETE_P95_MS:-300}"
    B_VERIFY="${CALIMOB_UPLOAD_PERF_BUDGET_VERIFY_P95_MS:-600}"
    B_SHOW="${CALIMOB_UPLOAD_PERF_BUDGET_SHOW_P95_MS:-250}"
    B_E2E="${CALIMOB_UPLOAD_PERF_BUDGET_E2E_P95_MS:-1200}"
    ;;
  medium)
    SESSIONS="${CALIMOB_UPLOAD_PERF_SESSIONS:-1000}"
    B_START="${CALIMOB_UPLOAD_PERF_BUDGET_START_P95_MS:-800}"
    B_COMPLETE="${CALIMOB_UPLOAD_PERF_BUDGET_COMPLETE_P95_MS:-800}"
    B_VERIFY="${CALIMOB_UPLOAD_PERF_BUDGET_VERIFY_P95_MS:-1600}"
    B_SHOW="${CALIMOB_UPLOAD_PERF_BUDGET_SHOW_P95_MS:-700}"
    B_E2E="${CALIMOB_UPLOAD_PERF_BUDGET_E2E_P95_MS:-3500}"
    ;;
  large)
    SESSIONS="${CALIMOB_UPLOAD_PERF_SESSIONS:-3000}"
    B_START="${CALIMOB_UPLOAD_PERF_BUDGET_START_P95_MS:-1500}"
    B_COMPLETE="${CALIMOB_UPLOAD_PERF_BUDGET_COMPLETE_P95_MS:-1500}"
    B_VERIFY="${CALIMOB_UPLOAD_PERF_BUDGET_VERIFY_P95_MS:-3000}"
    B_SHOW="${CALIMOB_UPLOAD_PERF_BUDGET_SHOW_P95_MS:-1200}"
    B_E2E="${CALIMOB_UPLOAD_PERF_BUDGET_E2E_P95_MS:-7000}"
    ;;
  *)
    echo "Unknown profile: $PROFILE"
    echo "Usage: $0 [small|medium|large]"
    exit 1
    ;;
esac

TS="$(date +%Y%m%d_%H%M%S)"
LOG_FILE="${ROOT_DIR}/tests/server/tmp/upload_verify_perf_${PROFILE}_${TS}.log"
mkdir -p "$(dirname "$LOG_FILE")"

echo "[upload_verify_perf] profile=$PROFILE sessions=$SESSIONS"
echo "[upload_verify_perf] budgets start=$B_START complete=$B_COMPLETE verify=$B_VERIFY show=$B_SHOW e2e=$B_E2E"
echo "[upload_verify_perf] log=$LOG_FILE"
echo "[upload_verify_perf] db=${PERF_DB_CONNECTION}://${PERF_DB_USERNAME}@${PERF_DB_HOST}:${PERF_DB_PORT}/${PERF_DB_DATABASE}"

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
  CALIMOB_UPLOAD_PERF_TESTS=1 \
  CALIMOB_UPLOAD_PERF_SESSIONS="$SESSIONS" \
  CALIMOB_UPLOAD_PERF_BUDGET_START_P95_MS="$B_START" \
  CALIMOB_UPLOAD_PERF_BUDGET_COMPLETE_P95_MS="$B_COMPLETE" \
  CALIMOB_UPLOAD_PERF_BUDGET_VERIFY_P95_MS="$B_VERIFY" \
  CALIMOB_UPLOAD_PERF_BUDGET_SHOW_P95_MS="$B_SHOW" \
  CALIMOB_UPLOAD_PERF_BUDGET_E2E_P95_MS="$B_E2E" \
  php artisan test tests/Performance/SyncUploadVerifyLoadTest.php
) 2>&1 | tee "$LOG_FILE"

REPORT_PATH="$(rg -o 'report=.*' "$LOG_FILE" | tail -1 | sed 's/^report=//')"
if [[ -n "${REPORT_PATH:-}" && -f "$REPORT_PATH" ]]; then
  echo "[upload_verify_perf] report=$REPORT_PATH"
  if command -v jq >/dev/null 2>&1; then
    jq -r '"[upload_verify_perf] start_p95=\(.start_ms_p95) complete_p95=\(.complete_ms_p95) verify_p95=\(.verify_ms_p95) show_p95=\(.show_ms_p95) e2e_p95=\(.e2e_ms_p95) sessions=\(.sessions)"' "$REPORT_PATH"
  fi
else
  echo "[upload_verify_perf] WARNING: report path not found in output"
fi
