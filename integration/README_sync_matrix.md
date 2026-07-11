# Sync Convergence Matrix — real device(s) ↔ local CaliWeb server

> **If you are an LLM or a dev picking this up cold: read this whole file first.**
> It is the single source of truth for the sync integration harness. Every file
> below also carries an inline header explaining its own role.

## What this is (and why)

We chased a long tail of Merkle **convergence** bugs (placeholder covers,
`sha256:`-prefixed cover hashes, ghost files, §13 effective-lm). Unit tests pass
but only a **real device against a real server** proves convergence end-to-end.
This harness stands up a throwaway **local CaliWeb server in Docker** (PostgreSQL
17 — the prod engine), seeds the exact **edge-case states** that broke
convergence, points one or more **Android emulators** (calimob) at it, syncs, and
asserts:

| Dimension | What it checks |
|---|---|
| **Convergence** | after sync, `client Merkle root == server Merkle root` per dimension (meta/covers/files) → 0 candidates |
| **Concurrency** | 2 devices, same library, write different books, sync → final state = union, no lost writes |
| **Multi-user separation** | user A never sees user B's books/Merkle (logical isolation) |
| **Multi-user load** | N concurrent syncs → no 500s / corruption |

## The pieces (all committed, all self-documented)

| File | Role |
|---|---|
| `html/docker-compose.test.yml` | the local server: `postgres` (pg17) + `app` **built from the local html** (runs our code, not the prod image). PG host `5433`, app host `8081`. |
| `html/.env.test-server` | the app's env inside the compose (DB → `postgres` service, `QUEUE=sync` so Merkle rebuild is inline/deterministic). |
| `html/phpunit.testserver.xml` | phpunit bound EXPLICITLY to the docker PG (no `.env` override-trap) — runs server unit/feature tests against the prod engine. |
| `html/database/seeders/SyncMatrixSeeder.php` | **parameterized** edge-case seed. The matrix is the `SCENARIOS` const — add a row, it flows everywhere. |
| `tests/integration/test_sync_convergence_matrix.py` | the pytest conductor (Phase 1+; orchestrates seed → drive emulator → assert). |
| `scripts/up-test-server.sh` / `reset-test-server.sh` | bring up / reset+seed the server. |

## Reachability (memorise this)

```
host      → PG          127.0.0.1:5433      (seeding, phpunit)
host      → app         http://localhost:8081
emulator  → app         http://10.0.2.2:8081   (10.0.2.2 = host, from the AVD)
app       → PG          postgres:5432          (compose network)
```

## Quick start

```bash
# Recommended: menu 60 brings up PG+app, resets, runs pytest.
./scripts/upTests --menu=60

# Manual equivalent:
scripts/up-test-server.sh              # PG + app (NOT --pg-only for HTTP/emulator phases)
scripts/reset-test-server.sh           # migrate:fresh + SyncMatrixSeeder on caliweb_test
cd tests/integration && python3 -m pytest test_sync_matrix_registry_federation.py \
  test_sync_convergence_matrix.py test_plugin_sync_matrix_headless.py -v
```

**Do not** substitute `php artisan serve` on the host for the docker `app` service: CLI
`--env=test-server` and HTTP bootstrap load different env files, so Sanctum tokens minted
from the host often 401 against a host-served API. The app container uses `.env.test-server`
and talks to `postgres:5432` on the compose network.

`--pg-only` is only for seeding / `phpunit.testserver.xml` without building the app image:

```bash
cd html

# PG only (no app on :8081)
docker compose -f docker-compose.test.yml up -d postgres
DB_HOST=127.0.0.1 DB_PORT=5433 DB_DATABASE=caliweb_test \
  php artisan migrate --force --env=test-server

# Seed the edge-case matrix
DB_HOST=127.0.0.1 DB_PORT=5433 DB_DATABASE=caliweb_test \
  php artisan db:seed --class=SyncMatrixSeeder --force --env=test-server

# Verify the server fix on the real engine (PG)
php artisan test -c phpunit.testserver.xml tests/Unit/MerkleCoverHashPrefixNormalizationTest.php

# Reset everything (drop the volume)
docker compose -f docker-compose.test.yml down -v
```

## Databases in the docker PG

