#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Headless end-to-end sync scenarios for sync_calimob.

Runs calibre-debug in a subprocess and validates:
- full sync returns inventory (compressed) when requested
- incremental sync returns inventory_hint
- cursors advance monotonically (base64 unix ts)
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request


REQUIRED = [
    'CALIMOB_DISCOVERY_URL',
    'CALIMOB_LIBRARY_PATH',
    'CALIMOB_LIBRARY_ID',
    'CALIMOB_SERVER_LIBRARY_ID',
    'CALIMOB_CONFIG_JSON',
    'TEST_USER_EMAIL',
    'TEST_USER_PASSWORD',
]


def _skip(msg):
    sys.stderr.write('SKIP: %s\n' % msg)
    sys.exit(0)


def _get_env():
    env = {}
    for k in REQUIRED:
        v = os.environ.get(k)
        if not v:
            _skip('%s not set; headless E2E not run' % k)
        env[k] = v
    env['CALIBRE_DEBUG'] = os.environ.get('CALIBRE_DEBUG', '/Applications/calibre.app/Contents/MacOS/calibre-debug')
    env['CALIBRE_CUSTOMIZE'] = os.environ.get('CALIBRE_CUSTOMIZE', '/Applications/calibre.app/Contents/MacOS/calibre-customize')
    env['CALIMOB_RUN_FULL'] = os.environ.get('CALIMOB_RUN_FULL', '')
    env['CALIMOB_USE_V4'] = os.environ.get('CALIMOB_USE_V4', '')
    env['CALIMOB_SIMULATE_CRASH_AFTER_APPLY'] = os.environ.get('CALIMOB_SIMULATE_CRASH_AFTER_APPLY', '')
    return env


def _run(cmd, env=None):
    return subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _extract_json(output):
    # Find last valid JSON object by scanning backwards for '{'
    start = None
    for i in range(len(output) - 1, -1, -1):
        if output[i] != '{':
            continue
        try:
            obj = json.loads(output[i:])
            start = i
            break
        except Exception:
            continue
    if start is None:
        raise ValueError('No JSON summary found in output')
    return json.loads(output[start:])


def _json_request(url, method='GET', data=None, headers=None):
    body = None
    if data is not None:
        body = json.dumps(data).encode('utf-8')
    request = urllib.request.Request(url, data=body, method=method)
    if headers:
        for name, value in headers.items():
            request.add_header(name, value)
    if data is not None:
        request.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f'{method} {url} -> {exc.code} {exc.reason}: {payload}') from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f'{method} {url} failed: {exc}') from exc


def _discover_api_url(base_url):
    for suffix in ('/discovery.php', '/api/discovery'):
        candidate = base_url.rstrip('/') + suffix
        try:
            data = _json_request(candidate)
        except RuntimeError:
            continue
        api_url = data.get('api_url') or data.get('apiUrl')
        if api_url:
            return api_url
    raise RuntimeError(f'discovery failed for {base_url}')


def _login(api_url, email, password):
    payload = {'email': email, 'password': password}
    data = _json_request(api_url.rstrip('/') + '/auth/login', method='POST', data=payload)
    token = data.get('token')
    if not token:
        raise RuntimeError('login failed: %s' % json.dumps(data))
    return token


def _decode_cursor(cur):
    if not cur:
        return None
    try:
        raw = base64.b64decode(cur).decode('utf-8')
        return int(raw)
    except Exception:
        return None


def _install_plugin(tmp_cfg, root, calibre_customize):
    env = os.environ.copy()
    env['CALIBRE_CONFIG_DIRECTORY'] = tmp_cfg
    res = _run([calibre_customize, '-b', os.path.join(root, 'sync_calimob')], env=env)
    if res.returncode != 0:
        _skip('failed to install plugin into temp config')


