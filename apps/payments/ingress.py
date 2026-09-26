"""Accept a webhook quickly. The Celery task does the booking update."""

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.payments.models import ProcessingStatus, WebhookEvent
from apps.payments.tasks import KNOWN_EVENTS, process_webhook_event

logger = logging.getLogger(__name__)


def accept_webhook(*, event_id: str, event_type: str, payload: dict) -> dict:
    """Store the event once and enqueue it. Repeats return duplicate with no side effects."""
    ignored = event_type not in KNOWN_EVENTS
    defaults = {
        "event_type": event_type,
        "payload": payload,
        "processing_status": ProcessingStatus.IGNORED if ignored else ProcessingStatus.RECEIVED,
        "processed_at": timezone.now() if ignored else None,
    }
    try:
        with transaction.atomic():
            event, created = WebhookEvent.objects.get_or_create(
                event_id=event_id,
                defaults=defaults,
            )
    except IntegrityError:
        event = WebhookEvent.objects.get(event_id=event_id)
        created = False

    if not created:
        logger.info("webhook_duplicate", extra={"event_id": event_id})
        return {"status": "duplicate", "event_id": event_id}

    if ignored:
        logger.info("webhook_received", extra={"event_id": event_id, "ignored": True})
        return {"status": "ignored", "event_id": event_id}

    logger.info("webhook_received", extra={"event_id": event_id, "event_type": event_type})
    process_webhook_event.delay(event.event_id)
    return {"status": "accepted"}
