/**
 * mobile/src/utils/device.ts
 * Stable device identifier — survives app updates, not uninstalls.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import {v4 as uuidv4} from 'uuid';

const DEVICE_ID_KEY = 'paisa:device_id';

let _deviceId: string | null = null;

export async function getDeviceId(): Promise<string> {
  if (_deviceId) return _deviceId;
  const stored = await AsyncStorage.getItem(DEVICE_ID_KEY);
  if (stored) {
    _deviceId = stored;
    return stored;
  }
  const id = uuidv4();
  await AsyncStorage.setItem(DEVICE_ID_KEY, id);
  _deviceId = id;
  return id;
}
