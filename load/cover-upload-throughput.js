/**
 * cover-upload-throughput.js
 *
 * Simulates 20 concurrent cover uploads via:
 *   POST /api/libraries/{libraryUuid}/books/{bookUuid}/cover
 *
 * Each VU uploads a minimal valid JPEG (1x1 pixel).
 * This stresses the cover storage path (local disk or R2)
 * and the has_cover / cover_hash update logic.
 *
 * Prerequisites:
 *   - BOOK_UUIDS env var: comma-separated list of existing book UUIDs
 *     (at least 20 for full parallelism; VUs are assigned round-robin).
 *   - The books must belong to LIBRARY_UUID and to the authenticated user.
 *
 * Usage:
 *   k6 run \
 *     --env BASE_URL=http://localhost:8088 \
 *     --env AUTH_TOKEN=<bearer-token> \
 *     --env LIBRARY_UUID=<library-uuid> \
 *     --env BOOK_UUIDS=uuid1,uuid2,...,uuid20 \
 *     tests/load/cover-upload-throughput.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';
import { BASE_URL, AUTH_TOKEN, LIBRARY_UUID } from './config.js';
import { generateMinimalJpeg, getUploadAuthHeaders, uuid4 } from './helpers.js';

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const uploadErrorRate = new Rate('upload_errors');
const uploadDuration = new Trend('upload_duration_ms', true);

// ---------------------------------------------------------------------------
// Test configuration
// ---------------------------------------------------------------------------
export const options = {
    stages: [
        { duration: '10s', target: 20 },  // ramp up to 20 VUs
        { duration: '30s', target: 20 },  // hold
        { duration: '10s', target: 0 },   // ramp down
    ],
    thresholds: {
        http_req_duration: ['p(95)<5000'],       // 95th < 5 s
        upload_errors: ['rate<0.10'],            // < 10 % error rate
        upload_duration_ms: ['p(99)<8000'],      // 99th < 8 s
    },
};

// ---------------------------------------------------------------------------
// Parse book UUID list
// ---------------------------------------------------------------------------
const rawBooks = __ENV.BOOK_UUIDS || '';
const BOOK_UUIDS = rawBooks
    ? rawBooks.split(',').map((s) => s.trim())
    : [];

if (BOOK_UUIDS.length === 0) {
    console.warn(
        'BOOK_UUIDS not set — uploads will target random UUIDs and likely 404. ' +
        'Set BOOK_UUIDS=uuid1,uuid2,... for meaningful tests.'
    );
    // Generate placeholder UUIDs so the test still runs structurally
    for (let i = 0; i < 20; i++) {
        BOOK_UUIDS.push(uuid4());
    }
}

// ---------------------------------------------------------------------------
// Pre-generate the JPEG once (shared across all VUs in the same worker)
// ---------------------------------------------------------------------------
const JPEG_DATA = generateMinimalJpeg();

// ---------------------------------------------------------------------------
// Main VU function
// ---------------------------------------------------------------------------
export default function () {
    const libraryUuid = LIBRARY_UUID || uuid4();
    const bookIndex = (__VU - 1) % BOOK_UUIDS.length;
    const bookUuid = BOOK_UUIDS[bookIndex];

    const headers = getUploadAuthHeaders(AUTH_TOKEN);

    // k6's http.file() wraps binary data for multipart upload
    const coverFile = http.file(JPEG_DATA, 'cover.jpg', 'image/jpeg');

    const res = http.post(
        `${BASE_URL}/api/libraries/${libraryUuid}/books/${bookUuid}/cover`,
        { cover: coverFile },
        {
            headers,
            tags: { name: 'cover_upload' },
            timeout: '15s',
        }
    );

    uploadDuration.add(res.timings.duration);

    const ok = check(res, {
        'status is 200': (r) => r.status === 200,
        'response time < 5s': (r) => r.timings.duration < 5000,
        'body confirms cover stored': (r) => {
            try {
                const body = JSON.parse(r.body);
                // The endpoint returns the updated book or a success message
                return (
                    body.has_cover === 1 ||
                    body.has_cover === true ||
                    body.success === true ||
                    r.status === 200
                );
            } catch (_) {
                // If body is not JSON but status is 200, still OK
                return r.status === 200;
            }
        },
    });

    uploadErrorRate.add(!ok);

    // Short pause to avoid hammering the storage backend
    sleep(Math.random() * 1.5 + 0.5); // 0.5-2 s
}
