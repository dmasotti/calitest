#!/usr/bin/env bash
# Description: Run the Locust-based Calimob sync load harness with env-driven configuration.
# Usage: tests/performance/locust/run_locust.sh [options]

set -euo pipefail

show_help() {
  cat <<'EOF'
Usage: run_locust.sh [OPTIONS]

Run the Locust harness for sync/v5, library-hash and optional presigned upload flows.

OPTIONS:
  --users N             Number of concurrent users (default: 5)
  --spawn-rate N        Spawn rate per second (default: 1)
  --run-time DURATION   Duration, e.g. 2m, 30s, 10m (default: 2m)
  --headless            Run without web UI (default)
  --web                 Run with Locust web UI
  --host URL            Override CALIMOB_LOCUST_BASE_URL
  --html-report PATH    Save Locust HTML report
  -h, --help            Show this help

Required environment:
  CALIMOB_LOCUST_API_TOKEN

Examples:
  CALIMOB_LOCUST_API_TOKEN="..." tests/performance/locust/run_locust.sh --users 5 --spawn-rate 2 --run-time 2m
  CALIMOB_LOCUST_API_TOKEN="..." CALIMOB_LOCUST_ENABLE_PRESIGNED=on tests/performance/locust/run_locust.sh --users 2 --spawn-rate 1 --run-time 1m
EOF
}

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
LOCUST_DIR="$ROOT_DIR/tests/performance/locust"
USERS="${CALIMOB_LOCUST_USERS:-5}"
SPAWN_RATE="${CALIMOB_LOCUST_SPAWN_RATE:-1}"
RUN_TIME="${CALIMOB_LOCUST_RUN_TIME:-2m}"
HOST_OVERRIDE=""
HTML_REPORT=""
HEADLESS="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --users)
      USERS="$2"
      shift 2
      ;;
    --spawn-rate)
      SPAWN_RATE="$2"
      shift 2
      ;;
    --run-time)
      RUN_TIME="$2"
      shift 2
      ;;
    --headless)
      HEADLESS="1"
      shift
      ;;
    --web)
      HEADLESS="0"
      shift
      ;;
    --host)
      HOST_OVERRIDE="$2"
      shift 2
      ;;
    --html-report)
      HTML_REPORT="$2"
      shift 2
      ;;
    -h|--help)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      show_help
      exit 1
      ;;
  esac
done

if [[ -z "${CALIMOB_LOCUST_API_TOKEN:-}" ]]; then
  echo "Missing CALIMOB_LOCUST_API_TOKEN" >&2
  exit 1
fi

if ! command -v locust >/dev/null 2>&1; then
  echo "locust command not found. Install with:" >&2
  echo "  python3 -m pip install -r tests/performance/locust/requirements.txt" >&2
  exit 1
fi

mkdir -p /tmp
LOG_FILE="/tmp/locust_sync_$(date +%Y%m%d_%H%M%S).log"

LOCUST_ARGS=(
  -f "$LOCUST_DIR/locustfile.py"
)

if [[ -n "$HOST_OVERRIDE" ]]; then
  export CALIMOB_LOCUST_BASE_URL="$HOST_OVERRIDE"
fi

if [[ "$HEADLESS" == "1" ]]; then
  LOCUST_ARGS+=(
    --headless
    --users "$USERS"
    --spawn-rate "$SPAWN_RATE"
    --run-time "$RUN_TIME"
  )
fi

if [[ -n "$HTML_REPORT" ]]; then
  LOCUST_ARGS+=(--html "$HTML_REPORT")
fi

echo "[locust-sync] users=$USERS spawn_rate=$SPAWN_RATE run_time=$RUN_TIME headless=$HEADLESS log=$LOG_FILE"
locust "${LOCUST_ARGS[@]}" 2>&1 | tee "$LOG_FILE"
