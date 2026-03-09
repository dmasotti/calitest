#!/usr/bin/env bash
# Script per preparare l'ambiente headless plugin:
# 1. determina l'UUID della libreria Calibre locale (fallback a tests/plugin/fixtures/CalibreTestLocal)
# 2. elimina eventuali librerie esistenti per l'utente (per liberare lo slot libero)
# 3. ricrea la libreria via `headless_setup_library.sh`
# 4. genera un `sync_calimob.json` temporaneo con discovery/rest token e mapping della libreria

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/../../.." && pwd)
HTML_DIR="$PROJECT_ROOT/html"
DEFAULT_LIBRARY_PATH="$PROJECT_ROOT/tests/plugin/fixtures/CalibreTestLocal"
DEFAULT_CONFIG_PATH="$PROJECT_ROOT/tests/plugin/integration/generated_sync_calimob.json"

REQUIRED_ENV=(
  "CALIMOB_DISCOVERY_URL"
  "TEST_USER_EMAIL"
  "TEST_USER_PASSWORD"
)

for KEY in "${REQUIRED_ENV[@]}"; do
  if [[ -z "${!KEY:-}" ]]; then
    echo "Errore: imposta la variabile d'ambiente $KEY" >&2
    exit 1
  fi
done

CALIBRE_LIBRARY_PATH="${CALIBRE_LIBRARY_PATH:-$DEFAULT_LIBRARY_PATH}"
if [[ ! -d "$CALIBRE_LIBRARY_PATH" ]]; then
  echo "Errore: libreria Calibre locale non trovata in $CALIBRE_LIBRARY_PATH" >&2
  exit 1
fi

CALIBRE_ID="${CALIBRE_LIBRARY_ID:-}"
metadata_db="$CALIBRE_LIBRARY_PATH/metadata.db"
if [[ -z "$CALIBRE_ID" && -f "$metadata_db" ]]; then
  CALIBRE_ID=$(sqlite3 "$metadata_db" "SELECT uuid FROM library_id LIMIT 1;" 2>/dev/null || true)
fi

if [[ -z "$CALIBRE_ID" ]]; then
  echo "Errore: non posso determinare l'UUID della libreria Calibre. Imposta CALIBRE_LIBRARY_ID." >&2
  exit 1
fi

command -v curl >/dev/null 2>&1 || { echo "curl non installato"; exit 1; }
command -v jq >/dev/null 2>&1 || { echo "jq non installato"; exit 1; }
command -v sqlite3 >/dev/null 2>&1 || { echo "sqlite3 non installato"; exit 1; }
command -v php >/dev/null 2>&1 || { echo "php non installato"; exit 1; }

DISCOVERY_URL="$CALIMOB_DISCOVERY_URL"
FORCE_API_URL="${CALIMOB_FORCE_API_URL:-}"

