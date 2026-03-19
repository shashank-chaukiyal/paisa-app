"""app/services/notification.py — Firebase Cloud Messaging push sender"""
from __future__ import annotations

import structlog
import httpx

log = structlog.get_logger(__name__)

FCM_ENDPOINT = "https://fcm.googleapis.com/fcm/send"


async def push_notification(
    token: str,
    title: str,
    body: str,
    data: dict | None = None,
    server_key: str | None = None,
) -> bool:
    """
    Send FCM push notification.
    Returns True on success, False on failure (non-raising — caller decides on retry).
    """
    from app.config import settings
    key = server_key or settings.FCM_SERVER_KEY

    if not key:
        log.warning("notification.fcm_key_missing")
        return False

    payload = {
        "to": token,
        "notification": {"title": title, "body": body, "sound": "default"},
        "data": data or {},
        "priority": "high",
        "content_available": True,
    }

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                FCM_ENDPOINT,
                json=payload,
                headers={
                    "Authorization": f"key={key}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("success") == 1:
                log.info("notification.sent", title=title)
                return True
            log.warning("notification.fcm_error", result=result)
        else:
            log.error("notification.http_error", status=resp.status_code)
    except Exception as exc:
        log.error("notification.exception", error=str(exc))

    return False
