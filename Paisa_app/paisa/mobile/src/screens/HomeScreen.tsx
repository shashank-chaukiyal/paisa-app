/**
 * mobile/src/screens/HomeScreen.tsx
 *
 * Fixes applied:
 *   - Fix #8:  Defined at module level (not inside App()), eliminating
 *              full remount on every parent state change
 *   - Fix #2:  Reads from Zustand store, not prop-drilled useState
 *   - Fix #11: Transaction dates are ISO strings, formatted with date-fns
 *   - Fix #13: Balance shown is monthly (income - expense this month)
 */
import React, { useState } from 'react';
import {
  ScrollView, View, Text, TouchableOpacity, StyleSheet,
  Alert, Platform, PermissionsAndroid,
} from 'react-native';
import { formatDistanceToNow, parseISO } from 'date-fns';
import { useTransactionStore, amountRupees } from '../stores/transactionStore';
import { AddModal } from '../components/AddModal';

export function HomeScreen() {
  const [showAddModal, setShowAddModal] = useState(false);

  const {
    transactions,
    monthlyIncomePaise,
    monthlyExpensePaise,
    monthlyBalance,
    smsGranted,
    setSmsGranted,
    removeTransaction,
  } = useTransactionStore();

  const requestSmsPermission = async () => {
    if (Platform.OS !== 'android') {
      Alert.alert('Not supported', 'SMS interception is Android only.');
      return;
    }
    try {
      const result = await PermissionsAndroid.requestMultiple([
        PermissionsAndroid.PERMISSIONS.RECEIVE_SMS,
        PermissionsAndroid.PERMISSIONS.READ_SMS,
      ]);
      const granted =
        result[PermissionsAndroid.PERMISSIONS.RECEIVE_SMS] === 'granted' &&
        result[PermissionsAndroid.PERMISSIONS.READ_SMS] === 'granted';
      setSmsGranted(granted);
      Alert.alert(
        granted ? '✅ Permission Granted' : '❌ Permission Denied',
        granted
          ? 'Paisa will now auto-detect bank SMS transactions.'
          : 'You can grant it later in App Settings → Permissions.',
      );
    } catch {
      Alert.alert('Error', 'Could not request SMS permission.');
    }
  };

  const handleDeleteTransaction = (id: string) => {
    Alert.alert('Delete', 'Remove this transaction?', [
      { text: 'Cancel', style: 'cancel' },
      { text: 'Delete', style: 'destructive', onPress: () => removeTransaction(id) },
    ]);
  };

  // Fix: format ISO date to relative time for display
  const formatDate = (iso: string) => {
    try {
      return formatDistanceToNow(parseISO(iso), { addSuffix: true });
    } catch {
      return iso;
    }
  };

  return (
    <>
      <AddModal visible={showAddModal} onClose={() => setShowAddModal(false)} />

      <ScrollView contentContainerStyle={styles.scroll}>
        <View style={styles.header}>
          <Text style={styles.logo}>₹ Paisa</Text>
          <Text style={styles.tagline}>Smart Finance Tracker</Text>
        </View>

        {/* Fix: balance is monthly, not all-time */}
        <View style={styles.card}>
          <Text style={styles.cardLabel}>This Month's Balance</Text>
          <Text style={[styles.balance, { color: monthlyBalance >= 0 ? '#00d4aa' : '#ff6b6b' }]}>
            ₹ {amountRupees(monthlyBalance).toLocaleString('en-IN')}
          </Text>
          <View style={styles.row}>
            <View style={styles.incomeBox}>
              <Text style={styles.incomeLabel}>↑ Income</Text>
              <Text style={styles.incomeAmount}>₹ {amountRupees(monthlyIncomePaise).toLocaleString('en-IN')}</Text>
            </View>
            <View style={styles.expenseBox}>
              <Text style={styles.expenseLabel}>↓ Expense</Text>
              <Text style={styles.expenseAmount}>₹ {amountRupees(monthlyExpensePaise).toLocaleString('en-IN')}</Text>
            </View>
          </View>
        </View>

        <Text style={styles.sectionTitle}>Quick Actions</Text>
        <View style={styles.row}>
          {[
            { icon: '➕', label: 'Add', onPress: () => setShowAddModal(true) },
          ].map(btn => (
            <TouchableOpacity key={btn.label} style={styles.actionBtn} onPress={btn.onPress}>
              <Text style={styles.actionIcon}>{btn.icon}</Text>
              <Text style={styles.actionText}>{btn.label}</Text>
            </TouchableOpacity>
          ))}
        </View>

        <Text style={styles.sectionTitle}>Recent Transactions</Text>
        {transactions.length === 0 ? (
          <View style={styles.emptyCard}>
            <Text style={styles.emptyIcon}>💳</Text>
            <Text style={styles.emptyText}>No transactions yet</Text>
            <Text style={styles.emptySubtext}>Tap ➕ to add one manually</Text>
          </View>
        ) : (
          transactions.slice(0, 10).map(txn => (
            <TouchableOpacity
              key={txn.id}
              style={styles.txnRow}
              onLongPress={() => handleDeleteTransaction(txn.id)}
            >
              <View style={[styles.txnIcon, { backgroundColor: txn.type === 'credit' ? '#00d4aa22' : '#ff6b6b22' }]}>
                <Text>{txn.type === 'credit' ? '↑' : '↓'}</Text>
              </View>
              <View style={styles.txnInfo}>
                <Text style={styles.txnDesc}>{txn.description}</Text>
                {/* Fix: use formatted ISO date */}
                <Text style={styles.txnDate}>{formatDate(txn.date)} · {txn.category}</Text>
              </View>
              <Text style={[styles.txnAmount, { color: txn.type === 'credit' ? '#00d4aa' : '#ff6b6b' }]}>
                {txn.type === 'credit' ? '+' : '-'}₹{amountRupees(txn.amountPaise).toLocaleString('en-IN')}
              </Text>
            </TouchableOpacity>
          ))
        )}

        <View style={styles.smsCard}>
          <Text style={styles.smsTitle}>
            {smsGranted ? '✅ SMS Active' : '📱 SMS Auto-Detection'}
          </Text>
          <Text style={styles.smsText}>
            {smsGranted
              ? 'Paisa is monitoring bank SMS for auto transactions.'
              : 'Grant SMS permission to automatically log UPI & bank transactions.'}
          </Text>
          {!smsGranted && (
            <TouchableOpacity style={styles.grantBtn} onPress={requestSmsPermission}>
              <Text style={styles.grantBtnText}>Grant Permission</Text>
            </TouchableOpacity>
          )}
        </View>
      </ScrollView>
    </>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingBottom: 100 },
  header: { alignItems: 'center', paddingVertical: 30 },
  logo: { fontSize: 36, fontWeight: 'bold', color: '#00d4aa' },
  tagline: { fontSize: 14, color: '#888', marginTop: 4 },
  card: { backgroundColor: '#1a1a2e', borderRadius: 20, padding: 24, marginBottom: 24, borderWidth: 1, borderColor: '#00d4aa33' },
  cardLabel: { color: '#888', fontSize: 14, marginBottom: 4 },
  balance: { color: '#fff', fontSize: 38, fontWeight: 'bold', marginVertical: 8 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 8 },
  incomeBox: { flex: 1 },
  expenseBox: { flex: 1 },
  incomeLabel: { color: '#00d4aa', fontSize: 12 },
  incomeAmount: { color: '#00d4aa', fontSize: 18, fontWeight: '600' },
  expenseLabel: { color: '#ff6b6b', fontSize: 12 },
  expenseAmount: { color: '#ff6b6b', fontSize: 18, fontWeight: '600' },
  sectionTitle: { color: '#fff', fontSize: 18, fontWeight: '600', marginBottom: 12, marginTop: 8 },
  actionBtn: { flex: 1, backgroundColor: '#1a1a2e', borderRadius: 16, padding: 14, alignItems: 'center', borderWidth: 1, borderColor: '#ffffff11' },
  actionIcon: { fontSize: 22 },
  actionText: { color: '#888', fontSize: 11, marginTop: 5 },
  emptyCard: { backgroundColor: '#1a1a2e', borderRadius: 16, padding: 32, alignItems: 'center', marginBottom: 16 },
  emptyIcon: { fontSize: 40 },
  emptyText: { color: '#fff', fontSize: 16, marginTop: 12, fontWeight: '600' },
  emptySubtext: { color: '#666', fontSize: 13, marginTop: 6, textAlign: 'center' },
  txnRow: { backgroundColor: '#1a1a2e', borderRadius: 14, padding: 16, marginBottom: 10, flexDirection: 'row', alignItems: 'center' },
  txnIcon: { width: 40, height: 40, borderRadius: 20, alignItems: 'center', justifyContent: 'center', marginRight: 12 },
  txnInfo: { flex: 1 },
  txnDesc: { color: '#fff', fontSize: 15, fontWeight: '500' },
  txnDate: { color: '#666', fontSize: 12, marginTop: 3 },
  txnAmount: { color: '#fff', fontSize: 15, fontWeight: '600' },
  smsCard: { backgroundColor: '#00d4aa22', borderRadius: 16, padding: 20, marginTop: 8, borderWidth: 1, borderColor: '#00d4aa55' },
  smsTitle: { color: '#00d4aa', fontSize: 16, fontWeight: '600', marginBottom: 8 },
  smsText: { color: '#aaa', fontSize: 13, lineHeight: 20 },
  grantBtn: { backgroundColor: '#00d4aa', borderRadius: 10, padding: 14, alignItems: 'center', marginTop: 12 },
  grantBtnText: { color: '#000', fontWeight: '700', fontSize: 14 },
});
