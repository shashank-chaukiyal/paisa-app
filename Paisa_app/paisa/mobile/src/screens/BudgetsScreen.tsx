/**
 * mobile/src/screens/BudgetsScreen.tsx
 *
 * Fixes applied:
 *   - Fix #8:  Module-level component
 *   - Fix #15: Budget "spent" now uses CATEGORY-SPECIFIC spending
 *              (was Math.min(totalExpense, limit) which was totally wrong)
 *   - Fix #2:  Reads from Zustand store
 */
import React from 'react';
import { ScrollView, View, Text, StyleSheet } from 'react-native';
import { useTransactionStore, amountRupees } from '../stores/transactionStore';

// Default budgets — in a full implementation these would come from the backend/DB
const DEFAULT_BUDGETS = [
  { name: 'Food',      limitPaise: 500000,  category: 'Food' },
  { name: 'Transport', limitPaise: 200000,  category: 'Transport' },
  { name: 'Shopping',  limitPaise: 300000,  category: 'Shopping' },
  { name: 'Bills',     limitPaise: 250000,  category: 'Bills' },
  { name: 'Health',    limitPaise: 150000,  category: 'Health' },
];

export function BudgetsScreen() {
  // Fix: use actual per-category spending from the store
  const { spendingByCategory } = useTransactionStore();

  return (
    <ScrollView contentContainerStyle={styles.scroll}>
      <Text style={styles.screenTitle}>Budgets 🎯</Text>

      {DEFAULT_BUDGETS.map(budget => {
        // Fix: look up THIS category's actual spending (not total expense)
        const spentPaise = spendingByCategory[budget.name] ?? 0;
        const pct = budget.limitPaise > 0
          ? Math.min((spentPaise / budget.limitPaise) * 100, 100)
          : 0;
        const color = pct > 90 ? '#ff6b6b' : pct > 70 ? '#ffa500' : '#00d4aa';

        return (
          <View key={budget.name} style={styles.budgetCard}>
            <View style={styles.budgetHeader}>
              <Text style={styles.budgetName}>{budget.name}</Text>
              <Text style={[styles.pct, { color }]}>{pct.toFixed(0)}%</Text>
            </View>
            <View style={styles.progressBg}>
              <View style={[styles.progressFill, { width: `${pct}%`, backgroundColor: color }]} />
            </View>
            <View style={styles.budgetFooter}>
              <Text style={styles.spent}>₹{amountRupees(spentPaise).toLocaleString('en-IN')} spent</Text>
              <Text style={styles.limit}>of ₹{amountRupees(budget.limitPaise).toLocaleString('en-IN')}</Text>
            </View>
            {pct > 90 && (
              <Text style={styles.warning}>⚠️ Budget almost exceeded!</Text>
            )}
          </View>
        );
      })}

      <View style={styles.hint}>
        <Text style={styles.hintText}>💡 Long-press a budget to edit its limit (coming soon)</Text>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  scroll: { padding: 20, paddingBottom: 100 },
  screenTitle: { color: '#fff', fontSize: 24, fontWeight: 'bold', marginBottom: 20, marginTop: 10 },
  budgetCard: { backgroundColor: '#1a1a2e', borderRadius: 14, padding: 18, marginBottom: 14 },
  budgetHeader: { flexDirection: 'row', justifyContent: 'space-between', marginBottom: 10 },
  budgetName: { color: '#fff', fontSize: 15, fontWeight: '600' },
  pct: { fontSize: 14, fontWeight: '700' },
  progressBg: { backgroundColor: '#ffffff11', borderRadius: 4, height: 8, marginBottom: 10 },
  progressFill: { borderRadius: 4, height: 8 },
  budgetFooter: { flexDirection: 'row', justifyContent: 'space-between' },
  spent: { color: '#ccc', fontSize: 13 },
  limit: { color: '#666', fontSize: 13 },
  warning: { color: '#ff6b6b', fontSize: 12, marginTop: 8 },
  hint: { backgroundColor: '#1a1a2e', borderRadius: 14, padding: 16, alignItems: 'center', marginTop: 8 },
  hintText: { color: '#555', fontSize: 13 },
});
