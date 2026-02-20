"""
Push notification service for sending Expo Push Notifications.

This module handles sending push notifications via the Expo Push API,
including batch sending, error handling, and token validation.
"""

from __future__ import annotations
from typing import List, Optional, Dict, Any
from uuid import UUID
import logging
import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.push_token_repository import PushTokenRepository

logger = logging.getLogger(__name__)

# Expo Push API endpoint
EXPO_PUSH_ENDPOINT = "https://exp.host/--/api/v2/push/send"

# Max notifications per batch (Expo recommends max 100)
MAX_BATCH_SIZE = 100

# Error types from Expo that indicate invalid/inactive tokens
INVALID_TOKEN_ERRORS = {
    "DeviceNotRegistered",
    "InvalidCredentials",
    "MessageTooBig"  # Indicates token format issue
}


class PushNotificationService:
    """
    Service for sending push notifications via Expo Push API.

    This service coordinates push notification operations including:
    - Sending individual and batch notifications
    - Handling Expo API errors
    - Managing token validation and deactivation
    - Retry logic for transient failures
    """

    def __init__(
        self,
        push_token_repo: Optional[PushTokenRepository] = None
    ):
        """
        Initialize service with repository.

        Args:
            push_token_repo: PushTokenRepository instance
        """
        self.push_token_repo = push_token_repo or PushTokenRepository()

    async def send_to_user(
        self,
        db: AsyncSession,
        user_id: UUID,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "default",
        sound: str = "default",
        badge: Optional[int] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Send push notification to all active devices of a user.

        Args:
            db: Database session
            user_id: UUID of the user
            title: Notification title
            body: Notification body
            data: Optional data payload
            priority: Priority (default, normal, high)
            sound: Sound to play (default or null for silent)
            badge: Badge count to display

        Returns:
            Dictionary with send results: {sent: int, failed: int, errors: List}
        """
        # Get all active tokens for user
        tokens = await self.push_token_repo.get_active_tokens_for_user(db, user_id)

        if not tokens:
            logger.info(f"No active push tokens for user {user_id}")
            return {"sent": 0, "failed": 0, "errors": []}

        # Create push messages for each token
        messages = [
            {
                "to": token.token,
                "title": title,
                "body": body,
                "data": data or {},
                "priority": priority,
                "sound": sound,
                "badge": badge
            }
            for token in tokens
        ]

        # Send in batches
        return await self._send_batch(db, messages, http_client=http_client)

    async def send_to_company(
        self,
        db: AsyncSession,
        company_id: UUID,
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "default",
        sound: str = "default",
        badge: Optional[int] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Send push notification to all active devices of a company.

        Args:
            db: Database session
            company_id: UUID of the company
            title: Notification title
            body: Notification body
            data: Optional data payload
            priority: Priority (default, normal, high)
            sound: Sound to play (default or null for silent)
            badge: Badge count to display

        Returns:
            Dictionary with send results
        """
        # Get all active tokens for company
        tokens = await self.push_token_repo.get_active_tokens_for_company(db, company_id)

        if not tokens:
            logger.info(f"No active push tokens for company {company_id}")
            return {"sent": 0, "failed": 0, "errors": []}

        # Create push messages
        messages = [
            {
                "to": token.token,
                "title": title,
                "body": body,
                "data": data or {},
                "priority": priority,
                "sound": sound,
                "badge": badge
            }
            for token in tokens
        ]

        # Send in batches
        return await self._send_batch(db, messages, http_client=http_client)

    async def send_to_tokens(
        self,
        db: AsyncSession,
        tokens: List[str],
        title: str,
        body: str,
        data: Optional[Dict[str, Any]] = None,
        priority: str = "default",
        sound: str = "default",
        badge: Optional[int] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Send push notification to specific tokens.

        Args:
            db: Database session
            tokens: List of Expo push tokens
            title: Notification title
            body: Notification body
            data: Optional data payload
            priority: Priority (default, normal, high)
            sound: Sound to play
            badge: Badge count

        Returns:
            Dictionary with send results
        """
        if not tokens:
            return {"sent": 0, "failed": 0, "errors": []}

        messages = [
            {
                "to": token,
                "title": title,
                "body": body,
                "data": data or {},
                "priority": priority,
                "sound": sound,
                "badge": badge
            }
            for token in tokens
        ]

        return await self._send_batch(db, messages, http_client=http_client)

    async def _send_batch(
        self,
        db: AsyncSession,
        messages: List[Dict[str, Any]],
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> Dict[str, Any]:
        """
        Send push notifications in batches to Expo Push API.

        Args:
            db: Database session
            messages: List of push message objects

        Returns:
            Dictionary with aggregated results
        """
        total_sent = 0
        total_failed = 0
        all_errors = []

        # Split into batches of MAX_BATCH_SIZE
        for i in range(0, len(messages), MAX_BATCH_SIZE):
            batch = messages[i:i + MAX_BATCH_SIZE]

            try:
                # Use the provided persistent client if available; otherwise create a
                # short-lived one for this batch.  When using a persistent client we
                # intentionally do NOT close it here — the caller owns its lifecycle.
                if http_client is not None:
                    response = await http_client.post(
                        EXPO_PUSH_ENDPOINT,
                        json=batch,
                        headers={
                            "Accept": "application/json",
                            "Content-Type": "application/json"
                        },
                    )
                else:
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        response = await client.post(
                            EXPO_PUSH_ENDPOINT,
                            json=batch,
                            headers={
                                "Accept": "application/json",
                                "Content-Type": "application/json"
                            },
                        )

                if response.status_code == 200:
                    result = response.json()
                    receipts = result.get("data", [])

                    # Process receipts
                    for idx, receipt in enumerate(receipts):
                        if receipt.get("status") == "ok":
                            total_sent += 1
                        else:
                            total_failed += 1
                            error_type = receipt.get("details", {}).get("error")
                            error_message = receipt.get("message", "Unknown error")

                            # Log error
                            logger.warning(
                                f"Push notification failed: {error_type} - {error_message}"
                            )
                            all_errors.append({
                                "token": batch[idx]["to"],
                                "error": error_type,
                                "message": error_message
                            })

                            # Deactivate token if it's invalid
                            if error_type in INVALID_TOKEN_ERRORS:
                                await self._deactivate_token(db, batch[idx]["to"])

                else:
                    # API error
                    logger.error(
                        f"Expo Push API error: {response.status_code} - {response.text}"
                    )
                    total_failed += len(batch)
                    all_errors.append({
                        "error": "API_ERROR",
                        "message": f"Status {response.status_code}",
                        "count": len(batch)
                    })

            except httpx.TimeoutException:
                logger.error("Timeout sending push notifications")
                total_failed += len(batch)
                all_errors.append({
                    "error": "TIMEOUT",
                    "message": "Request timed out",
                    "count": len(batch)
                })

            except Exception as e:
                logger.error(f"Error sending push notifications: {e}")
                total_failed += len(batch)
                all_errors.append({
                    "error": "EXCEPTION",
                    "message": str(e),
                    "count": len(batch)
                })

        # Commit token deactivations
        await db.commit()

        return {
            "sent": total_sent,
            "failed": total_failed,
            "errors": all_errors
        }

    async def _deactivate_token(self, db: AsyncSession, token: str):
        """
        Deactivate an invalid push token.

        Args:
            db: Database session
            token: Expo push token to deactivate
        """
        try:
            deactivated = await self.push_token_repo.deactivate_token(db, token)
            if deactivated:
                logger.info(f"Deactivated invalid push token: {token[:20]}...")
        except Exception as e:
            logger.error(f"Error deactivating token: {e}")
