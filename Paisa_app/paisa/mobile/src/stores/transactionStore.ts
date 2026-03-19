/**
 * mobile/src/stores/transactionStore.ts
 *
 * Fix: Replaces plain useState<Transaction[]> in App.tsx with a proper
 * Zustand store. This:
 *   1. Persists state across component re-renders without prop drilling
 *   2. Provides a clean interface for WatermelonDB integration (swap
 *      the in-memory array for DB queries when native setup is confirmed)
 *   3. Allows screens defined outside App() to access shared state
 *
 * IMPORTANT: Amounts are stored in paise (1 INR = 100 paise) to match
 * the backend schema and avoid floating-point drift.
 */

import { create } from 'zustand';
import { format, isThisMonth, parseISO } from 'date-fns';

// ─── Types ────────────────────────────────────────────────────────────

export interface Transaction {
  id: string;
  description: string;
  amountPaise: number;          // Fix: store in paise, not rupees
  type: 'debit' | 'credit';
  date: string;                  // Fix: ISO 8601 string, not display label
  category: string;
}

export const DEBIT_CATEGORIES  = ['Food', 'Transport', 'Shopping', 'Bills', 'Health', 'Other'];
export const CREDIT_CATEGORIES = ['Salary', 'Freelance', 'Investment', 'Gift', 'Refund', 'Other'];

// ─── Helpers ──────────────────────────────────────────────────────────

/** Display a transaction's date as a human-readable relative string. */
export function formatTxnDate(isoDate: string): string {
  try {
    return format(parseISO(isoDate), 'dd MMM · h:mm a');
  } catch {
    return isoDate;
  }
}

export function amountRupees(paise: number): number {
  return paise / 100;
}

export function amountPaise(rupees: number): number {
  return Math.round(rupees * 100);
}

// ─── Store ────────────────────────────────────────────────────────────

interface TransactionState {
  transactions: Transaction[];
  smsGranted: boolean;

  // Derived — filtered to current calendar month
  monthlyIncomePaise: number;
  monthlyExpensePaise: number;
  monthlyBalance: number;

  // Category spending (debit only, current month)
  spendingByCategory: Record<string, number>;

  // Mutations
  addTransaction: (txn: Omit<Transaction, 'id'>) => void;
  removeTransaction: (id: string) => void;
  setSmsGranted: (granted: boolean) => void;
}

const SEED_TRANSACTIONS: Transaction[] = [
  {
    id: '1',
    description: 'Swiggy Order',
    amountPaise: 35000,
    type: 'debit',
    date: new Date(Date.now() - 1000 * 60 * 30).toISOString(), // 30 min ago
    category: 'Food',
  },
  {
    id: '2',
    description: 'Salary Credit',
    amountPaise: 4500000,
    type: 'credit',
    date: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(), // yesterday
    category: 'Salary',
  },
  {
    id: '3',
    description: 'Uber Ride',
    amountPaise: 18000,
    type: 'debit',
    date: new Date(Date.now() - 1000 * 60 * 60 * 26).toISOString(),
    category: 'Transport',
  },
];

/** Recompute all derived values from a transaction list. */
function computeDerived(txns: Transaction[]) {
  // Fix: filter to current month only for monthly totals
  const thisMonth = txns.filter(t => {
    try { return isThisMonth(parseISO(t.date)); } catch { return false; }
  });

  const monthlyIncomePaise = thisMonth
    .filter(t => t.type === 'credit')
    .reduce((s, t) => s + t.amountPaise, 0);

  const monthlyExpensePaise = thisMonth
    .filter(t => t.type === 'debit')
    .reduce((s, t) => s + t.amountPaise, 0);

  // Fix: category spending computed per-category from this month only
  const spendingByCategory = thisMonth
    .filter(t => t.type === 'debit')
    .reduce<Record<string, number>>((acc, t) => {
      acc[t.category] = (acc[t.category] ?? 0) + t.amountPaise;
      return acc;
    }, {});

  return {
    monthlyIncomePaise,
    monthlyExpensePaise,
    monthlyBalance: monthlyIncomePaise - monthlyExpensePaise,
    spendingByCategory,
  };
}

export const useTransactionStore = create<TransactionState>((set) => ({
  transactions: SEED_TRANSACTIONS,
  smsGranted: false,
  ...computeDerived(SEED_TRANSACTIONS),

  addTransaction: (txnData) =>
    set((state) => {
      const next = [
        {
          ...txnData,
          id: Date.now().toString(),
          date: txnData.date || new Date().toISOString(),
        },
        ...state.transactions,
      ];
      return { transactions: next, ...computeDerived(next) };
    }),

  removeTransaction: (id) =>
    set((state) => {
      const next = state.transactions.filter(t => t.id !== id);
      return { transactions: next, ...computeDerived(next) };
    }),

  setSmsGranted: (granted) => set({ smsGranted: granted }),
}));
