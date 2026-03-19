/**
 * mobile/src/components/AddModal.tsx
 *
 * Fixes applied:
 *   - Fix #16: Category list changes based on debit/credit type
 *   - Fix #17: KeyboardAvoidingView prevents keyboard covering inputs
 *   - Fix #17: Tapping overlay backdrop dismisses the modal
 *   - Fix #11: Dates stored as ISO strings, not display labels
 *   - Fix #2:  Uses Zustand store instead of prop-drilled setState
 */
import React, { useState } from 'react';
import {
  Modal, View, Text, TextInput, TouchableOpacity,
  ScrollView, StyleSheet, Alert, KeyboardAvoidingView,
  Platform, TouchableWithoutFeedback,
} from 'react-native';
import {
  useTransactionStore,
  DEBIT_CATEGORIES,
  CREDIT_CATEGORIES,
  amountPaise,
} from '../stores/transactionStore';

interface Props {
  visible: boolean;
  onClose: () => void;
}

const INITIAL_FORM = { description: '', amount: '', type: 'debit' as 'debit' | 'credit', category: 'Food' };

export function AddModal({ visible, onClose }: Props) {
  const addTransaction = useTransactionStore(s => s.addTransaction);
  const [form, setForm] = useState(INITIAL_FORM);

  // Fix: category list is dynamic based on transaction type
  const categories = form.type === 'debit' ? DEBIT_CATEGORIES : CREDIT_CATEGORIES;

  const handleTypeChange = (type: 'debit' | 'credit') => {
    const defaultCat = type === 'debit' ? 'Food' : 'Salary';
    setForm(f => ({ ...f, type, category: defaultCat }));
  };

  const handleSave = () => {
    if (!form.description.trim() || !form.amount.trim()) {
      Alert.alert('Missing fields', 'Please enter description and amount.');
      return;
    }
    const parsed = parseFloat(form.amount);
    if (isNaN(parsed) || parsed <= 0) {
      Alert.alert('Invalid amount', 'Please enter a valid positive number.');
      return;
    }
    addTransaction({
      description: form.description.trim(),
      amountPaise: amountPaise(parsed),   // Fix: store paise not rupees
      type: form.type,
      date: new Date().toISOString(),       // Fix: ISO timestamp not "Just now"
      category: form.category,
    });
    setForm(INITIAL_FORM);
    onClose();
  };

  const handleClose = () => {
    setForm(INITIAL_FORM);
    onClose();
  };

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={handleClose}>
      {/* Fix: tapping the backdrop dismisses the modal */}
      <TouchableWithoutFeedback onPress={handleClose}>
        <View style={styles.overlay}>
          {/* Fix: KeyboardAvoidingView prevents keyboard from covering inputs */}
          <KeyboardAvoidingView
            behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          >
            <TouchableWithoutFeedback onPress={e => e.stopPropagation()}>
              <View style={styles.sheet}>
                <Text style={styles.title}>Add Transaction</Text>

                <TextInput
                  style={styles.input}
                  placeholder="Description (e.g. Swiggy)"
                  placeholderTextColor="#555"
                  value={form.description}
                  onChangeText={v => setForm(f => ({ ...f, description: v }))}
                />
                <TextInput
                  style={styles.input}
                  placeholder="Amount in ₹ (e.g. 350)"
                  placeholderTextColor="#555"
                  keyboardType="numeric"
                  value={form.amount}
                  onChangeText={v => setForm(f => ({ ...f, amount: v }))}
                />

                <Text style={styles.label}>Type</Text>
                <View style={styles.row}>
                  {(['debit', 'credit'] as const).map(t => (
                    <TouchableOpacity
                      key={t}
                      style={[styles.typeBtn, form.type === t && styles.typeBtnActive]}
                      onPress={() => handleTypeChange(t)}
                    >
                      <Text style={[styles.typeBtnText, form.type === t && styles.typeBtnTextActive]}>
                        {t === 'debit' ? '↓ Expense' : '↑ Income'}
                      </Text>
                    </TouchableOpacity>
                  ))}
                </View>

                {/* Fix: categories update when type changes */}
                <Text style={styles.label}>Category</Text>
                <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.catScroll}>
                  {categories.map(c => (
                    <TouchableOpacity
                      key={c}
                      style={[styles.chip, form.category === c && styles.chipActive]}
                      onPress={() => setForm(f => ({ ...f, category: c }))}
                    >
                      <Text style={[styles.chipText, form.category === c && styles.chipTextActive]}>{c}</Text>
                    </TouchableOpacity>
                  ))}
                </ScrollView>

                <View style={[styles.row, { marginTop: 24 }]}>
                  <TouchableOpacity
                    style={[styles.btn, styles.btnCancel]}
                    onPress={handleClose}
                  >
                    <Text style={styles.btnCancelText}>Cancel</Text>
                  </TouchableOpacity>
                  <TouchableOpacity style={[styles.btn, styles.btnSave]} onPress={handleSave}>
                    <Text style={styles.btnSaveText}>Save</Text>
                  </TouchableOpacity>
                </View>
              </View>
            </TouchableWithoutFeedback>
          </KeyboardAvoidingView>
        </View>
      </TouchableWithoutFeedback>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: { flex: 1, backgroundColor: '#000000bb', justifyContent: 'flex-end' },
  sheet: { backgroundColor: '#1a1a2e', borderTopLeftRadius: 24, borderTopRightRadius: 24, padding: 24, paddingBottom: 36 },
  title: { color: '#fff', fontSize: 20, fontWeight: '700', marginBottom: 20 },
  input: { backgroundColor: '#0f0f1a', borderRadius: 12, padding: 14, color: '#fff', marginBottom: 12, borderWidth: 1, borderColor: '#ffffff11', fontSize: 14 },
  label: { color: '#888', fontSize: 12, marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 },
  row: { flexDirection: 'row', justifyContent: 'space-between', gap: 8, marginBottom: 16 },
  typeBtn: { flex: 1, padding: 12, borderRadius: 10, borderWidth: 1, borderColor: '#ffffff22', alignItems: 'center' },
  typeBtnActive: { backgroundColor: '#00d4aa', borderColor: '#00d4aa' },
  typeBtnText: { color: '#888', fontWeight: '600', fontSize: 13 },
  typeBtnTextActive: { color: '#000' },
  catScroll: { marginBottom: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 20, borderWidth: 1, borderColor: '#ffffff22', marginRight: 8 },
  chipActive: { backgroundColor: '#00d4aa', borderColor: '#00d4aa' },
  chipText: { color: '#888', fontSize: 13 },
  chipTextActive: { color: '#000', fontWeight: '600' },
  btn: { flex: 1, borderRadius: 12, paddingVertical: 14, alignItems: 'center' },
  btnCancel: { backgroundColor: '#2a2a3e', borderWidth: 1, borderColor: '#ffffff22' },
  btnCancelText: { color: '#aaa', fontWeight: '600' },
  btnSave: { backgroundColor: '#00d4aa' },
  btnSaveText: { color: '#000', fontWeight: '700', fontSize: 15 },
});
