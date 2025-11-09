"""
WebSocket API endpoints for real-time notifications.

This module provides the WebSocket endpoint for establishing
real-time connections for notification delivery.
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import json
from typing import Optional
from uuid import UUID
import asyncio

from app.core.database import get_db
from app.core.websocket_manager import connection_manager
from app.core.security import decode_token
from sqlalchemy import select
from app.models.user import User
from app.models.company import Company

logger = logging.getLogger(__name__)

router = APIRouter()


async def authenticate_websocket(token: str, db: AsyncSession) -> Optional[tuple[str, UUID]]:
    """
    Authenticate a WebSocket connection using JWT token.

    Args:
        token: JWT token string
        db: Database session

    Returns:
        Tuple of (owner_type, owner_id) if valid, None otherwise
        owner_type is "user" or "company"
    """
    try:
        # Decode JWT token
        payload = decode_token(token)
        if not payload:
            return None

        subject = payload.get("sub")
        if not subject:
            return None

        # Convert subject to UUID
        try:
            user_uuid = UUID(subject)
        except (ValueError, TypeError):
            return None

        # Check if it's a user (try to get user by ID)
        result = await db.execute(select(User).where(User.id == user_uuid))
        user = result.scalar_one_or_none()
        if user:
            # If user has a company_id, they're a company user
            if user.company_id:
                return ("company", user.company_id)
            return ("user", user.id)

        return None

    except Exception as e:
        logger.error(f"WebSocket authentication error: {e}")
        return None


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    db: AsyncSession = Depends(get_db)
):
    """
    WebSocket endpoint for real-time notifications.

    Protocol:
    1. Client connects
    2. Client sends authentication message with JWT token
    3. Server responds with authenticated message or error
    4. Server sends periodic ping messages
    5. Client responds with pong messages
    6. Server sends notification events as they occur
    """
    authenticated = False
    owner_type = None
    owner_id = None
    heartbeat_task = None

    try:
        await websocket.accept()

        # Wait for authentication message (with timeout)
        try:
            auth_message = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            await websocket.send_json({
                "type": "error",
                "message": "Authentication timeout"
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Validate authentication message
        if auth_message.get("type") != "authenticate":
            await websocket.send_json({
                "type": "error",
                "message": "First message must be authentication"
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        token = auth_message.get("token")
        if not token:
            await websocket.send_json({
                "type": "error",
                "message": "Token is required"
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        # Authenticate
        auth_result = await authenticate_websocket(token, db)
        if not auth_result:
            await websocket.send_json({
                "type": "error",
                "message": "Invalid or expired token"
            })
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        owner_type, owner_id = auth_result

        # Register connection
        await connection_manager.connect(websocket, owner_type, owner_id)
        authenticated = True

        # Send authentication success
        await websocket.send_json({
            "type": "authenticated",
            f"{owner_type}_id": str(owner_id),
            "message": "Successfully authenticated"
        })

        logger.info(f"WebSocket authenticated: {owner_type}={owner_id}")

        # Start heartbeat task
        heartbeat_task = asyncio.create_task(send_heartbeat(websocket))

        # Listen for messages
        while True:
            try:
                message = await websocket.receive_json()

                # Handle pong
                if message.get("type") == "pong":
                    connection_manager.update_pong(websocket)

                # Handle other message types (future expansion)
                # e.g., message filtering preferences, acknowledgments, etc.

            except WebSocketDisconnect:
                logger.info(f"WebSocket disconnected: {owner_type}={owner_id}")
                break
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "code": "INVALID_MESSAGE_FORMAT",
                    "message": "Message must be valid JSON"
                })
            except Exception as e:
                logger.error(f"Error processing WebSocket message: {e}")
                break

    except Exception as e:
        logger.error(f"WebSocket error: {e}")

    finally:
        # Clean up
        if authenticated:
            connection_manager.disconnect(websocket)

        # Cancel heartbeat task
        if heartbeat_task:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def send_heartbeat(websocket: WebSocket, interval: int = 30):
    """
    Send periodic ping messages to keep connection alive.

    Args:
        websocket: WebSocket connection
        interval: Seconds between pings
    """
    try:
        while True:
            await asyncio.sleep(interval)
            await websocket.send_json({"type": "ping"})
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")
