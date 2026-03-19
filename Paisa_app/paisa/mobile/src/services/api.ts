/**
 * mobile/src/services/api.ts
 *
 * Fixes applied:
 *   - Fix #1:  Corrected uuid import (named import, not default) — was causing
 *              runtime crash "uuid.v4 is not a function" on every API call
 *   - Fix #6:  device_id in token refresh now calls getDeviceId() instead of
 *              hardcoded string literal 'device'
 *   - Fix #5:  Separate _authRetry and _retryCount flags so a 401 on a
 *              retried request still triggers the refresh flow correctly
 */

import axios, { AxiosInstance, AxiosRequestConfig, AxiosError } from 'axios';
import * as Keychain from 'react-native-keychain';
// Fix #1: Use named import — uuid v7+ has no default export
import { v4 as uuidv4 } from 'uuid';
import { logger } from '../utils/logger';
import { getDeviceId } from '../utils/device';

const BASE_URL = __DEV__ ? 'http://10.0.2.2:8000' : 'https://api.paisa.app';
const TIMEOUT_MS = 15_000;
const MAX_RETRIES = 3;

// ─── Token storage ────────────────────────────────────────────────────

const KEYCHAIN_SERVICE = 'paisa_tokens';

export async function saveTokens(access: string, refresh: string): Promise<void> {
  await Keychain.setGenericPassword(
    'tokens',
    JSON.stringify({ access, refresh }),
    {
      service: KEYCHAIN_SERVICE,
      accessControl: Keychain.ACCESS_CONTROL.BIOMETRY_ANY_OR_DEVICE_PASSCODE,
    },
  );
}

export async function getTokens(): Promise<{ access: string; refresh: string } | null> {
  const creds = await Keychain.getGenericPassword({ service: KEYCHAIN_SERVICE });
  if (!creds) return null;
  try {
    return JSON.parse(creds.password);
  } catch {
    return null;
  }
}

export async function clearTokens(): Promise<void> {
  await Keychain.resetGenericPassword({ service: KEYCHAIN_SERVICE });
}

// ─── Axios instance ───────────────────────────────────────────────────

export const apiClient: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  timeout: TIMEOUT_MS,
  headers: { 'Content-Type': 'application/json' },
});

// ─── Request interceptor — attach auth + request ID ──────────────────

apiClient.interceptors.request.use(async (config) => {
  const tokens = await getTokens();
  if (tokens?.access) {
    config.headers.Authorization = `Bearer ${tokens.access}`;
  }
  // Fix #1: was uuid.v4() (default import crash) — now correctly uuidv4()
  config.headers['X-Request-ID'] = uuidv4();
  return config;
});

// ─── Response interceptor — token refresh + retry ─────────────────────

let isRefreshing = false;
let refreshSubscribers: Array<(token: string) => void> = [];

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb);
}

function onRefreshed(token: string) {
  refreshSubscribers.forEach((cb) => cb(token));
  refreshSubscribers = [];
}

// Fix #5: Extended request config type with SEPARATE flags for auth vs retry
type ExtendedConfig = AxiosRequestConfig & {
  _authRetry?: boolean;    // true = already attempted token refresh for this request
  _retryCount?: number;    // number of network-error retries attempted
};

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as ExtendedConfig;

    // ── 401: refresh token ─────────────────────────────────────────
    // Fix #5: Use _authRetry (not _retry) so network retries don't block refresh
    if (error.response?.status === 401 && !originalRequest._authRetry) {
      originalRequest._authRetry = true;

      if (isRefreshing) {
        return new Promise((resolve) => {
          subscribeTokenRefresh((token) => {
            originalRequest.headers = {
              ...originalRequest.headers,
              Authorization: `Bearer ${token}`,
            };
            resolve(apiClient(originalRequest));
          });
        });
      }

      isRefreshing = true;
      try {
        const tokens = await getTokens();
        if (!tokens?.refresh) throw new Error('No refresh token');

        // Fix #6: get the real device ID instead of hardcoded 'device'
        const deviceId = await getDeviceId();

        const { data } = await axios.post(`${BASE_URL}/api/v1/auth/refresh`, {
          refresh_token: tokens.refresh,
          device_id: deviceId,          // Fix: was hardcoded string 'device'
        });

        await saveTokens(data.access_token, data.refresh_token);
        onRefreshed(data.access_token);

        originalRequest.headers = {
          ...originalRequest.headers,
          Authorization: `Bearer ${data.access_token}`,
        };
        return apiClient(originalRequest);
      } catch (refreshErr) {
        await clearTokens();
        logger.error('api.refresh_failed');
        return Promise.reject(refreshErr);
      } finally {
        isRefreshing = false;
      }
    }

    // ── Network errors: exponential backoff retry ──────────────────
    // Fix #5: Uses _retryCount independent of _authRetry
    if (!error.response) {
      const retryCount = (originalRequest._retryCount ?? 0) + 1;
      if (retryCount <= MAX_RETRIES) {
        originalRequest._retryCount = retryCount;
        const backoff = Math.pow(2, retryCount) * 500 + Math.random() * 500;
        logger.warn('api.network_retry', { attempt: retryCount, backoffMs: Math.round(backoff) });
        await new Promise((r) => setTimeout(r, backoff));
        return apiClient(originalRequest);
      }
    }

    logger.error('api.request_failed', {
      status: error.response?.status,
      url: originalRequest.url,
      method: originalRequest.method,
    });

    return Promise.reject(error);
  },
);
