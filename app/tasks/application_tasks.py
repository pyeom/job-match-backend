import logging

logger = logging.getLogger(__name__)


async def finalize_pending_application(ctx: dict, application_id: str) -> None:
    """
    ARQ task: fired 120s after a RIGHT swipe.
    - If swipe was undone: delete the PENDING application (clean up the stack)
    - If swipe is still active: promote PENDING -> ACTIVE and send notification
    """
    from uuid import UUID
    from sqlalchemy import select, delete as sql_delete
    from app.core.database import AsyncSessionLocal
    from app.models.application import Application
    from app.models.swipe import Swipe

    async with AsyncSessionLocal() as db:
        application = await db.get(Application, UUID(application_id))
        if not application or application.status != "PENDING":
            return  # Already finalized or manually removed

        # Check if the corresponding swipe is still active
        result = await db.execute(
            select(Swipe).where(
                Swipe.user_id == application.user_id,
                Swipe.job_id == application.job_id,
                Swipe.direction == "RIGHT",
                Swipe.is_undone == False,
            )
        )
        active_swipe = result.scalar_one_or_none()

        if not active_swipe:
            # Swipe was undone — clean up the PENDING application (safe: no notification FK)
            await db.execute(sql_delete(Application).where(Application.id == application.id))
            await db.commit()
            logger.info(f"Deleted PENDING application {application_id} — swipe was undone")
            return

        # Promote to ACTIVE
        application.status = "ACTIVE"
        await db.commit()
        logger.info(f"Promoted application {application_id} to ACTIVE")

        # Send notification (now safe: Application is ACTIVE and committed before creating FK reference)
        try:
            from app.services.notification_service import NotificationService
            notification_service = NotificationService()
            notification = await notification_service.create_new_application_notification(db, application.id)
            if notification:
                await db.commit()
                logger.info(f"Created notification {notification.id} for application {application_id}")
            else:
                logger.warning(f"Notification service returned None for application {application_id}")
        except Exception as e:
            logger.error(f"Failed to create notification for application {application_id}: {e}", exc_info=True)
