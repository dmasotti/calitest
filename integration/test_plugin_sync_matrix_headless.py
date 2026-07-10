"""Plugin headless sync on SyncMatrixSeeder UUIDs (Sprint 3).

Wraps sync_calimob/tests/plugin/integration/headless_sync_matrix_mrk06.sh.
Skips when docker PG or calibre-debug unavailable.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

HTML_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "html",
)
PROJECT_ROOT = os.path.dirname(HTML_DIR)
SCRIPT = os.path.join(
    PROJECT_ROOT,
    "sync_calimob",
    "tests",
    "plugin",
    "integration",
    "headless_sync_matrix_mrk06.sh",
)
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")


def _pg_up() -> bool:
    if not shutil.which("docker"):
        return False
    r = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", "caliweb_test_pg"],
        capture_output=True,
        text=True,
    )
    return r.returncode == 0 and r.stdout.strip() == "true"


def _calibre_debug() -> bool:
    path = os.environ.get(
        "CALIBRE_DEBUG", "/Applications/calibre.app/Contents/MacOS/calibre-debug"
    )
    return os.path.isfile(path) and os.access(path, os.X_OK)


pytestmark = pytest.mark.skipif(
    not _pg_up() or not _calibre_debug(),
    reason="Needs caliweb_test_pg + calibre-debug for plugin headless matrix.",
)


def test_plugin_headless_sync_matrix_mrk06_two_sync():
    """case_id MRK-06 plugin: 2 headless syncs on matrix UUIDs; server file survives."""
    subprocess.run(
        [os.path.join(SCRIPTS_DIR, "reset-test-server.sh")],
        check=True,
        capture_output=True,
        text=True,
    )
    r = subprocess.run(["bash", SCRIPT], capture_output=True, text=True)
    if r.stdout.strip().startswith("SKIP:") or "SKIP:" in r.stderr:
        pytest.skip(r.stderr or r.stdout)
    assert r.returncode == 0, (
        "plugin headless matrix failed:\n" + r.stdout[-2000:] + "\n" + r.stderr[-1000:]
    )