def _run_cli(tmp_cfg, env, full_sync=False):
    cmd = [
        env['CALIBRE_DEBUG'],
        '-e', os.path.join(env['ROOT'], 'sync_calimob', 'cli.py'),
        '--',
        '--library-path', env['CALIMOB_LIBRARY_PATH'],
        '--library-id', env['CALIMOB_LIBRARY_ID'],
        '--calimob-library-id', env['CALIMOB_SERVER_LIBRARY_ID'],
    ]
    if full_sync:
        cmd.append('--full-sync')
    if env.get('CALIMOB_USE_V4'):
        cmd.append('--v4')
    if env.get('CALIMOB_SIMULATE_CRASH_AFTER_APPLY'):
        cmd.append('--simulate-crash-after-apply')

    proc_env = os.environ.copy()
    proc_env['CALIBRE_CONFIG_DIRECTORY'] = tmp_cfg
    res = _run(cmd, env=proc_env)
    return res


def _require_inventory(block, label):
    inv = block.get(label)
    if not isinstance(inv, dict):
        raise AssertionError('%s missing' % label)
    if 'version' not in inv or 'uuids' not in inv:
        raise AssertionError('%s missing required keys' % label)
    if not isinstance(inv['uuids'], list):
        raise AssertionError('%s uuids must be list' % label)
    return inv


