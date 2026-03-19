/**
 * mobile/src/components/ErrorBoundary.tsx
 *
 * Fix: Without an error boundary, any render error in a screen kills
 * the entire app with a blank screen. This component catches render
 * errors and shows a friendly recovery UI instead.
 */
import React, { Component, ReactNode } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, ScrollView,
} from 'react-native';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('[ErrorBoundary] Caught error:', error.message, info.componentStack);
    // In production: Sentry.captureException(error, { extra: info });
  }

  reset = () => this.setState({ hasError: false, error: null });

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <ScrollView contentContainerStyle={styles.container}>
        <Text style={styles.icon}>⚠️</Text>
        <Text style={styles.title}>
          {this.props.fallbackTitle ?? 'Something went wrong'}
        </Text>
        <Text style={styles.message}>
          {this.state.error?.message ?? 'An unexpected error occurred.'}
        </Text>
        <TouchableOpacity style={styles.btn} onPress={this.reset}>
          <Text style={styles.btnText}>Try Again</Text>
        </TouchableOpacity>
      </ScrollView>
    );
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0f0f1a',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
  },
  icon: { fontSize: 48, marginBottom: 16 },
  title: { color: '#fff', fontSize: 20, fontWeight: '700', marginBottom: 10, textAlign: 'center' },
  message: { color: '#888', fontSize: 13, textAlign: 'center', marginBottom: 28, lineHeight: 20 },
  btn: {
    backgroundColor: '#00d4aa',
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 36,
  },
  btnText: { color: '#000', fontWeight: '700', fontSize: 15 },
});
