"""app/workers/celery_app.py — Celery instance + beat schedule"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "paisa",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,      # fair dispatch — one task per worker slot
    task_routes={
        "tasks.process_sms": {"queue": "sms_processing"},
        "tasks.check_budget_alerts": {"queue": "notifications"},
        "tasks.send_daily_digest": {"queue": "notifications"},
    },
    beat_schedule={
        "daily-digest-8pm-ist": {
            "task": "tasks.send_daily_digest",
            "schedule": 86400,         # every 24h; align with cron in production
        },
    },
    # Dead-letter: failed tasks after max_retries → error_queue
    task_reject_on_worker_lost=True,
    task_default_queue="default",
)
