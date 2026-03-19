/**
 * mobile/src/screens/AnalyticsScreen.tsx
 *
 * Fixes applied:
 *   - Fix #8:  Module-level component — not recreated on every App() render
 *   - Fix #9:  "This Month" now actually shows THIS MONTH's data (was all-time)
 *   - Fix #14: Category breakdown uses per-category monthly spending (was all expenses)
 *   - Fix #2:  Reads from Zustand store
 */
import React from 'react';
import { ScrollView, View, Text, StyleSheet } from 'react-native';
import { useTransactionStore, amountRupees } from '../stores/transactionStore';
import { format } from 'date-fns';

export function AnalyticsScreen() {
  const {
    transactions,
    monthlyExpensePaise,
    monthlyIncomePaise,
    spendingByCategory,
  } = useTransactionStore();

  const monthLabel = format(new Date(), 'MMMM yyyy');
  const monthlyTxnCount = Object.values(spendingByCategory).length;
  const totalCategorySpend = Object.values(spendingByCategory).reduce((s, v) => s + v, 0);

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <Text style={styles.screenTitle}>Analytics 📊</Text>

      {/* Fix: "This Month" label with actual month name and real monthly total */}
      <View style={styles.card}>
        <Text style={styles.cardLabel}>{monthLabel}</Text>
        <Text style={styles.balance}>₹ {amountRupees(monthlyExpensePaise).toLocaleString('en-IN')}</Text>
        <Text style={styles.cardLabel}>
          Total spent · {transactions.filter(t => t.type === 'debit').length} expense transactions
        </Text>
      </View>

      <View style={styles.summaryRow}>
        <View style={[styles.summaryCard, { borderColor: '#00d4aa44' }]}>
          <Text style={styles.summaryLabel}>Income</Text>
          <Text style={[styles.summaryValue, { color: '#00d4aa' }]}>
            ₹{amountRupees(monthlyIncomePaise).toLocaleString('en-IN')}
          </Text>
        </View>
        <View style={[styles.summaryCard, { borderColor: '#ff6b6b44' }]}>
          <Text style={styles.summaryLabel}>Expense</Text>
          <Text style={[styles.summaryValue, { color: '#ff6b6b' }]}>
            ₹{amountRupees(monthlyExpensePaise).toLocaleString('en-IN')}
          </Text>
        </View>
      </View>

      {/* Fix: per-category spending using actual category-filtered amounts */}
      <Text style={styles.sectionTitle}>Spending by Category</Text>
      {Object.keys(spendingByCategory).length === 0 ? (
        <View style={styles.emptyCard}>
          <Text style={styles.emptyText}>No expense data for {monthLabel}</Text>
        </View>
      ) : (
        Object.entries(spendingByCategory)
          .sort(([, a], [, b]) => b - a) // highest first
          .map(([cat, paise]) => {
            const pct = totalCategorySpend > 0 ? (paise / totalCategorySpend) * 100 : 0;
            return (
              <View key={cat} style={styles.txnRow}>
                <View style={styles.txnInfo}>
                  <View style={styles.catHeader}>
                    <Text style={styles.txnDesc}>{cat}</Text>
                    <Text style={styles.pctLabel}>{pct.toFixed(0)}%</Text>
                  </View>
                  <View style={styles.progressBg}>
                    <View style={[styles.progressFill, { width: `${Math.min(pct, 100)}%` }]} />
                  </View>
                </View>
                <Text style={styles.txnAmount}>₹{amountRupees(paise).toLocaleString('en-IN')}</Text>
              </View>
            );
          })
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingBottom: 100 },
  screenTitle: { color: '#fff', fontSize: 24, fontWeight: 'bold', marginBottom: 20, marginTop: 10 },
  card: { backgroundColor: '#1a1a2e', borderRadius: 20, padding: 24, marginBottom: 20, borderWidth: 1, borderColor: '#00d4aa33' },
  cardLabel: { color: '#888', fontSize: 14, marginBottom: 4 },
  balance: { color: '#fff', fontSize: 38, fontWeight: 'bold', marginVertical: 8 },
  summaryRow: { flexDirection: 'row', gap: 12, marginBottom: 24 },
  summaryCard: { flex: 1, backgroundColor: '#1a1a2e', borderRadius: 14, padding: 16, borderWidth: 1 },
  summaryLabel: { color: '#888', fontSize: 12, marginBottom: 4 },
  summaryValue: { fontSize: 20, fontWeight: '700' },
  sectionTitle: { color: '#fff', fontSize: 18, fontWeight: '600', marginBottom: 12 },
  emptyCard: { backgroundColor: '#1a1a2e', borderRadius: 14, padding: 32, alignItems: 'center' },
  emptyText: { color: '#666', fontSize: 14 },
  txnRow: { backgroundColor: '#1a1a2e', borderRadius: 14, padding: 16, marginBottom: 10, flexDirection: 'row', alignItems: 'center' },
  txnInfo: { flex: 1, marginRight: 12 },
  catHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 8 },
  txnDesc: { color: '#fff', fontSize: 14, fontWeight: '500' },
  pctLabel: { color: '#888', fontSize: 12 },
  txnAmount: { color: '#fff', fontSize: 14, fontWeight: '600' },
  progressBg: { backgroundColor: '#ffffff11', borderRadius: 4, height: 6 },
  progressFill: { backgroundColor: '#00d4aa', borderRadius: 4, height: 6 },
});