- `caliweb_test` — the **integration** DB (the app/emulator talk to this; seeded by `SyncMatrixSeeder`).
- `test_caliweb` — the **phpunit** DB (`RefreshDatabase` manages it; must be `test_`-prefixed per `tests/CreatesApplication.php`'s safety guard).

## How to add an edge-case scenario (the whole point of "parameterized")

Edit `SyncMatrixSeeder::SCENARIOS` — add one row with a stable `uuid`, `case_id`,
the server-side fields (`has_cover`, `cover_original_hash`, optional `files` for
`books_files`), and `edge`/`expect` notes. For each `file_hash` in `files`, the seeder
also upserts a matching `files_store` row (`ensureFilesStoreRow`) so `is_uploaded`
stays true in sync payloads and FILES Merkle leaves use the real tail hash. Re-export
the registry JSON. It is then seeded and asserted automatically. **Never randomise the uuid**
— the uuid is the book's identity (see the project memory on title+uuid).

## The convergence assertion (deterministic, not logcat-grep)

After the device syncs, compare the **Merkle roots**: the server exposes its root
via the library-hash endpoint; the client computes its own. `meta == meta`,
`covers == covers`, `files == files` ⇒ converged. (The earlier device debugging
used the `CoverConv` logcat lines — kept as a diagnostic, but the root compare is
the assertion.)

## Phases (build order)

- **Phase 0 (done)**: local server + parameterized seeder + PG-verified fix + this doc + `upTests` wiring.
- **Phase 1 (done)**: single-device convergence. `1a` server-side leaf == raw-client (H4 guard, no emulator); `1b` real emulator adopts the server cover (`has_cover 0→1`) and re-sync is idempotent.
- **Phase 2 (done)**: concurrency, two emulators, same user + library — `2a` + `2b` below.
- **Phase 3 (done)**: multi-user — `3a` logical separation + `3b` concurrent load — HTTP-driven (no emulator).
- **Phase 4 (done)**: deletion data-safety e2e — `4a` an explicit delete (`d` list) tombstones on the live PG server, but a partial/restored inventory (a client that omits books) never deletes the omitted ones (absence ≠ delete). Complements the phpunit Level-A `DeletionSubscriptionSafetyTest` (downgrade/over-quota never delete) and the plugin Level-B `test_mass_deletion_guard` (absence→delete guard: suppress headless / confirm manual).
- **Phase 5 (done)**: multi-client cover/file SETTINGS safety e2e — `5a` metadata-only HTTP client; **`5b` SET-06** Calibre-full then metadata-only two-leg sequence on RLY-META (`metadata_only_safe`). Complements phpunit `CoverFileSettingsSafetyTest` and Phase 6 device path.
- **Phase 6 (implemented)**: real app sync must NOT drop a plugin-uploaded `books_files` row (`test_phase6_real_device_sync_keeps_plugin_uploaded_file`). Requires one emulator (`SCENARIO=adopt` default).
- **Phase 7 (done, verified 2026-07-10)**: file-dimension convergence — `7a` server FILES Merkle leaves == RAW client (no emulator); `7b` two-sync FIL-GHOST-01 / MRK-06 skeleton over HTTP; **`7c` real emulator** (`SCENARIO=mrk06`) — two syncs, `FileSigCache` remote tail, files Merkle branches match; **`7d` FIL-OK** (`SCENARIO=filok`) — local `converged.epub` bytes preserved on disk (not by-reference ghost). Seeder plants `books_files` **and** matching `files_store` rows (without `files_store`, server Merkle orphans tail hashes). Registry JSON via `scripts/export-sync-matrix-registry.php`. Shared assertions: `sync_matrix_verify.py`. Dart: `lib/util/files_merkle.dart`. Calimob fixes: live-DB overlay on server updates, flat `has_cover` in `ChangeItem`, pre-push cover/file adopt.
- **Phase 8 (implemented)**: 3-way MRK-06 — plugin headless 2-sync on `1bed2112`, then device `SCENARIO=mrk06`; server `books_files` must survive both legs. Requires emulator + **calibre-debug** (see Sprint 5 below).
- **Phase 9 (implemented)**: large metadata pull — server seeds **N=100** real books from `tests/plugin/fixtures/CalibreLargeLocal/metadata.db` on library `ccccaaaa-0000-4000-8000-000000000050` (separate from the 6-book edge matrix). **`9a`** (HTTP): metadata Merkle leaves match `books_hash_v2`, discover lists full pool. **`9b`** (device, `SCENARIO=large_pull`): empty client pulls all 100, metadata Merkle converges, second sync no-op. Reuses `CalibreFixtureMetadataReader` + existing conductor/Dart harness.

### Verification status (2026-07-10)

| Phase | Code | Last known green |
|---|---|---|
| 0–1, 3–5, 7 | ✅ | 7c/7d verified after `files_store` seeder + calimob live-DB fixes |
| 2 | ✅ | needs **two** emulators (`5554` + `5556`) — skips if either missing |
| 6 | ✅ | needs one emulator |
| 8 | ✅ | needs emulator + calibre-debug + plugin headless script |
| 9 | ✅ | needs one emulator; metadata-only (no EPUB/cover bytes in fixture) |

A full menu **60** run (federation + all conductor phases + plugin headless) has not been re-run end-to-end since the 7c/7d fix landed.

## Sprint 4 — Flutter v5 `case_id` federation (48/48)

Every test in `calimob/test/sync/web_sync_service_v5_test.dart` carries a `// case_id:` comment
linked to `v5_web_sync_test_case_ids.dart`. CI gate:

```bash
cd calimob && flutter test test/sync/v5_web_sync_case_coverage_test.dart
```

Export after registry edits:

```bash
cd calimob && dart run tool/export_v5_case_registry.dart
```

## Sprint 5 — plugin federation + 3-way MRK-06

Plugin behavioral rows (`A01`→`MRK-01`, `D01`→`MRK-05`, headless→`MRK-06`) are
exported to `plugin_v5_case_registry.json`:

```bash
python3 scripts/export-plugin-v5-case-registry.py
# (also runs from reset-test-server.sh)
```

Federation gate (fast, no emulator):

```bash
cd tests/integration && python3 -m pytest test_sync_matrix_registry_federation.py -v
```

**Phase 8** (`test_phase8_3way_plugin_emulator_mrk06`): plugin headless 2-sync on
`1bed2112`, then device `SCENARIO=mrk06` — server `books_files` must survive both legs.
Not yet verified in a single menu-60 run after Phase 7 landed; infra-dependent (emulator +
calibre-debug).

`scripts/upTests --menu=60` runs federation + full conductor + plugin headless (when
calibre-debug + docker PG are available).

## Registry export (`case_id` federation)

`SyncMatrixSeeder::SCENARIOS` is the single source of truth. Each row has a stable
`case_id` (and optional `case_ids` aliases) linking to
`docs/server/sync/SYNC_V5_STATE_MATRIX.md`. After seeding:

```bash
php scripts/export-sync-matrix-registry.php
# → tests/integration/fixtures/sync_matrix_registry.json
```

Pytest loads this file for `EXPECTED_SCENARIOS` and file assertions (Phase 0/7).

### Flutter v5 `case_id` registry (Sprint 3)

`calimob/test/sync/v5_case_registry.dart` maps matrix `case_id` → Flutter test files.
Export JSON:

```bash
cd calimob && dart run tool/export_v5_case_registry.dart
# → tests/integration/fixtures/flutter_v5_case_registry.json
```

### Plugin headless matrix (Sprint 3)

`sync_calimob/tests/plugin/integration/headless_sync_matrix_mrk06.sh` — plugin 2-sync
against docker test server with Calibre fixture built from `sync_matrix_registry.json`.
Pytest: `test_plugin_sync_matrix_headless.py`.

## Deletion / subscription / settings data-safety matrix (cross-layer)

| Layer | Subscription limits | Deletion + cover/file-settings safety |
|---|---|---|
| Server (phpunit/PG) | `SyncV5SubscriptionLimitsTest` (9) | `DeletionSubscriptionSafetyTest` (3) + `CoverFileSettingsSafetyTest` (4) + PG-boolean regressions (2) |
| Plugin (py unit) | 403 → warn+stop (no delete) | `test_mass_deletion_guard` (11): absence→delete guard |
| App (calimob) | 403 → abort sync (no delete) | unit `test/sync/deletion_settings_safety_test.dart`: payload `d` from explicit flag only, no-cover/no-file → null hashes (never a delete) |
| e2e (HTTP/PG) | — | Phase 4a (deletion) + Phase 5a (multi-client settings) |
| Device (emulator+PG) | — | Phase 6: real app sync keeps the plugin's uploaded file/cover |

### Phase 3 — multi-user (how it works)

`SyncMatrixSeeder` also plants a SECOND user B (`sync-matrix-b@test.com`, own
library `USER_B_LIBRARY_UUID`, distinct book uuids). Both tests are pure API
(stdlib `urllib`, no emulator):

**`test_phase3a_multiuser_logical_separation`** — each user sees only their own
library's `total_books`; user B querying A's library (Merkle root) sees 0 books,
and a sync B runs against A's `library_uuid` returns NONE of A's books in
`updates_for_client` (the strongest cross-user read-leak check). Symmetric for A↔B.

**`test_phase3b_concurrent_load_no_500s_no_corruption`** — fires N=30 concurrent
sync requests (ThreadPool, mixed A/B) → asserts every response is 200 (no 500s),
then no corruption: each user's seeded book count is intact and the Merkle tree
still rebuilds for both libraries.

### Phase 2 — concurrency (how it works)

ONE compiled calimob APK serves every phase; the `SCENARIO` is chosen by
`--dart-define` (`integration_test/sync_matrix_convergence_test.dart`):

| `SCENARIO` | divergent local state | device-side assertion |
|---|---|---|
| `adopt` (1b) | target `has_cover=0`, old lm | adopts server cover → `has_cover=1`, re-sync idempotent |
| `push` (2a) | target title changed + `app_modified=NEW_LM_MS` (newer) → PUSH | push sync + idempotent re-sync |
| `conflict` (2b) | same book, both newer, different titles | converges to `EXPECTED_WINNER_TITLE` (loser adopts) |
| `mrk06` (7c) | full 6-book matrix; target ghost file/cover | two syncs → files Merkle match |
| `filok` (7d) | full matrix + local EPUB bytes for FIL-OK | converged.epub preserved on disk |
| `large_pull` (9b) | **empty** local library | pull 100 real-metadata books; metadata Merkle match; 2nd sync noop |

**Barrier.** Two devices must hit `sync()` together. The conductor measures each
emulator's clock skew (`adb shell date`) and passes a per-device `GO_AT_MS` (a
host wall-clock instant + that device's skew). Each test busy-waits to `GO_AT_MS`
before `sync()`, so both fire within ~1s. Builds are **staggered** (so two
`flutter test` don't fight over `build/`), but the *sync* is synchronized.

**`test_phase2a_disjoint_concurrent_push`** — A writes book P (`no_cover`), B
writes book Q (`converged_normal`), concurrently. Asserts: (1) **no lost update**
— both titles present on the server; (2) **no lost invalidation** — any Merkle
root left `is_stale=false` after the concurrent pushes must be unchanged by a
fresh rebuild (else a push's invalidation was dropped → clients would diverge).

**`test_phase2b_same_book_conflict_lww`** — both devices rewrite the SAME book
with different titles/lm. The higher-lm writer is the winner (`NEW_LM_MS` gap, so
the outcome is push-order-agnostic). Asserts: server elects the winner
deterministically, and **both** device processes exit 0 — i.e. each converged to
the winner (the loser adopted it; no ping-pong).

Two emulators are required (`emulator-5554` + `emulator-5556`, override via
`ANDROID_EMULATOR_A` / `ANDROID_EMULATOR_B`); the tests skip if either is absent.

## CI / upTests

Wired into `scripts/upTests` (menu **60** — Sync-Matrix): brings up **PG + app**
(`up-test-server.sh`, not `--pg-only`), seeds via `reset-test-server.sh`, then runs
federation + conductor + plugin headless. See the `case "Sync-Matrix")` block there.

For PHPUnit against the docker PG only (no app image), use `phpunit.testserver.xml` —
it binds explicitly to `127.0.0.1:5433` and avoids the `.env` override trap documented
in `docs/agent-guides/testing.md`.
