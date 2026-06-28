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
- **Phase 1**: single-device convergence over `SCENARIOS` (the bugs we fixed).
- **Phase 2**: concurrency (2 emulators, same library).
- **Phase 3**: multi-user (separation + load), scaled via the same parameterized scenarios.

## CI / upTests

Wired into `scripts/upTests` (menu entry "Sync-Matrix"): it brings up the server,
seeds, and runs the suite. See the `case "Sync-Matrix")` block there.
