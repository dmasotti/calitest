/**
 * sync-concurrent-devices.js
 *
 * Simulates 10 devices syncing 5 libraries simultaneously.
 * Each virtual user (VU) represents one device. Libraries are assigned
 * round-robin so multiple VUs hit the same library concurrently,
 * which stresses the DB locking and Merkle cache invalidation paths.
 *
 * Usage:
 *   k6 run \
 *     --env BASE_URL=http://localhost:8088 \
 *     --env AUTH_TOKEN=<bearer-token> \
 *     --env LIBRARY_UUIDS=<comma-separated-uuids> \
 *     --env CALIBRE_LIBRARY_UUID=<calibre-uuid> \
 *     tests/load/sync-concurrent-devices.js
 *
 * LIBRARY_UUIDS: comma-separated list of up to 5 library UUIDs.
 *   If omitted, 5 random UUIDs are generated (requests will 404 but
 *   you can still validate response-time thresholds against a stub).
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { BASE_URL, AUTH_TOKEN, CALIBRE_LIBRARY_UUID } from './config.js';
import { generateSyncPayload, getAuthHeaders, uuid4 } from './helpers.js';

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const syncErrorRate = new Rate('sync_errors');
const syncDuration = new Trend('sync_duration_ms', true);

// ---------------------------------------------------------------------------
// Test configuration
// ---------------------------------------------------------------------------
export const options = {
    stages: [
        { duration: '30s', target: 10 },  // ramp up to 10 VUs
        { duration: '60s', target: 10 },  // hold at 10 VUs
        { duration: '30s', target: 0 },   // ramp down
    ],
    thresholds: {
        http_req_duration: ['p(95)<5000'],     // 95th percentile < 5 s
        sync_errors: ['rate<0.05'],            // < 5 % error rate
        sync_duration_ms: ['p(99)<8000'],      // 99th < 8 s
    },
};

// ---------------------------------------------------------------------------
// Parse library list
// ---------------------------------------------------------------------------
const rawLibs = __ENV.LIBRARY_UUIDS || '';
const LIBRARIES = rawLibs
    ? rawLibs.split(',').map((s) => s.trim())
    : [uuid4(), uuid4(), uuid4(), uuid4(), uuid4()];

// ---------------------------------------------------------------------------
// Main VU function
// ---------------------------------------------------------------------------
export default function () {
    // Assign a library round-robin based on VU id
    const libIndex = (__VU - 1) % LIBRARIES.length;
    const libraryId = LIBRARIES[libIndex];
    const calibreUuid = CALIBRE_LIBRARY_UUID || libraryId;

    // Build a payload of 50 books with random metadata hashes
    const clientBooks = generateSyncPayload(50);

    const payload = JSON.stringify({
        library_id: libraryId,
        calibre_library_uuid: calibreUuid,
        batch_size: 100,
        cursor: null,
        client_books: clientBooks,
    });

    const headers = getAuthHeaders(AUTH_TOKEN);

    const res = http.post(`${BASE_URL}/api/sync/v5`, payload, {
        headers,
        tags: { name: 'sync_v5' },
        timeout: '30s',
    });

    // Record custom metrics
    syncDuration.add(res.timings.duration);

    const ok = check(res, {
        'status is 200': (r) => r.status === 200,
        'response time < 5s': (r) => r.timings.duration < 5000,
        'body has updates_for_client': (r) => {
            try {
                const body = JSON.parse(r.body);
                return body.hasOwnProperty('updates_for_client');
            } catch (_) {
                return false;
            }
        },
        'no error field in body': (r) => {
            try {
                const body = JSON.parse(r.body);
                return !body.error;
            } catch (_) {
                return false;
            }
        },
    });

    syncErrorRate.add(!ok);

    // Brief pause between iterations to simulate real device cadence
    sleep(Math.random() * 2 + 1); // 1-3 s
}
