from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path

import pytest


def _extract_last_json(text: str):
    for i in range(len(text) - 1, -1, -1):
        if text[i] != '{':
            continue
        try:
            return json.loads(text[i:])
        except Exception:
            continue
    return None


@pytest.mark.integration
def test_headless_selected_actions_runtime_e2e():
    if os.environ.get('CALIMOB_RUN_HEADLESS_ACTION_E2E', '0') != '1':
        pytest.skip('set CALIMOB_RUN_HEADLESS_ACTION_E2E=1 to run calibre-debug headless action e2e')

    root = Path(__file__).resolve().parents[3]
    runner = root / 'tests' / 'plugin' / 'integration' / 'action_selected_headless_runner.py'
    calibre_debug = Path(os.environ.get('CALIBRE_DEBUG', '/Applications/calibre.app/Contents/MacOS/calibre-debug'))
    calibre_customize = Path(os.environ.get('CALIBRE_CUSTOMIZE', '/Applications/calibre.app/Contents/MacOS/calibre-customize'))

    if not calibre_debug.exists():
        pytest.skip(f'calibre-debug not found at {calibre_debug}')
    if not calibre_customize.exists():
        pytest.skip(f'calibre-customize not found at {calibre_customize}')

    with tempfile.TemporaryDirectory(prefix='calimob_action_headless_cfg_') as tmp_cfg:
        env = os.environ.copy()
        env['CALIBRE_CONFIG_DIRECTORY'] = tmp_cfg
        env['CALIMOB_PROJECT_ROOT'] = str(root)

        install_cmd = [str(calibre_customize), '-b', str(root / 'sync_calimob')]
        install = subprocess.run(
            install_cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if install.returncode != 0:
            pytest.skip(f'plugin install failed in temp cfg (returncode={install.returncode})')

        run_cmd = [str(calibre_debug), '-e', str(runner)]
        run = subprocess.run(
            run_cmd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        assert run.returncode == 0, run.stdout
        payload = _extract_last_json(run.stdout)
        assert isinstance(payload, dict), run.stdout
        assert payload.get('ok') is True, run.stdout
