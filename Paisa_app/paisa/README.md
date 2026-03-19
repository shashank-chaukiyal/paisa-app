# Paisa — Mobile Finance Tracker

> Production-grade Android finance app with SMS interception, UPI tracking, offline-first sync, biometric security, and real-time push alerts.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Android App (React Native 0.76 + Kotlin native modules)        │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐ │
│  │ SMS Receiver  │  │  Biometric   │  │  WatermelonDB         │ │
│  │ (Kotlin BR)  │  │  Auth (JSI)  │  │  Offline-first SQLite │ │
│  └──────┬───────┘  └──────────────┘  └───────────┬───────────┘ │
│         │ NativeEventEmitter                      │ Sync Engine │
│  ┌──────▼───────────────────────────────────────▼────────────┐  │
│  │              React Native UI Layer                         │  │
│  │  Zustand (global) + React Query (server state)            │  │
│  └──────────────────────────┬──────────────────────────────┘  │
└─────────────────────────────┼───────────────────────────────────┘
                              │ HTTPS (mTLS in prod)
┌─────────────────────────────▼───────────────────────────────────┐
│  FastAPI Backend (Cloudflare Workers → EC2 → bare metal path)   │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐  │
│  │ Auth (JWT +  │  │ SMS Ingest   │  │  Sync Engine         │  │
│  │ biometric    │  │ /api/v1/sms  │  │  cursor-paginated    │  │
│  │ sig verify)  │  │ → Celery Q   │  │  delta sync          │  │
│  └──────────────┘  └──────┬───────┘  └──────────────────────┘  │
│                           │                                     │
│  ┌──────────────┐  ┌──────▼───────┐  ┌──────────────────────┐  │
│  │  PostgreSQL  │  │  Redis       │  │  Celery Workers      │  │
│  │  + Alembic   │  │  Queue+Cache │  │  SMS Parse + Alerts  │  │
│  └──────────────┘  └──────────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Engineering Decisions

### Why paise (integer) for all money?
Floating-point errors accumulate in finance. `float(1.10) + float(2.20) ≠ 3.30`.
All amounts are stored and transported as **INTEGER PAISE** (1 INR = 100 paise).
API accepts and returns paise. Display layer divides by 100. No rounding risk.

### Why cursor pagination over OFFSET?
`OFFSET N` requires the DB to scan and discard N rows — O(N) cost that grows with page depth.
Cursor encodes `(updated_at, id)` and uses a `WHERE (updated_at, id) < (cur_ts, cur_id)` keyset seek.
With a composite index on `(user_id, updated_at)` this is O(log N) regardless of page depth.
Stable under concurrent writes — OFFSET skips rows inserted between requests.

### Why WatermelonDB for offline-first?
- JSI bridge (not async bridge) → ~3x faster than AsyncStorage
- Lazy loading — only loads records you observe
- Built-in sync protocol that maps to our cursor-based pull API
- SQLite under the hood → works offline with zero changes to query code

### Why Celery for SMS processing?
SMS arrives as a burst (e.g. 30 messages when the user installs and backfills).
Celery provides:
- **Backpressure**: `--concurrency=4` caps parallel DB writes
- **Retries**: exponential backoff 2^n seconds with jitter
- **Visibility**: Flower dashboard shows queue depth, failure rate
- **Dead-letter**: maxRetries exceeded → error_queue for manual review

### Idempotency (3 layers)
1. **Client**: `client_id` UUID generated on device, sent with every transaction
2. **API**: `X-Idempotency-Key` header + Redis lock prevents double-processing
3. **DB**: `UNIQUE(user_id, client_id)` constraint — database rejects true duplicates

### Conflict resolution (sync)
- **Server wins** on: amount, txn_type, txn_date, source, bank fields (authoritative from SMS)
- **Client wins** on: notes, tags, category_id (user intent)
- Implemented via per-field last-write-wins with field-level timestamps in sync payload

---

## Latency Targets & Cost Ceilings

