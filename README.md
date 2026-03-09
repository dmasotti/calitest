# Test Guide (Single Source of Truth)

This document consolidates all testing docs. Any other test docs now point here.

## 1) Test Layout

- `tests/server/` → Laravel/PHP server tests (PHPUnit) + shell sync scripts
- `tests/plugin/` → Calibre plugin tests (pytest + calibre-debug integration)
- `tests/docker/` → Docker services tests (pytest)
  - `tests/docker/rag-comics/` → RAG Comics service (91 test)
- `tests/opds/` → OPDS bash suites
- `tests/plugin/fixtures/CalibreTestLocal` → Calibre test library (contains `metadata.db`)
- `tests/run_all_tests.sh` → all-in-one runner (includes plugin V5)
- `tests/run_plugin_tests.sh` → plugin runner (unit + integration + V5)

## 2) Quick Start

### Run everything (recommended)

```bash
export DISCOVERY_URL="http://caliserver.test"
export TEST_USER_EMAIL="dmasotti+test1@gmail.com"
export TEST_USER_PASSWORD="firstsecret"

./tests/run_all_tests.sh
```

### Server (PHPUnit) only

```bash
set -a; source html/.env; set +a
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server
```

### Plugin (pytest) only

```bash
python3 -m pytest -q tests/plugin/unit
python3 -m pytest -q tests/plugin/integration
```

### Plugin V5 integration (calibre-debug)

```bash
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/v5/test_sync_v5_integration.py --all
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/v5/test_sync_v5_advanced.py --all
```

### OPDS

```bash
HOST="https://your-server.com" \
USER="user@example.com" \
PASS="your-password" \
./tests/opds/opds_comprehensive_test.sh
```

## 3) Environment Variables

### Common (server scripts + OPDS)

| Variable | Description | Required |
|---|---|---|
| `DISCOVERY_URL` | Server base URL | Yes |
| `TEST_USER_EMAIL` | Test user email | Yes |
| `TEST_USER_PASSWORD` | Test user password | Yes |
| `VERBOSE` | Verbose output (0/1) | No |

### Plugin (pytest + calibre-debug)

| Variable | Description | Default |
|---|---|---|
| `CALIMOB_TEST_LIBRARY_PATH` | Calibre library path | `tests/plugin/fixtures/CalibreTestLocal` |
| `CALIMOB_TEST_LIBRARY_UUID` | Library UUID | `1685fd4f-054e-4451-9df8-119c27fc1289` |
| `CALIMOB_TEST_CALIMOB_LIB_ID` | Calimob library id | `1` |
| `CALIMOB_TEST_API_URL` | Server API base | `https://coral-shark-984693.hostingersite.com/api` |
| `CALIMOB_TEST_TOKEN` | API token | (set locally) |
| `CALIBRE_DEBUG` | Calibre debug executable | `/Applications/calibre.app/Contents/MacOS/calibre-debug` |

## 4) Server Tests (PHPUnit + scripts)

### PHPUnit suite

```bash
set -a; source html/.env; set +a
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server
```

Run a single file:

```bash
set -a; source html/.env; set +a
./html/vendor/bin/phpunit -c phpunit.xml tests/server/SubscriptionApiTest.php

# Boundary server<->services (feature, mocked + edge cases)
cd html && ./vendor/bin/phpunit tests/Feature/ServerServiceBoundaryCoverageTest.php tests/Feature/ServerServiceBoundaryEdgeCasesTest.php
```

Run a single test:

```bash
set -a; source html/.env; set +a
./html/vendor/bin/phpunit -c phpunit.xml --filter test_get_subscription_status_returns_correct_data
```

### Remote server execution (optional)

```bash
./scripts/upTest --testsuite=Server
```

### Shell sync scripts

```bash
DISCOVERY_URL="https://your-server.com" \
TEST_USER_EMAIL="user@example.com" \
TEST_USER_PASSWORD="your-password" \
./tests/server/sync_comprehensive_test.sh
```