def main():
    env = _get_env()

    if not os.path.isfile(env['CALIMOB_CONFIG_JSON']):
        _skip('CALIMOB_CONFIG_JSON missing: %s' % env['CALIMOB_CONFIG_JSON'])
    if not os.path.isfile(env['CALIBRE_DEBUG']):
        _skip('calibre-debug not found at %s' % env['CALIBRE_DEBUG'])
    if not os.path.isfile(env['CALIBRE_CUSTOMIZE']):
        _skip('calibre-customize not found at %s' % env['CALIBRE_CUSTOMIZE'])

    env['ROOT'] = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..'))
    if env.get('CALIMOB_USE_V4'):
        sys.stderr.write('INFO: CALIMOB_USE_V4=1 (running sync V4)\n')
    api_url = _discover_api_url(env['CALIMOB_DISCOVERY_URL'])
    token = _login(api_url, env['TEST_USER_EMAIL'], env['TEST_USER_PASSWORD'])

    tmp_cfg = tempfile.mkdtemp(prefix='calimob_cfg_')
    try:
        os.makedirs(os.path.join(tmp_cfg, 'plugins'))
        cfg_path = os.path.join(tmp_cfg, 'plugins', 'sync_calimob.json')
        shutil.copy(env['CALIMOB_CONFIG_JSON'], cfg_path)
        data = json.load(open(cfg_path, 'r'))
        lm = data.get('LibraryMappings', {})
        lm[env['CALIMOB_LIBRARY_ID']] = {
            'syncEnabled': True,
            'calibreLibraryId': env['CALIMOB_LIBRARY_ID'],
            'calimobLibraryId': int(env['CALIMOB_SERVER_LIBRARY_ID']),
            'calimobLibraryName': 'Headless E2E'
        }
        data['LibraryMappings'] = lm
        for store_key in ('Caliweb', 'Goodreads'):
            store = data.get(store_key, {})
            store['discoveryUrl'] = env['CALIMOB_DISCOVERY_URL']
            store['restToken'] = token
            # Keep restEndpoint explicit so CLI can hit API without UI discovery
            store['restEndpoint'] = api_url.rstrip('/')
            store.pop('deviceToken', None)
            store.pop('discoveryCache', None)
            data[store_key] = store
        with open(cfg_path, 'w') as f:
            json.dump(data, f, indent=2, sort_keys=True)
        _install_plugin(tmp_cfg, env['ROOT'], env['CALIBRE_CUSTOMIZE'])

        # Track cursor before
        cfg_path = os.path.join(tmp_cfg, 'plugins', 'sync_calimob.json')
        before = json.load(open(cfg_path, 'r'))
        mapping = before.get('LibraryMappings', {}).get(env['CALIMOB_LIBRARY_ID'], {})
        prev_cursor = mapping.get('lastSyncCursor') or mapping.get('lastPullCursor')

        if env['CALIMOB_RUN_FULL']:
            res_full = _run_cli(tmp_cfg, env, full_sync=True)
            if res_full.returncode != 0:
                raise RuntimeError('calibre-debug exit=%d\n%s' % (res_full.returncode, res_full.stdout[:400]))
            summary_full = _extract_json(res_full.stdout)
            if env.get('CALIMOB_USE_V4'):
                assert_true(summary_full.get('sync_version') == 'v4', 'expected sync_version=v4 (full)')
            if summary_full.get('pull', {}).get('errors'):
                raise AssertionError('full sync: pull errors')
            if summary_full.get('push', {}).get('errors'):
                raise AssertionError('full sync: push errors')
            _require_inventory(summary_full.get('pull', {}), 'inventory')

        res_inc = _run_cli(tmp_cfg, env, full_sync=False)
        if res_inc.returncode != 0:
            raise RuntimeError('calibre-debug exit=%d\n%s' % (res_inc.returncode, res_inc.stdout[:400]))
        summary_inc = _extract_json(res_inc.stdout)
        if env.get('CALIMOB_USE_V4'):
            assert_true(summary_inc.get('sync_version') == 'v4', 'expected sync_version=v4 (incremental)')
        if summary_inc.get('pull', {}).get('errors'):
            sys.stderr.write('incremental pull errors: %s\n' % json.dumps(summary_inc.get('pull')))
            sys.stderr.write('incremental output tail:\n%s\n' % out_inc[-2000:])
            raise AssertionError('incremental: pull errors')
        if summary_inc.get('push', {}).get('errors'):
            sys.stderr.write('incremental push errors: %s\n' % json.dumps(summary_inc.get('push')))
            sys.stderr.write('incremental output tail:\n%s\n' % out_inc[-2000:])
            raise AssertionError('incremental: push errors')
        _require_inventory(summary_inc.get('pull', {}), 'inventory_hint')

        # Cursor monotonic check
        after = json.load(open(cfg_path, 'r'))
        mapping_after = after.get('LibraryMappings', {}).get(env['CALIMOB_LIBRARY_ID'], {})
        new_cursor = mapping_after.get('lastSyncCursor') or mapping_after.get('lastPullCursor')
        prev_ts = _decode_cursor(prev_cursor)
        new_ts = _decode_cursor(new_cursor)
        if prev_ts is not None and new_ts is not None and new_ts < prev_ts:
            raise AssertionError('cursor regressed: %s -> %s' % (prev_cursor, new_cursor))

        # Optional crash/resume test for V4
        if os.environ.get('CALIMOB_CRASH_RESUME_V4'):
            crash_env = dict(env)
            crash_env['CALIMOB_USE_V4'] = '1'
            crash_env['CALIMOB_SIMULATE_CRASH_AFTER_APPLY'] = '1'
            crash_res = _run_cli(tmp_cfg, crash_env, full_sync=False)
            if crash_res.returncode == 0:
                raise AssertionError('Expected simulated crash to return non-zero')

            crashed = json.load(open(cfg_path, 'r'))
            crashed_mapping = crashed.get('LibraryMappings', {}).get(env['CALIMOB_LIBRARY_ID'], {})
            pull_cursor = crashed_mapping.get('lastPullCursor')
            if not pull_cursor:
                raise AssertionError('Expected lastPullCursor set after apply checkpoint')

            # Resume without crash flag
            resume_env = dict(env)
            resume_env['CALIMOB_USE_V4'] = '1'
            resume_env.pop('CALIMOB_SIMULATE_CRASH_AFTER_APPLY', None)
            resume_res = _run_cli(tmp_cfg, resume_env, full_sync=False)
            if resume_res.returncode != 0:
                raise RuntimeError('resume exit=%d\n%s' % (resume_res.returncode, resume_res.stdout[:400]))
            _extract_json(resume_res.stdout)

        print('PASS: headless E2E scenarios')
    finally:
        try:
            shutil.rmtree(tmp_cfg)
        except Exception:
            pass


if __name__ == '__main__':
    main()
