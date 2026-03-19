/**
 * mobile/src/services/sms.ts
 *
 * Fix #7 (SMS hash mismatch):
 *   Before: mobile computed SHA-256(sender + ":" + body) for dedup.
 *   After:  mobile sends raw sender + body to the backend and lets the
 *           server compute the canonical hash as SHA-256(user_id:device_id:body).
 *
 *   The local AsyncStorage dedup key now uses the body+sender as a
 *   CACHE KEY only (not sent to the server), preventing double-firing
 *   of the upload logic within the same app session.
 *
 *   The server-side unique constraint uq_sms_dedup(user_id, device_id,
 *   message_hash) is the authoritative deduplication gate.
 */

import { NativeEventEmitter, NativeModules, Platform } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { apiClient } from './api';
import { logger } from '../utils/logger';
import { getDeviceId } from '../utils/device';

const { PaisaSmsModule } = NativeModules;

export interface RawSms {
  sender: string;
  body: string;
  // Fix: hash is a LOCAL cache key only; server computes its own canonical hash
  localCacheKey: string;
  timestamp: number;
}

// ─── Constants ────────────────────────────────────────────────────────

const SMS_QUEUE_KEY         = 'paisa:sms_queue';
const SMS_SEEN_KEYS_KEY     = 'paisa:sms_local_keys'; // renamed from sms_hashes
const MAX_SEEN_KEYS         = 500;
const UPLOAD_BATCH_SIZE     = 10;
const MAX_UPLOAD_RETRIES    = 3;

// ─── Local dedup (prevents re-firing within the same session) ─────────

async function isSeenLocally(key: string): Promise<boolean> {
  const raw = await AsyncStorage.getItem(SMS_SEEN_KEYS_KEY);
  const keys: string[] = raw ? JSON.parse(raw) : [];
  return keys.includes(key);
}

async function markSeenLocally(key: string): Promise<void> {
  const raw = await AsyncStorage.getItem(SMS_SEEN_KEYS_KEY);
  const keys: string[] = raw ? JSON.parse(raw) : [];
  keys.unshift(key);
  await AsyncStorage.setItem(
    SMS_SEEN_KEYS_KEY,
    JSON.stringify(keys.slice(0, MAX_SEEN_KEYS)),
  );
}

// ─── Local queue (offline buffer) ─────────────────────────────────────

async function enqueueSms(sms: RawSms): Promise<void> {
  const raw = await AsyncStorage.getItem(SMS_QUEUE_KEY);
  const queue: RawSms[] = raw ? JSON.parse(raw) : [];
  queue.push(sms);
  await AsyncStorage.setItem(SMS_QUEUE_KEY, JSON.stringify(queue));
}

async function dequeueAll(): Promise<RawSms[]> {
  const raw = await AsyncStorage.getItem(SMS_QUEUE_KEY);
  if (!raw) return [];
  await AsyncStorage.removeItem(SMS_QUEUE_KEY);
  return JSON.parse(raw);
}

// ─── Upload ───────────────────────────────────────────────────────────

async function uploadSmsToBackend(messages: RawSms[], retryCount = 0): Promise<void> {
  const deviceId = await getDeviceId();

  try {
    await apiClient.post(
      '/api/v1/sms/ingest',
      {
        messages: messages.map((m) => ({
          sender: m.sender,
          body: m.body,
          // Fix: do NOT send a pre-computed hash — server will compute it
          // using SHA-256(user_id:device_id:body) for correct deduplication
          received_at: new Date(m.timestamp).toISOString(),
          device_id: deviceId,
        })),
      },
      { timeout: 15_000 },
    );
    logger.info('sms.uploaded', { count: messages.length });
  } catch (error: any) {
    if (retryCount >= MAX_UPLOAD_RETRIES) {
      logger.error('sms.upload_failed_max_retries', { count: messages.length, error: error.message });
      for (const msg of messages) await enqueueSms(msg);
      return;
    }
    const backoff = Math.pow(2, retryCount) * 1000 + Math.random() * 500;
    logger.warn('sms.upload_retry', { attempt: retryCount + 1, backoffMs: Math.round(backoff) });
    await new Promise((r) => setTimeout(r, backoff));
    await uploadSmsToBackend(messages, retryCount + 1);
  }
}

// ─── Core SMS handler ──────────────────────────────────────────────────

async function handleIncomingSms(sms: RawSms): Promise<void> {
  logger.debug('sms.received', { sender: sms.sender });

  // Local session dedup only — server is the authoritative dedup gate
  if (await isSeenLocally(sms.localCacheKey)) {
    logger.debug('sms.local_duplicate_skipped');
    return;
  }
  await markSeenLocally(sms.localCacheKey);

  try {
    await uploadSmsToBackend([sms]);
  } catch {
    await enqueueSms(sms);
  }
}

// ─── Public API ───────────────────────────────────────────────────────

let eventSubscription: any = null;

export async function requestSmsPermission(): Promise<boolean> {
  if (Platform.OS !== 'android') return false;
  if (!PaisaSmsModule) {
    logger.error('sms.native_module_not_found');
    return false;
  }
  try {
    const granted = await PaisaSmsModule.requestSmsPermission();
    logger.info('sms.permission_result', { granted });
    return granted;
  } catch (e) {
    logger.error('sms.permission_error', { error: String(e) });
    return false;
  }
}

export function startSmsListener(): void {
  if (Platform.OS !== 'android' || !PaisaSmsModule) return;
  if (eventSubscription) return;
  const emitter = new NativeEventEmitter(PaisaSmsModule);
  eventSubscription = emitter.addListener('SMS_RECEIVED', handleIncomingSms);
  logger.info('sms.listener_started');
}

export function stopSmsListener(): void {
  if (eventSubscription) {
    eventSubscription.remove();
    eventSubscription = null;
    logger.info('sms.listener_stopped');
  }
}

export async function importHistoricalSms(daysBack = 30): Promise<{ imported: number; skipped: number }> {
  if (Platform.OS !== 'android' || !PaisaSmsModule) return { imported: 0, skipped: 0 };
  logger.info('sms.historical_import_start', { daysBack });
  try {
    const messages: RawSms[] = await PaisaSmsModule.readHistoricalSms(daysBack);
    let imported = 0;
    let skipped = 0;
    const unseen: RawSms[] = [];
    for (const msg of messages) {
      if (await isSeenLocally(msg.localCacheKey)) { skipped++; }
      else { await markSeenLocally(msg.localCacheKey); unseen.push(msg); }
    }
    for (let i = 0; i < unseen.length; i += UPLOAD_BATCH_SIZE) {
      await uploadSmsToBackend(unseen.slice(i, i + UPLOAD_BATCH_SIZE));
      imported += Math.min(UPLOAD_BATCH_SIZE, unseen.length - i);
      await new Promise((r) => setTimeout(r, 200));
    }
    logger.info('sms.historical_import_complete', { imported, skipped });
    return { imported, skipped };
  } catch (error: any) {
    logger.error('sms.historical_import_failed', { error: error.message });
    return { imported: 0, skipped: 0 };
  }
}

export async function flushSmsQueue(): Promise<void> {
  const queued = await dequeueAll();
  if (queued.length === 0) return;
  logger.info('sms.flush_queue', { count: queued.length });
  for (let i = 0; i < queued.length; i += UPLOAD_BATCH_SIZE) {
    await uploadSmsToBackend(queued.slice(i, i + UPLOAD_BATCH_SIZE));
  }
}