Other scripts:
- `tests/server/sync_protocol_contract_test.sh`
- `tests/server/sync_pull_post_inventory_test.sh`
- `tests/server/test_legacy_book.sh`
- `tests/server/docker_services_boundary_e2e.sh` (live E2E Laravel <-> Docker services)
- `tests/server/docker_services_boundary_e2e_paid.sh` (live E2E a pagamento, fake=false, conferma esplicita)
- `tests/server/presigned_upload_e2e.sh` (live E2E presigned upload singolo provider)
- `tests/server/presigned_upload_e2e_provider_matrix.sh` (live matrix R2/S3 nello stesso run)
- `tests/server/presigned_upload_soak.sh` (carico concorrente start/put/complete/verify)
- `scripts/run_boundary_dual_db_tests.sh` (parity run SQLite + MySQL per boundary suite)
- `scripts/run_hash_views_dual_db_tests.sh` (parity run SQLite + MySQL per hash views metadata)

Live boundary E2E example:

```bash
CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
CALIMOB_E2E_TOKEN="<superadmin-or-user-token>" \
./tests/server/docker_services_boundary_e2e.sh
```

Default behavior:
- `CALIMOB_E2E_FAKE_INDEXING=true` (default): indexing test in fake mode
- `CALIMOB_E2E_TEXT_FORMAT=AUTO` (default): usa EPUB se disponibile, altrimenti PDF
- `CALIMOB_E2E_STRICT_INDEXING=false` (default): se `true`, richiede `indexing_logs.status=success`
- `CALIMOB_E2E_COMICS_INDEXING=false` (default): se `true`, esegue anche `/chat/index` su comics

Force one text format:

```bash
CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
CALIMOB_E2E_TOKEN="<superadmin-or-user-token>" \
CALIMOB_E2E_TEXT_FORMAT="PDF" \
CALIMOB_E2E_REQUIRE_TEXT_FORMAT="true" \
CALIMOB_E2E_STRICT_INDEXING="true" \
./tests/server/docker_services_boundary_e2e.sh
```

Paid E2E (real indexing, fake=false) for both EPUB and PDF, with explicit confirmation prompt:

```bash
CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
CALIMOB_E2E_TOKEN="<superadmin-or-user-token>" \
./tests/server/docker_services_boundary_e2e_paid.sh
```

Boundary parity on both DB backends:

```bash
./scripts/run_boundary_dual_db_tests.sh
```

Hash-view parity on both DB backends:

```bash
./scripts/run_hash_views_dual_db_tests.sh
```

## 5) Plugin Tests (pytest)

### Unit

```bash
python3 -m pytest -q tests/plugin/unit
```

### Integration (Python)

```bash
python3 -m pytest -q tests/plugin/integration
```

### Plugin V5 integration (calibre-debug)

These tests use the local Calibre library in `tests/plugin/fixtures/CalibreTestLocal`.

```bash
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/v5/test_sync_v5_integration.py --all
/Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/v5/test_sync_v5_advanced.py --all
```

### Docker services (pytest)

```bash
cd tests/docker/rag-comics
./run_tests.sh unit
```

See `tests/docker/README.md` for details.

### Local-dev helper scripts

Helpers live in `sync_calimob/local-dev/` and now default to:
`tests/plugin/fixtures/CalibreTestLocal`.

## 6) OPDS Tests

```bash
HOST="https://your-server.com" \
USER="user@example.com" \
PASS="your-password" \
./tests/opds/opds_comprehensive_test.sh
```

## 7) Coverage

### Plugin (pytest)

```bash
python3 -m pytest --cov=sync_calimob --cov-report=term
python3 -m pytest --cov=sync_calimob --cov-report=html
```

### Server (PHPUnit)

```bash
set -a; source html/.env; set +a
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server --coverage
./html/vendor/bin/phpunit -c phpunit.xml --testsuite=Server --coverage-html=coverage/server
```

### Sonar coverage scripts

```bash
# 1) Copy and fill credentials (once)
cp scripts/.sonar.env.example scripts/.sonar.env

# 2) Server coverage + Sonar scan
./scripts/run_server_coverage_and_sonar.sh

# 3) Plugin unit coverage + Sonar scan
./scripts/run_plugin_coverage_and_sonar.sh
```

## 8) Test Accounts

Default test users:
- `dmasotti+test1@gmail.com` / `firstsecret`
- `dmasotti+test2@gmail.com` / `secondsecret`

