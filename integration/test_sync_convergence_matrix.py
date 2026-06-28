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

import hashlib
import os
import shutil
import subprocess

import pytest

HTML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "html",
)
LIBRARY_UUID = "42a0c170-23cf-11f1-93ec-391510e4e1b1"  # SyncMatrixSeeder default lib

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
# PHASE 1a — server-side convergence (the protocol, on the REAL running server)
#
# Proves: after a Merkle rebuild, the server's COVER leaf for each seeded book
# equals the leaf a RAW client (the Calibre plugin / calimob) computes —
# SHA256( join(sorted( SHA256("uuid|has_cover|RAW_hash") )) ). The 'cover_prefixed'
# scenario (cover_original_hash stored as 'sha256:…') is the H4 regression guard:
# without the leaf-strip fix the server would produce SHA256(…|1|sha256:…) and the
# raw client could NEVER match → covers never converge. This needs NO emulator —
# it is the protocol-level convergence proof on the running PG server.
# ─────────────────────────────────────────────────────────────────────────────

def _strip_prefix(h: str | None) -> str:
    if not h:
        return ""
    return h[7:] if h.startswith("sha256:") else h


def _client_cover_item_hash(uuid: str, has_cover: bool, cover_hash: str | None) -> str:
    """The per-book cover item_hash a RAW client sends: SHA256(uuid|hc|raw)."""
    hc = "1" if has_cover else "0"
    return hashlib.sha256(
        f"{uuid}|{hc}|{_strip_prefix(cover_hash)}".encode()
    ).hexdigest()


def _leaf_id(uuid: str) -> int:
    return int(uuid.replace("-", "").lower()[:2], 16)


@pytest.fixture(scope="module")
def rebuilt_server():
    """Rebuild the seeded library's Merkle once on the docker PG (host artisan)."""
    env = {**os.environ, "DB_HOST": "127.0.0.1", "DB_PORT": "5433",
           "DB_DATABASE": "caliweb_test", "DB_USERNAME": "testuser",
           "DB_PASSWORD": "testpass", "DB_CONNECTION": "pgsql"}
    subprocess.run(
        ["php", "artisan", "sync:rebuild-merkle", LIBRARY_UUID, "--env=test-server"],
        cwd=HTML_DIR, env=env, check=True, capture_output=True, text=True,
    )


def test_phase1a_server_cover_leaves_match_raw_client(rebuilt_server):
    """For every COVER leaf bucket, the server's leaf_hash == the leaf a RAW
    client computes from the SAME books. Drives the real seeded server; fails
    if the sha256: prefix ever leaks back into the leaf (H4 regression)."""
    # Read what was actually seeded (authoritative), grouped into leaf buckets.
    rows = _psql(
        "SELECT uuid, has_cover, COALESCE(cover_original_hash,'') FROM books "
        f"WHERE uuid IN ({','.join(repr(u) for u in EXPECTED_SCENARIOS.values())})"
    )
    buckets: dict[int, list[str]] = {}
    for line in rows.splitlines():
        uuid, has_cover, cover_hash = line.split("\t")
        hc = has_cover in ("t", "true", "1")
        buckets.setdefault(_leaf_id(uuid), []).append(
            _client_cover_item_hash(uuid, hc, cover_hash or None)
        )

    assert buckets, "no seeded books — run scripts/reset-test-server.sh"
    for leaf_id, items in buckets.items():
        expected = hashlib.sha256("".join(sorted(items)).encode()).hexdigest()
        server_leaf = _psql(
            "SELECT leaf_hash FROM sync_merkle_leaves "
            f"WHERE dimension='covers' AND leaf_id={leaf_id}"
        )
        assert server_leaf == expected, (
            f"COVER leaf {leaf_id}: server={server_leaf[:16]}… != raw-client "
            f"{expected[:16]}… — the cover_original_hash prefix is leaking into "
            f"the leaf (H4 regression)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 1b — single-device convergence on a REAL emulator (TODO: wire calimob)
# ─────────────────────────────────────────────────────────────────────────────

CALIMOB_DIR = os.environ.get(
    "CALIMOB_DIR",
    "/Users/macbookpro/Coding/flutter_25/Personal/calimob",
)
EMULATOR = os.environ.get("ANDROID_EMULATOR", "emulator-5554")


def _emulator_connected() -> bool:
    if not shutil.which("adb"):
        return False
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
    return any(line.startswith(EMULATOR) and "device" in line
               for line in out.splitlines())


@pytest.mark.skipif(
    not _emulator_connected() or not os.path.isdir(CALIMOB_DIR),
    reason=f"emulator {EMULATOR} not connected or CALIMOB_DIR missing.",
)
def test_phase1b_emulator_single_device_convergence():
    """REAL device: mint a Sanctum token, point calimob (emulator → the local
    server) at the seeded library with a DIVERGENT local state, run a sync, and
    assert the device ADOPTS the server cover and converges. Drives the calimob
    integration test integration_test/sync_matrix_convergence_test.dart.

    The 'cover_prefixed' scenario is the H4 regression guard end-to-end on a real
    device against the real PG server. Headless auth (bearer token) — no browser."""
    env = {**os.environ, "DB_HOST": "127.0.0.1", "DB_PORT": "5433",
           "DB_DATABASE": "caliweb_test", "DB_USERNAME": "testuser",
           "DB_PASSWORD": "testpass", "DB_CONNECTION": "pgsql"}
    token = subprocess.run(
        ["php", "artisan", "sync:test-token", "sync-matrix@test.com", "--env=test-server"],
        cwd=HTML_DIR, env=env, capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1]
    assert token and "|" in token, "failed to mint a Sanctum token"

    r = subprocess.run(
        ["flutter", "test",
         "integration_test/sync_matrix_convergence_test.dart",
         "-d", EMULATOR,
         "--dart-define=TEST_SERVER_URL=http://10.0.2.2:8081/api",
         f"--dart-define=TEST_TOKEN={token}"],
        cwd=CALIMOB_DIR, capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        "device convergence test failed:\n"
        + r.stdout[-3000:] + "\n" + r.stderr[-1500:]
    )


# PHASE 2 (concurrency, 2 emulators) and PHASE 3 (multi-user separation + load)
# follow the same parameterized pattern — see README_sync_matrix.md.
