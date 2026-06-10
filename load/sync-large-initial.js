/**
 * sync-large-initial.js
 *
 * Simulates the initial sync of a 1000-book library.
 * A single VU pushes 20 batches of 50 books each, then verifies
 * convergence within 3 additional passes (Merkle re-check).
 *
 * This exercises:
 *   - Large payload handling (JSON parsing, DB inserts)
 *   - Cursor-based pagination on the server side
 *   - Merkle tree rebuild under sustained write load
 *
 * Usage:
 *   k6 run \
 *     --env BASE_URL=http://localhost:8088 \
 *     --env AUTH_TOKEN=<bearer-token> \
 *     --env LIBRARY_UUID=<library-uuid> \
 *     --env CALIBRE_LIBRARY_UUID=<calibre-uuid> \
 *     tests/load/sync-large-initial.js
 */

import http from 'k6/http';
import { check, sleep, fail } from 'k6';
import { Counter, Trend } from 'k6/metrics';
import { BASE_URL, AUTH_TOKEN, LIBRARY_UUID, CALIBRE_LIBRARY_UUID } from './config.js';
import { generateSyncPayload, getAuthHeaders, uuid4 } from './helpers.js';

// ---------------------------------------------------------------------------
// Custom metrics
// ---------------------------------------------------------------------------
const booksCreated = new Counter('books_created');
const batchDuration = new Trend('batch_duration_ms', true);
const convergencePasses = new Counter('convergence_passes');

// ---------------------------------------------------------------------------
// Test configuration — single VU, one iteration
// ---------------------------------------------------------------------------
export const options = {
    vus: 1,
    iterations: 1,
    thresholds: {
        http_req_duration: ['p(95)<10000'],       // each batch < 10 s
        batch_duration_ms: ['avg<6000'],           // average batch < 6 s
        checks: ['rate>0.95'],                     // 95 % of checks pass
    },
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------
const TOTAL_BOOKS = 1000;
const BATCH_SIZE = 50;
const BATCHES = Math.ceil(TOTAL_BOOKS / BATCH_SIZE); // 20
const MAX_CONVERGENCE_PASSES = 3;

// ---------------------------------------------------------------------------
// Main scenario
// ---------------------------------------------------------------------------
export default function () {
    const libraryId = LIBRARY_UUID || uuid4();
    const calibreUuid = CALIBRE_LIBRARY_UUID || libraryId;
    const headers = getAuthHeaders(AUTH_TOKEN);

    // Keep track of all UUIDs we sent so we can verify convergence
    const allSentUuids = {};

    // ------------------------------------------------------------------
    // Phase 1: Push 20 batches of 50 books
    // ------------------------------------------------------------------
    for (let batch = 0; batch < BATCHES; batch++) {
        const clientBooks = generateSyncPayload(BATCH_SIZE);
        Object.assign(allSentUuids, clientBooks);

        const payload = JSON.stringify({
            library_id: libraryId,
            calibre_library_uuid: calibreUuid,
            batch_size: 200,
            cursor: null,
            client_books: clientBooks,
        });

        const res = http.post(`${BASE_URL}/api/sync/v5`, payload, {
            headers,
            tags: { name: `sync_batch_${batch}` },
            timeout: '30s',
        });

        batchDuration.add(res.timings.duration);

        const batchOk = check(res, {
            [`batch ${batch}: status 200`]: (r) => r.status === 200,
            [`batch ${batch}: has updates_for_client`]: (r) => {
                try {
                    return JSON.parse(r.body).hasOwnProperty('updates_for_client');
                } catch (_) {
                    return false;
                }
            },
        });

        if (!batchOk) {
            console.error(`Batch ${batch} failed: status=${res.status} body=${res.body}`);
        }

        // Count books that the server accepted (missing_from_server in response
        // means the server created them — count = sent minus those returned as
        // updates_for_client with is_new_on_client flag).
        try {
            const body = JSON.parse(res.body);
            // Books the server did NOT already have are implicitly created
            const updatesCount = (body.updates_for_client || []).length;
            const created = BATCH_SIZE - updatesCount;
            booksCreated.add(created > 0 ? created : BATCH_SIZE);
        } catch (_) {
            // If we cannot parse, still count the batch
            booksCreated.add(BATCH_SIZE);
        }

        // Short pause between batches
        sleep(0.5);
    }

    // ------------------------------------------------------------------
    // Phase 2: Convergence verification
    // Resend ALL 1000 books — the server should return 0 missing_from_server
    // within at most MAX_CONVERGENCE_PASSES passes.
    // ------------------------------------------------------------------
    let converged = false;

    for (let pass = 0; pass < MAX_CONVERGENCE_PASSES; pass++) {
        convergencePasses.add(1);

        const payload = JSON.stringify({
            library_id: libraryId,
            calibre_library_uuid: calibreUuid,
            batch_size: 1000,
            cursor: null,
            client_books: allSentUuids,
        });

        const res = http.post(`${BASE_URL}/api/sync/v5`, payload, {
            headers,
            tags: { name: `convergence_pass_${pass}` },
            timeout: '60s',
        });

        check(res, {
            [`convergence pass ${pass}: status 200`]: (r) => r.status === 200,
        });

        try {
            const body = JSON.parse(res.body);
            const updates = body.updates_for_client || [];
            const hasMore = body.has_more || false;

            // Converged when the server reports no new updates and no more pages
            if (updates.length === 0 && !hasMore) {
                converged = true;
                console.log(`Converged after ${pass + 1} pass(es)`);
                break;
            }

            console.log(
                `Convergence pass ${pass}: ${updates.length} updates, has_more=${hasMore}`
            );
        } catch (e) {
            console.error(`Convergence pass ${pass} parse error: ${e}`);
        }

        sleep(1);
    }

    check(null, {
        'converged within 3 passes': () => converged,
    });

    // ------------------------------------------------------------------
    // Phase 3: Merkle root sanity check
    // ------------------------------------------------------------------
    const merkleRes = http.get(
        `${BASE_URL}/api/sync/v5/merkle-root?library_id=${libraryId}`,
        { headers, tags: { name: 'merkle_root' }, timeout: '10s' }
    );

    check(merkleRes, {
        'merkle root: status 200': (r) => r.status === 200,
        'merkle root: non-empty hash': (r) => {
            try {
                const body = JSON.parse(r.body);
                return body.root && body.root.length > 0;
            } catch (_) {
                return false;
            }
        },
    });
}
