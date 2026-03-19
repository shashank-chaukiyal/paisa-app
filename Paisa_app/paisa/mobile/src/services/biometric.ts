/**
 * mobile/src/services/biometric.ts
 *
 * Biometric authentication service.
 * Wraps react-native-biometrics with:
 *  • Graceful fallback to PIN when biometrics unavailable/cancelled
 *  • Key pair creation for cryptographic attestation (not just presence check)
 *  • Session token signing — the server verifies signatures, not just "passed=true"
 *  • Timeout: re-authenticate after 5 minutes of inactivity
 */

import ReactNativeBiometrics, {BiometryTypes} from 'react-native-biometrics';
import AsyncStorage from '@react-native-async-storage/async-storage';
import {logger} from '../utils/logger';

const rnBiometrics = new ReactNativeBiometrics({allowDeviceCredentials: true});

// ─── Types ────────────────────────────────────────────────────────────

export type BiometricStatus =
  | 'available'
  | 'not_enrolled'
  | 'unavailable'
  | 'unsupported';

export interface BiometricResult {
  success: boolean;
  signature?: string;    // base64 ECDSA signature of the payload
  error?: string;
  fallbackToPin?: boolean;
}

// ─── Constants ────────────────────────────────────────────────────────

const KEY_ALIAS = 'paisa_biometric_key';
const LAST_AUTH_KEY = 'paisa:last_biometric_auth';
const SESSION_TIMEOUT_MS = 5 * 60 * 1000; // 5 minutes

// ─── Setup ────────────────────────────────────────────────────────────

export async function checkBiometricStatus(): Promise<BiometricStatus> {
  try {
    const {available, biometryType} = await rnBiometrics.isSensorAvailable();
    if (!available) return 'unavailable';
    if (!biometryType) return 'unsupported';
    logger.info('biometric.status', {type: biometryType});
    return 'available';
  } catch (e) {
    logger.error('biometric.status_error', {error: String(e)});
    return 'unavailable';
  }
}

/**
 * Create a biometric-bound ECDSA key pair.
 * The public key is sent to the server during enrollment.
 * Private key never leaves the device Secure Enclave / StrongBox.
 */
export async function enrollBiometric(): Promise<{publicKey: string} | null> {
  try {
    const {keysExist} = await rnBiometrics.biometricKeysExist();
    if (keysExist) {
      await rnBiometrics.deleteKeys();
    }

    const {publicKey} = await rnBiometrics.createKeys();
    logger.info('biometric.enrolled', {publicKeyLength: publicKey.length});
    return {publicKey};
  } catch (e) {
    logger.error('biometric.enroll_failed', {error: String(e)});
    return null;
  }
}

// ─── Authentication ────────────────────────────────────────────────────

/**
 * Authenticate with biometrics and sign a challenge payload.
 * The server uses the previously registered public key to verify.
 *
 * @param payload  String to sign (e.g. `${userId}:${timestamp}`)
 */
export async function authenticateWithBiometrics(payload: string): Promise<BiometricResult> {
  try {
    const status = await checkBiometricStatus();
    if (status !== 'available') {
      return {success: false, error: `Biometrics ${status}`, fallbackToPin: true};
    }

    const {success, signature, error} = await rnBiometrics.createSignature({
      promptMessage: 'Confirm your identity',
      payload,
      cancelButtonText: 'Use PIN instead',
    });

    if (!success) {
      logger.warn('biometric.auth_failed', {error});
      return {success: false, error: error || 'Authentication failed', fallbackToPin: true};
    }

    // Record last successful auth time for session timeout
    await AsyncStorage.setItem(LAST_AUTH_KEY, Date.now().toString());
    logger.info('biometric.auth_success');
    return {success: true, signature};

  } catch (e: any) {
    logger.error('biometric.auth_exception', {error: e.message});
    return {success: false, error: e.message, fallbackToPin: true};
  }
}

/**
 * Check if the current biometric session is still valid (within timeout).
 * Use this to skip re-authentication for quick app switches.
 */
export async function isBiometricSessionValid(): Promise<boolean> {
  const lastAuth = await AsyncStorage.getItem(LAST_AUTH_KEY);
  if (!lastAuth) return false;
  return Date.now() - parseInt(lastAuth, 10) < SESSION_TIMEOUT_MS;
}

export async function clearBiometricSession(): Promise<void> {
  await AsyncStorage.removeItem(LAST_AUTH_KEY);
}

export async function removeBiometricKeys(): Promise<void> {
  try {
    await rnBiometrics.deleteKeys();
    logger.info('biometric.keys_deleted');
  } catch (e) {
    logger.error('biometric.delete_keys_failed', {error: String(e)});
  }
}
