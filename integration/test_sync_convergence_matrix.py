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
import time

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


@pytest.fixture(scope="module", autouse=True)
def _hermetic_seed():
    """Reset+seed the server ONCE before this module runs. Phase 0/1a/1b READ the
    seed without resetting, so without this they'd inherit whatever a prior
    (possibly FAILED) run left behind — e.g. a half-applied concurrent push —
    and break on unexpected data. Phase 2/3 reset again per test as needed.
    (`_reset_and_rebuild` is defined lower in the file; resolved at call time.)"""
    if _server_up():
        _reset_and_rebuild()
    yield


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


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 2 — CONCURRENCY (two real emulators, SAME user + library)
#
# Two devices sync the same CaliWeb library at the SAME instant (a skew-
# compensated GO_AT barrier makes both sync() calls fire together). Two shapes:
#   2a disjoint pushes  — A writes book P, B writes book Q → neither push is lost
#                         and the server's Merkle tree isn't corrupted by the
#                         concurrent rebuilds (a fresh rebuild changes nothing).
#   2b same-book conflict — both rewrite book X differently → LWW (§13 effective-
#                         lm) elects ONE deterministic winner (higher lm) and
#                         BOTH devices converge to it (loser adopts; no ping-pong).
#
# Builds are staggered (different gradle start → no build/ contention) but the
# SYNC is barrier-synchronized, so server-side concurrency is genuinely exercised.
# ─────────────────────────────────────────────────────────────────────────────

EMULATOR_A = os.environ.get("ANDROID_EMULATOR_A",
                            os.environ.get("ANDROID_EMULATOR", "emulator-5554"))
EMULATOR_B = os.environ.get("ANDROID_EMULATOR_B", "emulator-5556")
SCRIPTS_DIR = os.path.join(os.path.dirname(HTML_DIR), "scripts")

UUID_NO_COVER = EXPECTED_SCENARIOS["no_cover"]            # 22222222… (no cover)
UUID_CONVERGED = EXPECTED_SCENARIOS["converged_normal"]   # 11111111… (has cover)
# A writer's edit lm is stamped this far in the future so it beats any wall-clock
# app_modified the other device assigns when it pulls+applies the book mid-round
# (the barrier delays sync by ~window_ms, so a "now" lm would already be stale).
FUTURE_LM_MARGIN_MS = 600_000


def _pg_env() -> dict:
    return {**os.environ, "DB_HOST": "127.0.0.1", "DB_PORT": "5433",
            "DB_DATABASE": "caliweb_test", "DB_USERNAME": "testuser",
            "DB_PASSWORD": "testpass", "DB_CONNECTION": "pgsql"}


def _mint_token(email: str = "sync-matrix@test.com") -> str:
    out = subprocess.run(
        ["php", "artisan", "sync:test-token", email, "--env=test-server"],
        cwd=HTML_DIR, env=_pg_env(), capture_output=True, text=True, check=True,
    ).stdout.strip().splitlines()[-1]
    assert "|" in out, f"failed to mint a Sanctum token for {email}: {out!r}"
    return out


def _reset_and_rebuild():
    """Fresh seed + Merkle rebuild → each Phase-2 test starts from the clean
    matrix (isolates 2a's server mutations from 2b)."""
    subprocess.run([os.path.join(SCRIPTS_DIR, "reset-test-server.sh")],
                   capture_output=True, text=True, check=True)


def _rebuild_merkle(library_uuid: str = LIBRARY_UUID):
    subprocess.run(["php", "artisan", "sync:rebuild-merkle", library_uuid, "--env=test-server"],
                   cwd=HTML_DIR, env=_pg_env(), check=True, capture_output=True, text=True)


def _host_ms() -> int:
    return int(time.time() * 1000)


