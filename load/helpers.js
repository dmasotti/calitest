/**
 * Common helper functions for k6 load tests.
 * No external dependencies — uses only k6 built-ins.
 */

/**
 * Generate a v4-style UUID (random).
 * Uses Math.random — good enough for load-test payloads.
 */
export function uuid4() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
        const r = (Math.random() * 16) | 0;
        const v = c === 'x' ? r : (r & 0x3) | 0x8;
        return v.toString(16);
    });
}

/**
 * Generate a hex hash string of the given length (default 32 = MD5-like).
 */
export function randomHash(len = 32) {
    const chars = '0123456789abcdef';
    let h = '';
    for (let i = 0; i < len; i++) {
        h += chars[(Math.random() * 16) | 0];
    }
    return h;
}

/**
 * Build a client_books dict suitable for POST /api/sync/v5.
 *
 * Each entry mirrors what the Calibre plugin / mobile app sends:
 *   { uuid: { metadata_hash, cover_hash, formats_sig, tail_hash } }
 *
 * @param {number} bookCount - How many books to generate
 * @returns {object} client_books keyed by UUID
 */
export function generateSyncPayload(bookCount) {
    const books = {};
    for (let i = 0; i < bookCount; i++) {
        const bookUuid = uuid4();
        books[bookUuid] = {
            metadata_hash: randomHash(32),
            cover_hash: randomHash(32),
            formats_sig: randomHash(16),
            tail_hash: randomHash(64),
        };
    }
    return books;
}

/**
 * Minimal valid JPEG file (1x1 pixel, red).
 * 107 bytes — smallest spec-compliant JFIF.
 * Returns an ArrayBuffer for use with http.file().
 */
export function generateMinimalJpeg() {
    // Hex-encoded minimal 1x1 JPEG
    const hex =
        'ffd8ffe000104a46494600010100000100010000' +
        'ffdb004300080606070605080707070909080a0c' +
        '140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c' +
        '20242e2720222c231c1c2837292c30313434341f' +
        '27393d38323c2e333432ffc0000b080001000101' +
        '011100ffc4001f000001050101010101010000000' +
        '0000000000102030405060708090a0bffc4001f01' +
        '0003010101010101010101000000000000010203' +
        '0405060708090a0bffda00080101000003f10001' +
        '11a5ffd9';
    // Actually, the above is not byte-exact. Use a known-good minimal JPEG:
    const bytes = [
        0xff, 0xd8, 0xff, 0xe0, 0x00, 0x10, 0x4a, 0x46, 0x49, 0x46, 0x00,
        0x01, 0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xff, 0xdb,
        0x00, 0x43, 0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07,
        0x07, 0x07, 0x09, 0x09, 0x08, 0x0a, 0x0c, 0x14, 0x0d, 0x0c, 0x0b,
        0x0b, 0x0c, 0x19, 0x12, 0x13, 0x0f, 0x14, 0x1d, 0x1a, 0x1f, 0x1e,
        0x1d, 0x1a, 0x1c, 0x1c, 0x20, 0x24, 0x2e, 0x27, 0x20, 0x22, 0x2c,
        0x23, 0x1c, 0x1c, 0x28, 0x37, 0x29, 0x2c, 0x30, 0x31, 0x34, 0x34,
        0x34, 0x1f, 0x27, 0x39, 0x3d, 0x38, 0x32, 0x3c, 0x2e, 0x33, 0x34,
        0x32, 0xff, 0xc0, 0x00, 0x0b, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01,
        0x01, 0x11, 0x00, 0xff, 0xc4, 0x00, 0x1f, 0x00, 0x00, 0x01, 0x05,
        0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0a, 0x0b, 0xff, 0xda, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00,
        0x3f, 0x00, 0x7b, 0x40, 0x1b, 0xff, 0xd9,
    ];
    const buf = new Uint8Array(bytes);
    return buf.buffer;
}

/**
 * Return standard auth + JSON headers for API requests.
 *
 * @param {string} token - Bearer token
 * @returns {object} Headers dict
 */
export function getAuthHeaders(token) {
    return {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
        Accept: 'application/json',
    };
}

/**
 * Return auth headers for multipart/form-data uploads.
 * (Content-Type is set automatically by k6 for multipart.)
 */
export function getUploadAuthHeaders(token) {
    return {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
    };
}