function discover_api_url() {
  if [[ -n "$FORCE_API_URL" ]]; then
    echo "$FORCE_API_URL"
    return 0
  fi
  local url
  url=$(curl -s "${DISCOVERY_URL}/discovery.php" | jq -r '.api_url // empty' 2>/dev/null || true)
  if [[ -z "$url" || "$url" == "null" ]]; then
    url=$(curl -s "${DISCOVERY_URL}/api/discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
  fi
  if [[ -z "$url" || "$url" == "null" ]]; then
    echo "Errore: discovery fallita per $DISCOVERY_URL" >&2
    exit 1
  fi
  echo "$url"
}

function login() {
  local api_url="$1"
  local payload
  payload=$(jq -nc --arg email "$TEST_USER_EMAIL" --arg password "$TEST_USER_PASSWORD" '{email: $email, password: $password}')
  local response
  response=$(curl -s -X POST "$api_url/auth/login" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -d "$payload")
  local token
  token=$(echo "$response" | jq -r '.token // empty')
  if [[ -z "$token" || "$token" == "null" ]]; then
    echo "Errore: login fallito" >&2
    echo "$response" >&2
    exit 1
  fi
  echo "$token"
}

function cleanup_libraries() {
  export HTML_DIR
  php <<'PHP'
<?php
  $htmlDir = getenv('HTML_DIR');
  if (!$htmlDir) {
    fwrite(STDERR, "HTML_DIR non impostato\n");
    exit(1);
  }
  require $htmlDir . '/vendor/autoload.php';
  $app = require_once $htmlDir . '/bootstrap/app.php';
  $kernel = $app->make(Illuminate\Contracts\Console\Kernel::class);
  $kernel->bootstrap();
  $email = getenv('TEST_USER_EMAIL');
  if (!$email) {
    fwrite(STDERR, "TEST_USER_EMAIL non impostato\n");
    exit(1);
  }
  $user = \App\Models\User::where('email', $email)->first();
  if (!$user) {
    fwrite(STDERR, "Utente $email non trovato; niente da eliminare\n");
    exit(0);
  }
  $libraries = \App\Models\Library::where('user_id', $user->id)->get();
  if ($libraries->isEmpty()) {
    fwrite(STDOUT, "Nessuna libreria da eliminare per l'utente $email\n");
    exit(0);
  }
  foreach ($libraries as $library) {
    $library->userBooks()->delete();
    $library->activityLogs()->delete();
    if ($library->stats) {
      $library->stats()->delete();
    }
    $library->delete();
    fwrite(STDOUT, "Eliminata libreria {$library->id} (UUID {$library->calibre_library_id})\n");
  }
?>
PHP
}

echo "UUID Calibre locale: $CALIBRE_ID"
cleanup_libraries

SETUP_OUT=$(
  DISCOVERY_URL="$DISCOVERY_URL" \
  TEST_USER_EMAIL="$TEST_USER_EMAIL" \
  TEST_USER_PASSWORD="$TEST_USER_PASSWORD" \
  CALIBRE_LIBRARY_ID="$CALIBRE_ID" \
  CALIMOB_LIBRARY_NAME="Headless Plugin $(date -u +%Y%m%d%H%M%S)" \
  "$SCRIPT_DIR/headless_setup_library.sh"
)

CALIMOB_SERVER_LIBRARY_ID=$(printf '%s\n' "$SETUP_OUT" | awk -F= '/^CALIMOB_LIBRARY_ID=/ {print $2; exit}')
if [[ -z "$CALIMOB_SERVER_LIBRARY_ID" ]]; then
  echo "Errore: impossibile ottenere CALIMOB_LIBRARY_ID dalla configurazione headless" >&2
  echo "$SETUP_OUT" >&2
  exit 1
fi

API_URL=$(discover_api_url)
REST_TOKEN=$(login "$API_URL")

CONFIG_PATH="${CALIMOB_CONFIG_JSON:-$DEFAULT_CONFIG_PATH}"
mkdir -p "$(dirname "$CONFIG_PATH")"

cat <<EOF >"$CONFIG_PATH"
{
  "Caliweb": {
    "discoveryCache": {},
    "discoveryUrl": "$DISCOVERY_URL",
    "restEndpoint": "$API_URL",
    "restToken": "$REST_TOKEN",
    "restUsername": "",
    "restPassword": "",
    "debugApiLogs": true,
    "uploadTimeout": 120,
    "httpTimeout": 30
  },
  "LibraryMappings": {
    "$CALIBRE_ID": {
      "syncEnabled": true,
      "calibreLibraryId": "$CALIBRE_ID",
      "calimobLibraryId": $CALIMOB_SERVER_LIBRARY_ID,
      "calimobLibraryName": "Headless Plugin Library"
    }
  },
  "BookUuidCache": {}
}
EOF

echo "Configurazione scritta in $CONFIG_PATH"
echo
cat <<EOF
Ambiente pronto. Esporta queste variabili e lancia i test headless (calibre-debug o gli script in tests/plugin/integration):

  export CALIMOB_DISCOVERY_URL="$DISCOVERY_URL"
  export CALIMOB_FORCE_API_URL="${FORCE_API_URL}"
  export TEST_USER_EMAIL="$TEST_USER_EMAIL"
  export TEST_USER_PASSWORD="$TEST_USER_PASSWORD"
  export CALIMOB_LIBRARY_PATH="$CALIBRE_LIBRARY_PATH"
  export CALIBRE_LIBRARY_ID="$CALIBRE_ID"
  export CALIMOB_LIBRARY_ID="$CALIBRE_ID"
  export CALIMOB_SERVER_LIBRARY_ID="$CALIMOB_SERVER_LIBRARY_ID"
  export CALIMOB_CONFIG_JSON="$CONFIG_PATH"

Poi lancia /Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/test_plugin_integration.py o uno degli script headless (headless_sync_smoke.sh, headless_e2e.py, headless_deep_suite.sh, ecc.).
EOF