def _device_epoch_ms(serial: str) -> int:
    """Wall-clock of an emulator in epoch ms (second granularity is fine — the
    sync overlaps for seconds, so ~1s of barrier skew is immaterial)."""
    out = subprocess.run(["adb", "-s", serial, "shell", "date", "+%s"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return int(out) * 1000


def _flutter_async(serial: str, defines: dict) -> subprocess.Popen:
    args = ["flutter", "test", "integration_test/sync_matrix_convergence_test.dart",
            "-d", serial]
    for k, v in defines.items():
        args.append(f"--dart-define={k}={v}")
    return subprocess.Popen(args, cwd=CALIMOB_DIR, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)


def _run_concurrent(token, a_defines, b_defines, window_ms=160_000, stagger_s=45):
    """Launch both device tests so their sync() calls fire at the same host
    wall-clock instant. GO_AT_MS is per-device (host target + that device's clock
    skew). The stagger only offsets the BUILD (avoids gradle build/ contention);
    the barrier keeps the SYNC concurrent. Returns (rc, stdout, stderr) per dev."""
    go_at_host = _host_ms() + window_ms
    skew_a = _device_epoch_ms(EMULATOR_A) - _host_ms()
    skew_b = _device_epoch_ms(EMULATOR_B) - _host_ms()
    common = {"TEST_SERVER_URL": "http://10.0.2.2:8081/api", "TEST_TOKEN": token}
    a = {**common, **a_defines, "DEVICE_LABEL": "A", "GO_AT_MS": go_at_host + skew_a}
    b = {**common, **b_defines, "DEVICE_LABEL": "B", "GO_AT_MS": go_at_host + skew_b}
    pa = _flutter_async(EMULATOR_A, a)
    time.sleep(stagger_s)             # let A clear gradle before B starts building
    pb = _flutter_async(EMULATOR_B, b)
    out_a, err_a = pa.communicate(timeout=600)
    out_b, err_b = pb.communicate(timeout=600)
    # Persist full device stdout for post-mortem (pytest truncates the assert
    # msg). Name by scenario so 2a (push) and 2b (conflict) don't overwrite.
    scn = a_defines.get("SCENARIO", "x")
    for label, out in (("A", out_a), ("B", out_b)):
        try:
            with open(f"/tmp/phase2_device_{scn}_{label}.log", "w") as f:
                f.write(out or "")
        except OSError:
            pass
    return (pa.returncode, out_a, err_a), (pb.returncode, out_b, err_b)


def _both_emulators() -> bool:
    if not shutil.which("adb"):
        return False
    out = subprocess.run(["adb", "devices"], capture_output=True, text=True).stdout
    connected = {ln.split("\t")[0] for ln in out.splitlines() if "\tdevice" in ln}
    return EMULATOR_A in connected and EMULATOR_B in connected


phase2_skip = pytest.mark.skipif(
    not _both_emulators() or not os.path.isdir(CALIMOB_DIR),
    reason=f"Phase 2 needs two emulators ({EMULATOR_A} + {EMULATOR_B}) and CALIMOB_DIR.",
)


@phase2_skip
def test_phase2a_disjoint_concurrent_push():
    """Two devices push DISJOINT books concurrently. Proves NO LOST UPDATE (each
    push lands) and the server Merkle tree is not corrupted by the concurrent
    rebuilds (the live tree already equals a fresh rebuild)."""
    _reset_and_rebuild()
    token = _mint_token()
    # The writer's edit lm must beat any wall-clock app_modified the OTHER device
    # stamps when it pulls+applies this book during the concurrent round. The
    # barrier delays sync by ~window_ms, so a plain _host_ms() (set now) would be
    # STALE by sync time → a pulled-and-restamped copy (app_modified≈real-now)
    # could win and clobber this push (a real user edit is fresh, not stale). Use
    # a comfortably-future lm so the writer is unambiguously newest.
    a_title, b_title = "A-PUSH-NoCover", "B-PUSH-Converged"
    lm = _host_ms() + FUTURE_LM_MARGIN_MS
    ra, rb = _run_concurrent(
        token,
        {"SCENARIO": "push", "TARGET_UUID": UUID_NO_COVER, "TARGET_HAS_COVER": 0,
         "NEW_TITLE": a_title, "NEW_LM_MS": lm},
        {"SCENARIO": "push", "TARGET_UUID": UUID_CONVERGED, "TARGET_HAS_COVER": 1,
         "NEW_TITLE": b_title, "NEW_LM_MS": lm},
    )
    assert ra[0] == 0, f"device A push failed:\n{ra[1][-3000:]}\n{ra[2][-1200:]}"
    assert rb[0] == 0, f"device B push failed:\n{rb[1][-3000:]}\n{rb[2][-1200:]}"
    # No lost update: BOTH concurrent pushes are present on the server.
    assert _psql(f"SELECT title FROM books WHERE uuid='{UUID_NO_COVER}'") == a_title
    assert _psql(f"SELECT title FROM books WHERE uuid='{UUID_CONVERGED}'") == b_title
    # No LOST INVALIDATION: the server flags rebuild at the ROOT level (the level
    # the client consults — stale leaves are never served as truth). A concurrency
    # bug would leave a root advertised FRESH (is_stale=false) while its data
    # changed → a client would skip the rebuild and diverge. So: any root that is
    # NOT stale after the concurrent pushes must be unchanged by a fresh rebuild.
    roots_before = _psql(
        "SELECT dimension || '|' || root_hash || '|' || is_stale "
        "FROM sync_merkle_roots ORDER BY dimension")
    _rebuild_merkle()
    roots_after = {}
    for ln in _psql("SELECT dimension || '|' || root_hash "
                    "FROM sync_merkle_roots ORDER BY dimension").splitlines():
        dim, h = ln.split("|")
        roots_after[dim] = h
    for ln in roots_before.splitlines():
        dim, h, stale = ln.split("|")
        if stale not in ("t", "true", "1"):  # advertised fresh
            assert roots_after.get(dim) == h, (
                f"dimension '{dim}' root was advertised fresh (is_stale=false) but a "
                f"rebuild changed it → a concurrent push's invalidation was lost")


@phase2_skip
def test_phase2b_same_book_conflict_lww():
    """Two devices rewrite the SAME book differently, concurrently. LWW (§13
    effective-lm) must elect ONE deterministic winner (higher lm) and BOTH
    devices must converge to it — the loser adopts, no ping-pong."""
    _reset_and_rebuild()
    token = _mint_token()
    # Future base (see Phase 2a) so the writers' lm beats any pull-restamp clock;
    # the +10s gap between A and B still decides the deterministic LWW winner.
    winner, loser, base = "LWW-WINNER-A", "LWW-LOSER-B", _host_ms() + FUTURE_LM_MARGIN_MS
    ra, rb = _run_concurrent(
        token,
        {"SCENARIO": "conflict", "TARGET_UUID": UUID_NO_COVER, "TARGET_HAS_COVER": 0,
         "NEW_TITLE": winner, "NEW_LM_MS": base + 10_000, "EXPECTED_WINNER_TITLE": winner},
        {"SCENARIO": "conflict", "TARGET_UUID": UUID_NO_COVER, "TARGET_HAS_COVER": 0,
         "NEW_TITLE": loser, "NEW_LM_MS": base, "EXPECTED_WINNER_TITLE": winner},
    )
    # Each device asserts in-test it converged to the winner; exit 0 == no
    # ping-pong on EITHER device (the loser adopted the winner's value).
    assert ra[0] == 0, f"winner device A failed:\n{ra[1][-3000:]}\n{ra[2][-1200:]}"
    assert rb[0] == 0, f"loser device B failed:\n{rb[1][-3000:]}\n{rb[2][-1200:]}"
    # Server elected the higher-lm writer deterministically (push order agnostic).
    assert _psql(f"SELECT title FROM books WHERE uuid='{UUID_NO_COVER}'") == winner


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 3 — MULTI-USER (logical separation + concurrent load), HTTP-driven
#
# No emulator: pure API. SyncMatrixSeeder also plants a SECOND user B (own
# library USER_B_LIBRARY_UUID, distinct book uuids).
#   3a separation — user B's token must NOT read user A's library (0 books, no
#                   leak in a sync's updates_for_client) and vice versa.
#   3b load        — N concurrent sync requests across both users → no 500s and
#                   no corruption (per-user counts intact, Merkle still rebuilds).
# ─────────────────────────────────────────────────────────────────────────────

import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

SERVER_BASE = "http://127.0.0.1:8081/api"      # host → app container
USER_B_EMAIL = "sync-matrix-b@test.com"
USER_B_LIBRARY_UUID = "b2b2b2b2-0000-4000-8000-0000000000b2"
A_UUIDS = set(EXPECTED_SCENARIOS.values())


def _api(path: str, token: str, body=None):
    """Authenticated JSON call. Returns (status, parsed_body). HTTP 4xx/5xx are
    returned (not raised) so callers can assert on the code (e.g. load test)."""
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(SERVER_BASE + path, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or "{}")
        except Exception:
            payload = {}
        return e.code, payload


def _empty_sync_body(library_uuid: str) -> dict:
    return {"library_id": library_uuid, "calibre_library_uuid": library_uuid,
            "cursor": None, "batch_size": 100, "client_books": {"b": {}, "d": []}}


def _book_count(library_uuid: str) -> str:
    return _psql("SELECT count(*) FROM books b JOIN libraries l ON b.library_id = l.id "
                 f"WHERE l.calibre_library_id = '{library_uuid}'")


phase3_skip = pytest.mark.skipif(
    not _server_up(), reason="Phase 3 needs the dockerized test server up.")


@phase3_skip
def test_phase3a_multiuser_logical_separation():
    """User B must not see user A's library and vice versa — logical isolation
    across the sync API (Merkle root + a sync's updates_for_client)."""
    _reset_and_rebuild()                       # seeds A (4 books) + B (2 books)
    _rebuild_merkle(USER_B_LIBRARY_UUID)       # build B's tree too
    token_a = _mint_token()
    token_b = _mint_token(USER_B_EMAIL)

    # Each user sees ONLY their own library's book count.
    _, root_a = _api(f"/sync/v5/merkle-root?calibre_library_uuid={LIBRARY_UUID}", token_a)
    assert root_a.get("total_books") == 4, f"user A should see 4 books, got {root_a}"
    _, root_b = _api(f"/sync/v5/merkle-root?calibre_library_uuid={USER_B_LIBRARY_UUID}", token_b)
    assert root_b.get("total_books") == 2, f"user B should see 2 books, got {root_b}"

    # B querying A's library must see NONE of A's books.
    _, b_on_a = _api(f"/sync/v5/merkle-root?calibre_library_uuid={LIBRARY_UUID}", token_b)
    assert (b_on_a.get("total_books") or 0) == 0, \
        f"LEAK: user B sees user A's library ({b_on_a})"
    _, a_on_b = _api(f"/sync/v5/merkle-root?calibre_library_uuid={USER_B_LIBRARY_UUID}", token_a)
    assert (a_on_b.get("total_books") or 0) == 0, \
        f"LEAK: user A sees user B's library ({a_on_b})"

    # Strongest check: B runs a sync against A's library_uuid — A's books must NOT
    # appear in updates_for_client (a cross-user read leak would surface here).
    _, resp = _api("/sync/v5", token_b, _empty_sync_body(LIBRARY_UUID))
    leaked = {u.get("uuid") for u in resp.get("updates_for_client", [])} & A_UUIDS
    assert not leaked, f"LEAK: user B's sync of A's library returned A's books {leaked}"


@phase3_skip
def test_phase3b_concurrent_load_no_500s_no_corruption():
    """N concurrent syncs across both users hold up: no 500s, per-user book
    counts unchanged, and the Merkle tree still rebuilds (no torn state)."""
    _reset_and_rebuild()
    _rebuild_merkle(USER_B_LIBRARY_UUID)
    token_a = _mint_token()
    token_b = _mint_token(USER_B_EMAIL)

    N = 30

    def _one(i: int) -> int:
        is_a = (i % 2 == 0)
        tok = token_a if is_a else token_b
        lib = LIBRARY_UUID if is_a else USER_B_LIBRARY_UUID
        status, _ = _api("/sync/v5", tok, _empty_sync_body(lib))
        return status

    with ThreadPoolExecutor(max_workers=10) as ex:
        codes = list(ex.map(_one, range(N)))

    bad = [c for c in codes if c != 200]
    assert not bad, f"{len(bad)}/{N} concurrent syncs were non-200: {sorted(set(bad))}"

    # No corruption: each user's library still has exactly its seeded books.
    assert _book_count(LIBRARY_UUID) == "4", "user A book count changed under load"
    assert _book_count(USER_B_LIBRARY_UUID) == "2", "user B book count changed under load"
    # And the tree is not torn — a rebuild must succeed for both libraries.
    _rebuild_merkle(LIBRARY_UUID)
    _rebuild_merkle(USER_B_LIBRARY_UUID)


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 4 — DELETION DATA-SAFETY (end-to-end, the live dockerized PG server)
#
# Complements the phpunit Level-A tests (which run inside a wrapping
# transaction): here we drive the REAL running server over HTTP (autocommit) to
# prove, on the prod engine, that a VOLUNTARY delete tombstones while a PARTIAL
# inventory (a client that simply doesn't list every book — a restored/partial
# library) never deletes the omitted books. The plugin's own absence→delete
# guard is covered by the Level-B unit tests (test_mass_deletion_guard.py).
# ─────────────────────────────────────────────────────────────────────────────

UUID_PREFIXED = EXPECTED_SCENARIOS["cover_prefixed"]   # 1bed2112…


def _sync_body(library_uuid, books=None, deleted=None):
    return {"library_id": library_uuid, "calibre_library_uuid": library_uuid,
            "cursor": None, "batch_size": 100,
            "client_books": {"b": books or {}, "d": deleted or []}}


def _alive_count(library_uuid):
    return _psql("SELECT count(*) FROM books b JOIN libraries l ON b.library_id = l.id "
                 f"WHERE l.calibre_library_id = '{library_uuid}' AND b.deleted_at IS NULL")


def _is_tombstoned(uuid):
    return _psql(f"SELECT (deleted_at IS NOT NULL)::int FROM books WHERE uuid = '{uuid}'") == "1"


@phase3_skip
def test_phase4a_voluntary_delete_tombstones_partial_inventory_is_safe():
    """On the live PG server: an EXPLICIT delete (the 'd' list) soft-deletes the
    book, but a client that simply OMITS books from its inventory (a partial /
    restored library) never deletes the omitted ones — absence is not deletion."""
    _reset_and_rebuild()
    token = _mint_token()

    # 1) Voluntary delete of one book → server tombstones it + confirms.
    status, resp = _api("/sync/v5", token, _sync_body(LIBRARY_UUID, deleted=[UUID_NO_COVER]))
    assert status == 200, f"delete sync failed: {status} {resp}"
    assert UUID_NO_COVER in (resp.get("deleted_confirmed") or []), \
        "an explicit delete must be confirmed by the server"
    assert _is_tombstoned(UUID_NO_COVER), "an explicit delete must soft-delete the server book"

    # 2) Partial inventory: report only ONE of the 3 remaining books, NO 'd' list.
    #    The two unmentioned (still-alive) books must NOT be tombstoned.
    alive_before = _alive_count(LIBRARY_UUID)            # 3 after the delete
    status, _ = _api("/sync/v5", token,
                     _sync_body(LIBRARY_UUID, books={UUID_CONVERGED: {"m": "check"}}))
    assert status == 200
    assert _alive_count(LIBRARY_UUID) == alive_before, \
        "a partial inventory must not delete the omitted books (absence != delete)"
    assert not _is_tombstoned(UUID_PREFIXED), \
        "a book merely absent from the client inventory must not be tombstoned"


# ─────────────────────────────────────────────────────────────────────────────
# PHASE 5 — MULTI-CLIENT cover/file SETTINGS safety (end-to-end, live PG)
#
# The mobile app (metadata-only: covers/files OFF) and the Calibre plugin
# (covers+files ON) sync the SAME library configured differently. A metadata-only
# client must NOT make the server drop the covers/files the other client uploaded.
# ─────────────────────────────────────────────────────────────────────────────

def _sync_body_opts(library_uuid, books=None, deleted=None, options=None):
    body = _sync_body(library_uuid, books=books, deleted=deleted)
    body["options"] = options or {}
    return body


@phase3_skip
def test_phase5a_metadata_only_client_keeps_other_clients_covers_and_files():
    """Simulate the plugin having uploaded a file + the server holding a cover for
    a book, then a metadata-only app client (covers/files OFF) syncs the same
    library. The file and cover must SURVIVE — a metadata-only sync is not a
    deletion of the other client's assets."""
    _reset_and_rebuild()
    token = _mint_token()
    book = UUID_CONVERGED  # has_cover=1, cover_original_hash seeded

    # The plugin's uploaded file (pull user_id/library_id straight from the book).
    _psql(
        "INSERT INTO books_files (user_id, library_id, book, format, "
        "uncompressed_size, name, file_hash, is_uploaded, uuid, created_at, updated_at) "
        "SELECT user_id, library_id, uuid, 'EPUB', 1024, 'x.epub', "
        "'sha256:" + ('cd' * 32) + "', 1, 'ffffffff-0000-4000-8000-0000000000f1', "
        f"now(), now() FROM books WHERE uuid = '{book}'")

    def _uploaded_files():
        return _psql(f"SELECT count(*) FROM books_files WHERE book = '{book}' "
                     "AND is_uploaded = 1 AND deleted_at IS NULL")
    def _cover_hash():
        return _psql(f"SELECT COALESCE(cover_original_hash,'') FROM books WHERE uuid = '{book}'")

    assert _uploaded_files() == "1", "precondition: the plugin's file is present"
    cover_before = _cover_hash()
    assert cover_before, "precondition: the book has a server cover"

    # App-style metadata-only sync: covers/files OFF, no cover/file hash for the book.
    status, _ = _api("/sync/v5", token, _sync_body_opts(
        LIBRARY_UUID,
        books={book: {"m": "check", "c": None, "f": None}},
        options={"sync_files_enabled": False, "sync_covers_enabled": False}))
    assert status == 200

    assert _uploaded_files() == "1", \
        "a metadata-only client must NOT drop the plugin's uploaded file"
    assert _cover_hash() == cover_before, \
        "a metadata-only client must NOT drop the server cover"
