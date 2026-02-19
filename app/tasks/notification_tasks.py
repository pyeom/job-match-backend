import logging
from uuid import UUID

from app.core.database import AsyncSessionLocal

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
    Raises on failure so ARQ will retry up to max_tries times.
    """
    from app.services.push_notification_service import PushNotificationService

    push_service = PushNotificationService()

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
                )
                logger.debug(f"Delivered push notification to company {target_id}")
            else:
                logger.error(f"Unknown target_type '{target_type}' for push notification")
        except Exception as e:
            logger.error(
                f"Failed to deliver push notification to {target_type} {target_id}: {e}",
                exc_info=True,
            )
            raise  # Let ARQ retry
