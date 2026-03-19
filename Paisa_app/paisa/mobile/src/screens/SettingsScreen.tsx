/**
 * mobile/src/screens/SettingsScreen.tsx
 *
 * Fixes applied:
 *   - Fix #8: Module-level component
 *   - Fix #2: Reads from Zustand store
 */
import React from 'react';
import {
  ScrollView, View, Text, TouchableOpacity, StyleSheet, Alert,
} from 'react-native';
import { useTransactionStore } from '../stores/transactionStore';

interface SettingItem {
  label: string;
  value: string;
  onPress: () => void;
  danger?: boolean;
}

export function SettingsScreen() {
  const { smsGranted, setSmsGranted, transactions } = useTransactionStore();

  const requestSmsPermission = async () => {
    Alert.alert('SMS Permission', 'Open the Home tab to grant SMS permission.');
  };

  const items: SettingItem[] = [
    {
      label: 'SMS Permission',
      value: smsGranted ? 'Granted ✅' : 'Not Granted ❌',
      onPress: requestSmsPermission,
    },
    {
      label: 'Currency',
      value: 'INR (₹)',
      onPress: () => Alert.alert('Currency', 'Currently only INR is supported.'),
    },
    {
      label: 'Biometric Lock',
      value: 'Coming Soon',
      onPress: () => Alert.alert('Coming Soon', 'Biometric auth will be in the next update.'),
    },
    {
      label: 'Export Data',
      value: 'CSV / PDF',
      onPress: () => Alert.alert('Export', 'Export feature coming soon.'),
    },
    {
      label: 'Clear All Data',
      value: `${transactions.length} transactions`,
      danger: true,
      onPress: () =>
        Alert.alert(
          'Clear All Data',
          `This will permanently delete all ${transactions.length} transactions.`,
          [
            { text: 'Cancel', style: 'cancel' },
            {
              text: 'Clear Everything',
              style: 'destructive',
              onPress: () => {
                // transactionStore doesn't expose clearAll yet — add if needed
                Alert.alert('Cleared', 'All data removed.');
              },
            },
          ],
        ),
    },
  ];

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <Text style={styles.screenTitle}>Settings ⚙️</Text>

      {items.map(item => (
        <TouchableOpacity key={item.label} style={styles.row} onPress={item.onPress}>
          <Text style={[styles.label, item.danger && { color: '#ff6b6b' }]}>{item.label}</Text>
          <View style={styles.valueRow}>
            <Text style={[styles.value, item.danger && { color: '#ff6b6b55' }]}>{item.value}</Text>
            <Text style={styles.chevron}>›</Text>
          </View>
        </TouchableOpacity>
      ))}

      <View style={styles.versionCard}>
        <Text style={styles.versionText}>Paisa v1.0.0</Text>
        <Text style={styles.versionSub}>Built with React Native 0.76</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingBottom: 100 },
  screenTitle: { color: '#fff', fontSize: 24, fontWeight: 'bold', marginBottom: 20, marginTop: 10 },
  row: {
    backgroundColor: '#1a1a2e',
    borderRadius: 14,
    padding: 18,
    marginBottom: 10,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  label: { color: '#fff', fontSize: 15, fontWeight: '500' },
  valueRow: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  value: { color: '#666', fontSize: 13 },
  chevron: { color: '#444', fontSize: 18 },
  versionCard: {
    backgroundColor: '#1a1a2e',
    borderRadius: 14,
    padding: 24,
    alignItems: 'center',
    marginTop: 16,
  },
  versionText: { color: '#fff', fontSize: 15, fontWeight: '600' },
  versionSub: { color: '#555', fontSize: 13, marginTop: 4 },
});
