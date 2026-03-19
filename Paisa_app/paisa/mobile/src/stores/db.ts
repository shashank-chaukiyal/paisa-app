/**
 * mobile/src/stores/db.ts
 *
 * Fixes applied:
 *   - Fix #24: Removed unused `lazy` import (dead code)
 *   - Fix #22: JSI mode disabled (jsi: false) with clear comment explaining
 *              how to re-enable once native CMakeLists + build.gradle are
 *              configured per WatermelonDB JSI setup guide.
 *              Enabling JSI without native setup causes a crash on startup.
 */

import { Database } from '@nozbe/watermelondb';
import SQLiteAdapter from '@nozbe/watermelondb/adapters/sqlite';
import { Model, tableSchema, appSchema } from '@nozbe/watermelondb';
// Fix: removed `lazy` — it was imported but never used (dead import)
import { field, date, readonly, writer } from '@nozbe/watermelondb/decorators';
import { schemaMigrations, addColumns } from '@nozbe/watermelondb/Schema/migrations';
import { Q } from '@nozbe/watermelondb';

// ─── Schema (version 2) ───────────────────────────────────────────────

export const schema = appSchema({
  version: 2,
  tables: [
    tableSchema({
      name: 'transactions',
      columns: [
        { name: 'client_id',      type: 'string',  isIndexed: true },
        { name: 'server_id',      type: 'string',  isOptional: true, isIndexed: true },
        { name: 'amount_paise',   type: 'number' },
        { name: 'txn_type',       type: 'string' },
        { name: 'txn_date',       type: 'number' },
        { name: 'description',    type: 'string' },
        { name: 'category_id',    type: 'number',  isOptional: true },
        { name: 'merchant',       type: 'string',  isOptional: true },
        { name: 'reference_id',   type: 'string',  isOptional: true },
        { name: 'upi_vpa',        type: 'string',  isOptional: true },
        { name: 'bank_name',      type: 'string',  isOptional: true },
        { name: 'account_masked', type: 'string',  isOptional: true },
        { name: 'source',         type: 'string' },
        { name: 'notes',          type: 'string',  isOptional: true },
        { name: 'tags',           type: 'string',  isOptional: true },
        { name: 'sync_status',    type: 'string' },
        { name: 'is_deleted',     type: 'boolean' },
        { name: 'created_at',     type: 'number' },
        { name: 'updated_at',     type: 'number' },
      ],
    }),
    tableSchema({
      name: 'categories',
      columns: [
        { name: 'server_id',  type: 'number',  isOptional: true },
        { name: 'name',       type: 'string' },
        { name: 'icon',       type: 'string',  isOptional: true },
        { name: 'color',      type: 'string',  isOptional: true },
        { name: 'is_income',  type: 'boolean' },
        { name: 'sort_order', type: 'number' },
        { name: 'created_at', type: 'number' },
        { name: 'updated_at', type: 'number' },
      ],
    }),
    tableSchema({
      name: 'budgets',
      columns: [
        { name: 'server_id',   type: 'number',  isOptional: true },
        { name: 'name',        type: 'string' },
        { name: 'category_id', type: 'number',  isOptional: true },
        { name: 'limit_paise', type: 'number' },
        { name: 'period',      type: 'string' },
        { name: 'is_active',   type: 'boolean' },
        { name: 'sync_status', type: 'string' },
        { name: 'created_at',  type: 'number' },
        { name: 'updated_at',  type: 'number' },
      ],
    }),
    tableSchema({
      name: 'sms_queue',
      columns: [
        { name: 'sender',       type: 'string' },
        { name: 'body',         type: 'string' },
        { name: 'message_hash', type: 'string', isIndexed: true },
        { name: 'received_at',  type: 'number' },
        { name: 'uploaded',     type: 'boolean' },
        { name: 'created_at',   type: 'number' },
      ],
    }),
  ],
});

// ─── Migrations ────────────────────────────────────────────────────────

export const migrations = schemaMigrations({
  migrations: [
    {
      toVersion: 2,
      steps: [
        addColumns({
          table: 'transactions',
          columns: [{ name: 'tags', type: 'string', isOptional: true }],
        }),
      ],
    },
  ],
});

// ─── Models ───────────────────────────────────────────────────────────

export class TransactionModel extends Model {
  static table = 'transactions';

