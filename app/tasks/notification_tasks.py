import logging
from uuid import UUID

from arq.worker import Retry

from app.core.database import AsyncSessionLocal
from app.models.notification import DeliveryStatus

logger = logging.getLogger(__name__)


async def deliver_push_notification(
    ctx: dict,
    target_type: str,
    target_id: str,
    title: str,
    body: str,
    data: dict,
) -> None:
    """
    ARQ task: deliver a push notification to a user or company.

    target_type: "user" | "company"
    Uses exponential backoff on failure: defer = job_try ** 2 seconds
    (1 s, 4 s, 9 s for tries 1, 2, 3).
    On final failure (job_try >= max_tries) the notification's delivery_status
    is set to 'failed' in the database.
    """
    from app.services.push_notification_service import PushNotificationService

    http_client = ctx.get("http_client")
    push_service = PushNotificationService()
    notification_id_str: str | None = data.get("notification_id")

    async with AsyncSessionLocal() as db:
        try:
            if target_type == "user":
                await push_service.send_to_user(
                    db=db,
                    user_id=UUID(target_id),
                    title=title,
                    body=body,
                    data=data,
                    priority="high",
                    http_client=http_client,
                )
                logger.debug(f"Delivered push notification to user {target_id}")
            elif target_type == "company":
                await push_service.send_to_company(
                    db=db,
                    company_id=UUID(target_id),
                    title=title,
                    body=body,
                    data=data,
                    priority="high",
                    http_client=http_client,
                )
                logger.debug(f"Delivered push notification to company {target_id}")
            else:
                logger.error(f"Unknown target_type '{target_type}' for push notification")
                return

            # Mark notification as delivered in the database
            if notification_id_str:
                await _update_delivery_status(db, notification_id_str, DeliveryStatus.delivered)

        except Exception as e:
            logger.error(
                f"Failed to deliver push notification to {target_type} {target_id} "
                f"(try {ctx.get('job_try', '?')}): {e}",
                exc_info=True,
            )

            max_tries: int = ctx.get("job_settings", {}).get("max_tries", 3) if isinstance(ctx.get("job_settings"), dict) else 3
            job_try: int = ctx.get("job_try", 1)

            if job_try >= max_tries:
                # Final attempt failed — persist the failure status
                if notification_id_str:
                    async with AsyncSessionLocal() as fail_db:
                        await _update_delivery_status(fail_db, notification_id_str, DeliveryStatus.failed)
            else:
                # Exponential backoff: 1 s → 4 s → 9 s for tries 1, 2, 3
                raise Retry(defer=job_try ** 2)


async def _update_delivery_status(db, notification_id_str: str, status: DeliveryStatus) -> None:
    """Update the delivery_status column for a notification row."""
    from sqlalchemy import update as sql_update
    from app.models.notification import Notification

    try:
        stmt = (
            sql_update(Notification)
            .where(Notification.id == UUID(notification_id_str))
            .values(delivery_status=status)
        )
        await db.execute(stmt)
        await db.commit()
        logger.debug(f"Set delivery_status={status.value} for notification {notification_id_str}")
    except Exception as update_err:
        logger.error(
            f"Failed to update delivery_status for notification {notification_id_str}: {update_err}",
            exc_info=True,
        )