| Endpoint | P50 target | P95 target | P99 ceiling |
|---|---|---|---|
| `GET /api/v1/transactions` | < 50ms | < 200ms | < 500ms |
| `POST /api/v1/transactions` | < 100ms | < 300ms | < 800ms |
| `POST /api/v1/sms/ingest` | < 50ms | < 150ms | < 400ms |
| `GET /api/v1/sync/pull` | < 80ms | < 250ms | < 600ms |
| `POST /api/v1/sync/push` | < 120ms | < 400ms | < 1000ms |
| SMS parse (Celery) | < 200ms | < 500ms | < 2s |

**Cost ceiling (solo/small team):**
- Supabase Pro: ~$25/month (1GB DB, 50GB bandwidth)
- Redis (Upstash): ~$0 – $10/month (pay per request)
- FCM: Free for all volumes
- **Total infra: < $50/month** at 10,000 MAU

---

## Observability

Every request has:
- `X-Request-ID` header (UUID, propagated to all log lines)
- Structured JSON logs via `structlog` (shipped to Loki or CloudWatch)
- Prometheus metrics at `/metrics` (latency histograms, SMS parse success rate)
- Celery task visibility via Flower at `:5555`

Key metrics to alert on:
```
# SMS parse failure rate (alert if > 10%)
rate(paisa_sms_processed_total{status="parse_failed"}[5m])
  / rate(paisa_sms_processed_total[5m]) > 0.10

# API P99 latency breach
histogram_quantile(0.99, paisa_http_request_duration_seconds) > 0.5

# Queue depth (alert if > 100 pending SMS)
celery_queue_length{queue="sms_processing"} > 100
```

---

## Quick Start

### Prerequisites
- Docker + Docker Compose
- Node.js 18+
- Android Studio (for mobile)
- JDK 17

### Backend
```bash
cd backend
cp .env.example .env          # fill in SECRET_KEY, FCM creds
docker compose up -d db redis minio

pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload

# Start Celery workers
celery -A app.workers.celery_app worker --loglevel=info -Q sms_processing,notifications,sync
```

### Mobile
```bash
cd mobile
npm install
npx react-native run-android

# To test SMS on emulator:
adb shell am broadcast -a android.provider.Telephony.SMS_RECEIVED \
  --es "pdus" "$(python3 scripts/encode_sms_pdu.py 'HDFCBK' 'Rs.500 debited from A/c XX1234')"
```

---

## Android Permissions Required

```xml
<!-- AndroidManifest.xml -->
<uses-permission android:name="android.permission.RECEIVE_SMS" />
<uses-permission android:name="android.permission.READ_SMS" />
<uses-permission android:name="android.permission.USE_BIOMETRIC" />
<uses-permission android:name="android.permission.USE_FINGERPRINT" />
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECEIVE_BOOT_COMPLETED" />
<uses-permission android:name="android.permission.VIBRATE" />
```

---

## Schema Migrations

```bash
# Create new migration
alembic revision --autogenerate -m "add_savings_goals_table"

# Apply to development
alembic upgrade head

# Rollback one step
alembic downgrade -1

# Check current version
alembic current

# Never edit existing migration files after they've been applied to production.
```

---

## Security

- JWT access tokens: 24h expiry, RS256 signed
- Refresh tokens: 30-day expiry, SHA-256 hashed in DB, device-bound
- Biometric: ECDSA key pair in Android StrongBox; server verifies signature
- All DB queries: parameterized (SQLAlchemy ORM — no raw SQL with user input)
- SMS body never logged in plain text after processing (only hash + parse result)
- Secrets: `.env` file, never committed; production via AWS Secrets Manager / Doppler

---

## Project Structure