  @field('client_id')      clientId!: string;
  @field('server_id')      serverId!: string | null;
  @field('amount_paise')   amountPaise!: number;
  @field('txn_type')       txnType!: string;
  @date('txn_date')        txnDate!: Date;
  @field('description')    description!: string;
  @field('category_id')    categoryId!: number | null;
  @field('merchant')       merchant!: string | null;
  @field('reference_id')   referenceId!: string | null;
  @field('upi_vpa')        upiVpa!: string | null;
  @field('bank_name')      bankName!: string | null;
  @field('account_masked') accountMasked!: string | null;
  @field('source')         source!: string;
  @field('notes')          notes!: string | null;
  @field('tags')           _tagsRaw!: string | null;
  @field('sync_status')    syncStatus!: string;
  @field('is_deleted')     isDeleted!: boolean;
  @readonly @date('created_at') createdAt!: Date;
  @readonly @date('updated_at') updatedAt!: Date;

  get tags(): string[] {
    if (!this._tagsRaw) return [];
    try { return JSON.parse(this._tagsRaw); } catch { return []; }
  }

  get amountRupees(): number {
    return this.amountPaise / 100;
  }

  @writer async softDelete(): Promise<void> {
    await this.update((rec) => {
      rec.isDeleted = true;
      rec.syncStatus = 'pending';
    });
  }

  @writer async markSynced(serverId: string): Promise<void> {
    await this.update((rec) => {
      rec.serverId = serverId;
      rec.syncStatus = 'synced';
    });
  }
}

export class CategoryModel extends Model {
  static table = 'categories';
  @field('server_id')  serverId!: number | null;
  @field('name')       name!: string;
  @field('icon')       icon!: string | null;
  @field('color')      color!: string | null;
  @field('is_income')  isIncome!: boolean;
  @field('sort_order') sortOrder!: number;
  @readonly @date('created_at') createdAt!: Date;
  @readonly @date('updated_at') updatedAt!: Date;
}

export class BudgetModel extends Model {
  static table = 'budgets';
  @field('server_id')   serverId!: number | null;
  @field('name')        name!: string;
  @field('category_id') categoryId!: number | null;
  @field('limit_paise') limitPaise!: number;
  @field('period')      period!: string;
  @field('is_active')   isActive!: boolean;
  @field('sync_status') syncStatus!: string;
  @readonly @date('created_at') createdAt!: Date;
  @readonly @date('updated_at') updatedAt!: Date;

  get limitRupees(): number { return this.limitPaise / 100; }
}

export class SmsQueueModel extends Model {
  static table = 'sms_queue';
  @field('sender')       sender!: string;
  @field('body')         body!: string;
  @field('message_hash') messageHash!: string;
  @date('received_at')   receivedAt!: Date;
  @field('uploaded')     uploaded!: boolean;
  @readonly @date('created_at') createdAt!: Date;
}

// ─── Database factory ─────────────────────────────────────────────────

let _db: Database | null = null;

export function getDatabase(): Database {
  if (_db) return _db;

  const adapter = new SQLiteAdapter({
    schema,
    migrations,
    /**
     * Fix #22: JSI disabled.
     *
     * JSI mode (~3x faster) requires native setup in:
     *   android/app/CMakeLists.txt  — add watermelondb-jsi target
     *   android/app/build.gradle   — add packagingOptions for jsi
     *
     * Once native setup is complete, change this back to: jsi: true
     * See: https://watermelondb.dev/docs/Installation#ios-and-android
     */
    jsi: false,
    onSetUpError: (error) => {
      console.error('[WatermelonDB] Setup error:', error);
    },
  });

  _db = new Database({
    adapter,
    modelClasses: [TransactionModel, CategoryModel, BudgetModel, SmsQueueModel],
  });

  return _db;
}

// ─── Query helpers ─────────────────────────────────────────────────────

export function pendingTransactions(db: Database) {
  return db
    .get<TransactionModel>('transactions')
    .query(Q.where('sync_status', 'pending'), Q.where('is_deleted', false));
}

export function recentTransactions(db: Database, limitDays = 30) {
  const since = Date.now() - limitDays * 24 * 3600 * 1000;
  return db
    .get<TransactionModel>('transactions')
    .query(
      Q.where('is_deleted', false),
      Q.where('txn_date', Q.gte(since)),
      Q.sortBy('txn_date', Q.desc),
    );
}