Verify/create:

```bash
cd html
set -a; source .env; set +a
php artisan user:info dmasotti+test1@gmail.com
php artisan user:info dmasotti+test2@gmail.com

php artisan user:create dmasotti+test1@gmail.com --password=firstsecret
php artisan user:create dmasotti+test2@gmail.com --password=secondsecret
```

## 9) Troubleshooting

- **401**: check user/password/token and that the user exists.
- **404**: verify endpoint and routes.
- **500**: check Laravel logs and DB schema.
- **OPDS**: app-password can be used for Basic Auth (username = email).
- **Calibre**: ensure Full Disk Access for `calibre-debug` and that the fixture library is readable.

## 10) CI Example

```yaml
name: Run Tests
on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run Test Suite
        env:
          DISCOVERY_URL: ${{ secrets.TEST_SERVER_URL }}
          TEST_USER_EMAIL: ${{ secrets.TEST_USER_EMAIL }}
          TEST_USER_PASSWORD: ${{ secrets.TEST_USER_PASSWORD }}
        run: |
          ./tests/run_all_tests.sh
```

## 11) Notes

- Tests live in project root `tests/` (not deployed).
- Use only test accounts and isolated data.
- Calibre fixture library is in-repo: `tests/plugin/fixtures/CalibreTestLocal`.

## 12) Sync Protocol Coverage Matrix (v5)

Reference docs:
- `docs/server/sync/PROTOCOLLO_SYNC_UNIFICATO.md`
- `docs/server/sync/SYNC_V5_PROTOCOL.md`

Protocol requirement -> test coverage:
- Request formats (`client_books` compact + extended) -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Request contract validation errors (422 on invalid scalar/range types) -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Client deletions (`client_books.d` -> `deleted_confirmed`, no upload request) -> `tests/server/SyncV5ProtocolCoverageTest.php`, `tests/server/SyncV5SemanticsTest.php`
- Client delete list normalization + first-chunk-only processing (`d` with strings/objects/duplicates; no reprocessing at `client_cursor>0`) -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Client delete compatibility with single-string `d` payload -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Delete precedence on concurrent payload intent (same UUID in `b` and `d` -> delete wins) -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Cursor format/composite pagination (`timestamp:id`, no cursor stalls) -> `tests/server/SyncV5ProtocolCoverageTest.php`, `tests/server/SyncV5ClientBatchingTest.php`, `tests/server/SyncCompositeCursorTest.php`
- Cursor malformed input resilience (no 500; valid next cursor) -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Hash-aware skip/update behavior (`metadata/cover/files`) -> `tests/server/SyncV5HashSkipServerUpdatesTest.php`, `tests/server/SyncV5SemanticsTest.php`
- Hash normalization robustness (`sha256:` prefixes, unordered files list) -> `tests/server/SyncV5ProtocolCoverageTest.php`
- Pre-sliced client chunking (`client_cursor/client_batch_size`) -> `tests/server/SyncV5ClientBatchingTest.php`
- Gzip request/response compatibility -> `html/tests/Feature/DecodeGzipJsonRequestMiddlewareTest.php`, `tests/server/GzipApiResponseMiddlewareTest.php`, `tests/server/SyncV5ProtocolCoverageTest.php`
- UUID-only identity and ID reconciliation semantics -> `html/tests/Feature/SyncIdConformanceTest.php`, `html/tests/Feature/SyncEntityIdReconciliationTest.php`
- Plugin-side v5 cache/payload logic (`m/c/f`, cursor, resume) -> `sync_calimob/tests/plugin/unit/test_sync_worker_helpers.py`, `sync_calimob/tests/plugin/integration/test_unified_batch_sync.py`

Minimum CI gate for sync changes:
```bash
set -a && source html/.env && set +a
./html/vendor/bin/phpunit -c phpunit.xml \
  tests/server/SyncV5ProtocolCoverageTest.php \
  tests/server/SyncV5ClientBatchingTest.php \
  tests/server/SyncV5HashSkipServerUpdatesTest.php \
  tests/server/SyncV5SemanticsTest.php

pytest -q sync_calimob/tests/plugin/unit/test_sync_worker_helpers.py
```
