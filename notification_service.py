"""
notification_service.py — Firebase Cloud Messaging (FCM) push notifications.

Initialises the Firebase Admin SDK lazily on first use.  When
FIREBASE_CREDENTIALS_PATH is not set the service degrades gracefully:
all send calls return a result that indicates Firebase is not configured
rather than raising an exception.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

from config import FIREBASE_CREDENTIALS_PATH

logger = logging.getLogger(__name__)

_firebase_initialized: bool = False
_firebase_available: bool = False


def _init_firebase() -> bool:
    """
    Initialise the Firebase Admin SDK (once).

    Returns True when Firebase is ready to send messages, False otherwise.
    """
    global _firebase_initialized, _firebase_available

    if _firebase_initialized:
        return _firebase_available

    _firebase_initialized = True

    if not FIREBASE_CREDENTIALS_PATH:
        logger.warning(
            "FIREBASE_CREDENTIALS_PATH is not set; push notifications are disabled. "
            "Set the environment variable to a Firebase service-account JSON path to enable them."
        )
        _firebase_available = False
        return False

    try:
        import firebase_admin  # type: ignore[import-untyped]
        from firebase_admin import credentials  # type: ignore[import-untyped]

        if not firebase_admin._apps:
            cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
            firebase_admin.initialize_app(cred)

        _firebase_available = True
        logger.info("Firebase Admin SDK initialised successfully.")
        return True

    except Exception as exc:
        logger.error("Failed to initialise Firebase Admin SDK: %s", exc)
        _firebase_available = False
        return False


def send_hazard_notifications_batch(
    tokens_with_alerts: List[Dict[str, str]],
) -> Dict[str, Any]:
    """
    Send hazard-alert push notifications to a list of FCM device tokens.

    Args:
        tokens_with_alerts: List of dicts, each with keys:
            ``token``    — FCM registration token
            ``event``    — e.g. "Tornado Warning"
            ``severity`` — e.g. "Extreme"

    Returns:
        A dict with keys:
            ``success_count``       — number of messages sent successfully
            ``failure_count``       — number of messages that failed
            ``firebase_configured`` — whether Firebase was available
            ``results``             — per-token outcome list
    """
    if not tokens_with_alerts:
        return {
            "success_count": 0,
            "failure_count": 0,
            "firebase_configured": _firebase_available,
            "results": [],
        }

    if not _init_firebase():
        return {
            "success_count": 0,
            "failure_count": len(tokens_with_alerts),
            "firebase_configured": False,
            "results": [
                {
                    "token_preview": item["token"][:20] + "...",
                    "success": False,
                    "error": "Firebase not configured",
                }
                for item in tokens_with_alerts
            ],
        }

    try:
        from firebase_admin import messaging  # type: ignore[import-untyped]

        messages = [
            messaging.Message(
                notification=messaging.Notification(
                    title="⚠️ Weather Hazard Alert",
                    body=f"{item.get('event', 'Weather Alert')} — Severity: {item.get('severity', 'Unknown')}",
                ),
                data={
                    "event": item.get("event", ""),
                    "severity": item.get("severity", ""),
                    "type": "hazard_alert",
                },
                token=item["token"],
            )
            for item in tokens_with_alerts
        ]

        # FCM batch limit is 500 messages; chunk larger lists.
        BATCH_SIZE = 500
        success_count = 0
        failure_count = 0
        results: List[Dict[str, Any]] = []

        for batch_start in range(0, len(messages), BATCH_SIZE):
            batch = messages[batch_start : batch_start + BATCH_SIZE]
            batch_items = tokens_with_alerts[batch_start : batch_start + BATCH_SIZE]

            batch_response = messaging.send_each(batch)

            for idx, send_response in enumerate(batch_response.responses):
                preview = batch_items[idx]["token"][:20] + "..."
                if send_response.success:
                    success_count += 1
                    results.append({"token_preview": preview, "success": True})
                else:
                    failure_count += 1
                    results.append(
                        {
                            "token_preview": preview,
                            "success": False,
                            "error": str(send_response.exception),
                        }
                    )

        return {
            "success_count": success_count,
            "failure_count": failure_count,
            "firebase_configured": True,
            "results": results,
        }

    except Exception as exc:
        logger.error("Batch notification send failed: %s", exc)
        return {
            "success_count": 0,
            "failure_count": len(tokens_with_alerts),
            "firebase_configured": True,
            "results": [],
            "error": str(exc),
        }
