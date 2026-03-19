/**
 * mobile/src/utils/logger.ts
 * Structured logger — mirrors backend structlog output format.
 * In production: ship to Sentry / Datadog via their RN SDKs.
 */

type LogLevel = 'debug' | 'info' | 'warn' | 'error';

interface LogEntry {
  level: LogLevel;
  event: string;
  timestamp: string;
  [key: string]: unknown;
}

function emit(level: LogLevel, event: string, context: Record<string, unknown> = {}) {
  const entry: LogEntry = {
    level,
    event,
    timestamp: new Date().toISOString(),
    ...context,
  };

  if (__DEV__) {
    const color = {debug: '\x1b[37m', info: '\x1b[32m', warn: '\x1b[33m', error: '\x1b[31m'}[level];
    console.log(`${color}[${level.toUpperCase()}]\x1b[0m ${event}`, context);
  } else {
    // Production: ship to monitoring
    // Sentry.addBreadcrumb({ message: event, data: context, level });
  }
}

export const logger = {
  debug: (event: string, ctx?: Record<string, unknown>) => emit('debug', event, ctx),
  info:  (event: string, ctx?: Record<string, unknown>) => emit('info',  event, ctx),
  warn:  (event: string, ctx?: Record<string, unknown>) => emit('warn',  event, ctx),
  error: (event: string, ctx?: Record<string, unknown>) => emit('error', event, ctx),
};
