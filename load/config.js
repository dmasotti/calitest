/**
 * Shared configuration for k6 load tests.
 *
 * Override via environment variables:
 *   k6 run --env BASE_URL=http://localhost:8088 --env AUTH_TOKEN=xxx ...
 */

export const BASE_URL = __ENV.BASE_URL || 'https://caliwebapp.com';
export const AUTH_TOKEN = __ENV.AUTH_TOKEN || '';
export const LIBRARY_UUID = __ENV.LIBRARY_UUID || '';
// Library numeric ID (some endpoints accept both)
export const LIBRARY_ID = __ENV.LIBRARY_ID || '';
// Calibre library UUID — required by sync/v5
export const CALIBRE_LIBRARY_UUID = __ENV.CALIBRE_LIBRARY_UUID || LIBRARY_UUID;