```
paisa/
├── backend/
│   ├── app/
│   │   ├── main.py                # FastAPI app factory, middleware
│   │   ├── config.py              # Pydantic settings
│   │   ├── database.py            # AsyncSession factory
│   │   ├── redis_client.py        # Redis pool
│   │   ├── models/
│   │   │   └── transaction.py     # All SQLAlchemy ORM models
│   │   ├── api/v1/
│   │   │   ├── auth.py            # Login, refresh, biometric enroll
│   │   │   ├── transactions.py    # CRUD + batch + cursor pagination
│   │   │   ├── sms.py             # SMS ingest → Celery queue
│   │   │   ├── budgets.py         # Budget CRUD
│   │   │   ├── analytics.py       # Spending trends, category breakdown
│   │   │   └── sync.py            # Delta sync push/pull
│   │   ├── services/
│   │   │   ├── sms_parser.py      # Regex SMS parser (10 banks)
│   │   │   ├── notification.py    # FCM push notification sender
│   │   │   └── upi.py             # UPI VPA validation + enrichment
│   │   ├── workers/
│   │   │   ├── celery_app.py      # Celery configuration
│   │   │   └── tasks.py           # SMS processing, alerts, digest
│   │   └── middleware/
│   │       ├── auth.py            # JWT + biometric signature verify
│   │       └── logging.py         # structlog configuration
│   ├── alembic/versions/
│   │   └── 0001_initial_schema.py
│   ├── tests/
│   │   ├── unit/test_sms_parser.py
│   │   └── integration/test_transactions.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── .env.example
│
├── mobile/
│   ├── android/
│   │   └── app/src/main/java/com/paisa/
│   │       ├── sms/SmsReceiver.kt      # BroadcastReceiver
│   │       ├── sms/SmsModule.kt        # RN native module bridge
│   │       └── sms/SmsLocalDb.kt       # Local SQLite buffer
│   ├── src/
│   │   ├── navigation/             # Stack + Tab navigators
│   │   ├── screens/                # All UI screens
│   │   ├── services/
│   │   │   ├── api.ts              # Axios instance + interceptors
│   │   │   ├── sms.ts              # SMS listener + upload
│   │   │   ├── biometric.ts        # Biometric auth + key management
│   │   │   └── sync.ts             # WatermelonDB sync engine
│   │   ├── stores/
│   │   │   └── db.ts               # WatermelonDB schema + models
│   │   └── utils/
│   │       ├── logger.ts           # Structured logger
│   │       ├── device.ts           # Stable device ID
│   │       └── currency.ts         # Paise ↔ rupees formatting
│   └── package.json
│
└── docker-compose.yml
```

---

## SMS Parser Coverage

| Bank | Debit | Credit | UPI VPA | Balance | Ref No |
|---|---|---|---|---|---|
| HDFC | ✅ | ✅ | ✅ | ✅ | ✅ |
| SBI | ✅ | ✅ | ✅ | ✅ | ✅ |
| ICICI | ✅ | ✅ | ✅ | ✅ | ✅ |
| Axis | ✅ | ✅ | ✅ | ✅ | ✅ |
| Kotak | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| Paytm | ✅ | ✅ | ✅ | ❌ | ✅ |
| PhonePe | ✅ | ✅ | ✅ | ❌ | ✅ |
| Google Pay | ✅ | ✅ | ✅ | ❌ | ✅ |
| Yes Bank | ✅ | ✅ | ⚠️ | ✅ | ✅ |
| PNB | ✅ | ✅ | ⚠️ | ✅ | ✅ |

Parse confidence threshold: **0.70** — below this, SMS is logged but no transaction is created.

---

## 1–3 Month Roadmap (Solo Engineer)

**Month 1 — Core**
- [ ] FastAPI backend + PostgreSQL + Alembic migrations
- [ ] JWT auth + PIN login
- [ ] Manual transaction CRUD (API + mobile UI)
- [ ] WatermelonDB offline-first setup + delta sync

**Month 2 — Automation**
- [ ] SMS BroadcastReceiver + parser for top 5 banks
- [ ] Celery SMS processing pipeline
- [ ] Biometric auth (fingerprint + face)
- [ ] FCM push notifications + budget alerts

**Month 3 — Polish**
- [ ] UPI deep link tracking
- [ ] Analytics dashboard (monthly trends, category breakdown)
- [ ] CSV export to S3
- [ ] Prometheus + Grafana observability
- [ ] Play Store submission (Android)
