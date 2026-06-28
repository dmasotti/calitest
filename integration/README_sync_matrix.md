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
cd html

# 1) Bring up the server (PG + app built from local source). First build is slow.
docker compose -f docker-compose.test.yml up -d --build

# 2) (PG only, fast — for seeding / server unit tests without the app image)
docker compose -f docker-compose.test.yml up -d postgres
DB_HOST=127.0.0.1 DB_PORT=5433 DB_DATABASE=caliweb_test \
  php artisan migrate --force --env=test-server

# 3) Seed the edge-case matrix
DB_HOST=127.0.0.1 DB_PORT=5433 DB_DATABASE=caliweb_test \
  php artisan db:seed --class=SyncMatrixSeeder --force --env=test-server

# 4) Verify the server fix on the real engine (PG)
php artisan test -c phpunit.testserver.xml tests/Unit/MerkleCoverHashPrefixNormalizationTest.php

# Reset everything (drop the volume)
docker compose -f docker-compose.test.yml down -v
```

## Databases in the docker PG

- `caliweb_test` — the **integration** DB (the app/emulator talk to this; seeded by `SyncMatrixSeeder`).
- `test_caliweb` — the **phpunit** DB (`RefreshDatabase` manages it; must be `test_`-prefixed per `tests/CreatesApplication.php`'s safety guard).

## How to add an edge-case scenario (the whole point of "parameterized")

Edit `SyncMatrixSeeder::SCENARIOS` — add one row with a stable `uuid`, the
server-side fields (`has_cover`, `cover_original_hash`, …), and `edge`/`expect`
notes. It is then seeded and asserted automatically. **Never randomise the uuid**
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

Wired into `scripts/upTests` (menu entry "Sync-Matrix"): it brings up the server,
seeds, and runs the suite. See the `case "Sync-Matrix")` block there.
