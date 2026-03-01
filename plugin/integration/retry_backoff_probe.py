#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Probe retry/backoff by simulating transient 503s on a local HTTP server."""

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import threading
import time
try:
    from http.server import HTTPServer, BaseHTTPRequestHandler
except ImportError:
    from BaseHTTPServer import HTTPServer, BaseHTTPRequestHandler


class _State(object):
    def __init__(self):
        self.count = 0


def _make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != '/api/ping':
                self.send_response(404)
                self.end_headers()
                return
            state.count += 1
            if state.count <= 2:
                self.send_response(503)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"ok": false, "error": "retry"}')
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"ok": true}')

        def log_message(self, fmt, *args):
            return

    return Handler


def main():
    cfg_dir = os.environ.get('CALIBRE_CONFIG_DIRECTORY')
    if not cfg_dir:
        raise SystemExit('CALIBRE_CONFIG_DIRECTORY not set')
    plugins_dir = os.path.join(cfg_dir, 'plugins')
    if not os.path.isdir(plugins_dir):
        os.makedirs(plugins_dir)

    state = _State()
    httpd = HTTPServer(('127.0.0.1', 0), _make_handler(state))
    port = httpd.server_address[1]

    def run_server():
        httpd.serve_forever()

    t = threading.Thread(target=run_server)
    t.daemon = True
    t.start()

    cfg_path = os.path.join(plugins_dir, 'sync_calimob.json')
    data = {
        'Caliweb': {
            'restEndpoint': 'http://127.0.0.1:%d/api' % port,
            'discoveryUrl': '',
        },
        'LibraryMappings': {}
    }
    with open(cfg_path, 'w') as f:
        json.dump(data, f, indent=2, sort_keys=True)

    from calibre_plugins.sync_calimob import rest_client

    client = rest_client.RestApiClient(None)
    client.max_retries = 3

    start = time.time()
    result = client.get('/ping')
    elapsed = time.time() - start

    httpd.shutdown()
    t.join(timeout=1)

    ok = bool(result and result.get('ok'))
    summary = {
        'ok': ok,
        'attempts': state.count,
        'elapsed_seconds': round(elapsed, 3),
    }
    print(json.dumps(summary, sort_keys=True))
    if not ok or state.count < 3:
        raise SystemExit('FAIL: retry/backoff did not trigger (attempts=%s)' % state.count)
    print('PASS: retry/backoff scenario')


if __name__ == '__main__':
    main()
