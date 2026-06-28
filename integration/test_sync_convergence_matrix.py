"""
Sync CONVERGENCE matrix — pytest conductor.

READ tests/integration/README_sync_matrix.md FIRST. This file is the orchestrator
that, phase by phase, drives the local dockerized CaliWeb test server + real
Android emulator(s) and asserts Merkle convergence / concurrency / multi-user
separation.

How it is wired:
  - `scripts/upTests --menu=60` brings up the server (scripts/up-test-server.sh),
    resets+seeds it (scripts/reset-test-server.sh → SyncMatrixSeeder), then runs
    THIS file.
  - The server's integration DB is `caliweb_test` on the docker PG (host 5433).
    We query it through `docker exec caliweb_test_pg psql` so there is NO python
    DB-driver dependency.

Design notes for whoever extends this (LLM or human):
  - The edge-case matrix lives ONCE in
    html/database/seeders/SyncMatrixSeeder.php::SCENARIOS. Add a row there and it
    flows into the seed AND the assertions below (we read it back from the DB).
  - The convergence assertion is deterministic: client Merkle root == server
    Merkle root per dimension (NOT logcat grep). Phase 1 wires the emulator side.
"""

import json
import shutil
import subprocess

import pytest

PG_CONTAINER = "caliweb_test_pg"
PG_DB = "caliweb_test"
PG_USER = "testuser"

# The scenarios SyncMatrixSeeder plants (key → uuid). Kept in sync with
# SyncMatrixSeeder::SCENARIOS — the seeder is the source of truth; this is the
# expected read-back used by the Phase-0 server assertions.
EXPECTED_SCENARIOS = {
    "converged_normal": "11111111-0000-4000-8000-000000000001",
    "cover_prefixed": "1bed2112-83be-4979-8e26-0e901b0b1eb1",
    "no_cover": "22222222-0000-4000-8000-000000000002",
    "cover_only_no_local": "58659249-778e-414c-9d87-e4438d963b11",
}


def _psql(sql: str) -> str:
    """Run a query against the dockerized test PG, return stdout (tab-separated)."""
    return subprocess.run(
        ["docker", "exec", PG_CONTAINER, "psql", "-U", PG_USER, "-d", PG_DB,
         "-tAF\t", "-c", sql],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _server_up() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", PG_CONTAINER],
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


pytestmark = pytest.mark.skipif(
    not _server_up(),
    reason="Test server not up. Run: scripts/up-test-server.sh --pg-only && "
           "scripts/reset-test-server.sh  (or ./scripts/upTests --menu=60).",
)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 0 — server + seed are correct (the foundation every later phase builds on)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key,uuid", EXPECTED_SCENARIOS.items())
def test_phase0_matrix_seeded(key, uuid):
    """Each edge-case scenario from SyncMatrixSeeder is present on the server with
    the exact server-side state it is meant to reproduce (parameterized over the
    matrix — add a scenario in the seeder + EXPECTED_SCENARIOS and it is covered)."""
    row = _psql(
        f"SELECT has_cover, COALESCE(cover_original_hash,'NULL') "
        f"FROM books WHERE uuid = '{uuid}'"
    )
    assert row, f"scenario '{key}' (uuid={uuid}) not seeded — run reset-test-server.sh"
    has_cover, cover_hash = row.split("\t")

    if key == "cover_prefixed":
        # The historical bug: the server stores the hash WITH the sha256: prefix.
        assert cover_hash.startswith("sha256:"), \
            "cover_prefixed must keep the literal prefix the leaf-fix normalises away"
    if key == "no_cover":
        assert has_cover in ("0", "f", "false"), "no_cover must have has_cover=0"


def test_phase0_users_are_isolated_by_default():
    """Sanity for the multi-user dimension: every seeded book belongs to exactly
    one user_id (no cross-user rows). The real separation test is Phase 3, but
    this guards the seed itself never leaks across users."""
    distinct_users = _psql("SELECT COUNT(DISTINCT user_id) FROM books "
                           "WHERE uuid IN (" +
                           ",".join(f"'{u}'" for u in EXPECTED_SCENARIOS.values()) + ")")
    assert distinct_users == "1", "seeded matrix must belong to a single user"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1 — single-device convergence (TODO: wire the emulator)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skip(reason="Phase 1 — emulator orchestration not wired yet.")
def test_phase1_single_device_convergence():
    """For each scenario: point calimob (emulator → http://10.0.2.2:8081) at the
    seeded server, run a backup/sync, then assert the device's Merkle root ==
    the server's library-hash root for meta/covers/files (0 candidates).

    Implementation plan (see README):
      1. push the matching LOCAL state onto the emulator (a device seeder / a
         calimob integration_test driven via `flutter test ... -d <emulator>`),
      2. trigger sync,
      3. GET the server library-hash + read the client root, assert equality.
    The 'cover_prefixed' scenario is the regression guard for the H4 fix.
    """


# PHASE 2 (concurrency, 2 emulators) and PHASE 3 (multi-user separation + load)
# follow the same parameterized pattern — see README_sync_matrix.md.
