"""app/config.py — Pydantic settings loaded from environment / .env"""
from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import List


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Core
    APP_VERSION: str = "1.0.0"
    ENV: str = "development"
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24       # 24 h
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database
    DATABASE_URL: str                                  # asyncpg URL
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_POOL_SIZE: int = 20

    # S3
    S3_ENDPOINT: str = "http://localhost:9000"
    S3_ACCESS_KEY: str = "paisa_minio"
    S3_SECRET_KEY: str = "paisa_minio_secret"
    S3_BUCKET_RECEIPTS: str = "paisa-receipts"
    S3_BUCKET_EXPORTS: str = "paisa-exports"

    # FCM / Push notifications
    FCM_SERVER_KEY: str = ""
    FIREBASE_CREDENTIALS_JSON: str = ""               # base64-encoded service account JSON

    # Idempotency key TTL (Redis)
    IDEMPOTENCY_TTL_SECONDS: int = 86_400             # 24 h

    # SMS processing
    SMS_MAX_RETRIES: int = 3
    SMS_RETRY_BACKOFF_BASE: float = 2.0               # exponential: base^attempt seconds
    SMS_QUEUE_MAX_CONCURRENCY: int = 10
    SMS_DEDUP_WINDOW_SECONDS: int = 300               # 5-min dedup window per device

    # Rate limiting
    RATE_LIMIT_PER_MINUTE: int = 60
    SMS_RATE_LIMIT_PER_MINUTE: int = 200              # higher — batch ingestion

    # Pagination
    DEFAULT_PAGE_SIZE: int = 25
    MAX_PAGE_SIZE: int = 100

    # Latency targets (ms) — used in tests
    TARGET_P99_LATENCY_MS: int = 500
    TARGET_P95_LATENCY_MS: int = 200

    # Observability
    JSON_LOGS: bool = True
    OTEL_ENABLED: bool = False
    OTEL_ENDPOINT: str = "http://localhost:4317"
    SENTRY_DSN: str = ""

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:8081"]

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
