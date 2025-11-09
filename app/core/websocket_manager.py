"""
WebSocket connection manager for real-time notifications.

This module manages active WebSocket connections, authentication,
and broadcasting of notifications to connected clients.
"""

from typing import Dict, Set, Optional
from fastapi import WebSocket
from uuid import UUID
import logging
import asyncio
from datetime import datetime

logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time notifications.

    Tracks connections by user_id and company_id, handles broadcasting,
    and implements connection health checks via ping/pong.
    """

    def __init__(self):
        # user_id → Set[WebSocket]
        self.user_connections: Dict[UUID, Set[WebSocket]] = {}

        # company_id → Set[WebSocket]
        self.company_connections: Dict[UUID, Set[WebSocket]] = {}

        # WebSocket → user_id or company_id (for cleanup)
        self.connection_owners: Dict[WebSocket, tuple[str, UUID]] = {}

        # WebSocket → last_pong_time (for health checks)
        self.last_pong: Dict[WebSocket, datetime] = {}

    async def connect(
        self,
        websocket: WebSocket,
        owner_type: str,  # "user" or "company"
        owner_id: UUID
    ):
        """
        Register a new WebSocket connection.

        Args:
            websocket: WebSocket instance
            owner_type: "user" or "company"
            owner_id: UUID of user or company
        """
        await websocket.accept()

        if owner_type == "user":
            if owner_id not in self.user_connections:
                self.user_connections[owner_id] = set()
            self.user_connections[owner_id].add(websocket)
        elif owner_type == "company":
            if owner_id not in self.company_connections:
                self.company_connections[owner_id] = set()
            self.company_connections[owner_id].add(websocket)

        self.connection_owners[websocket] = (owner_type, owner_id)
        self.last_pong[websocket] = datetime.utcnow()

        logger.info(f"WebSocket connected: {owner_type}={owner_id}")

    def disconnect(self, websocket: WebSocket):
        """
        Remove a WebSocket connection.

        Args:
            websocket: WebSocket instance to remove
        """
        if websocket not in self.connection_owners:
            return

        owner_type, owner_id = self.connection_owners[websocket]

        if owner_type == "user" and owner_id in self.user_connections:
            self.user_connections[owner_id].discard(websocket)
            if not self.user_connections[owner_id]:
                del self.user_connections[owner_id]

        elif owner_type == "company" and owner_id in self.company_connections:
            self.company_connections[owner_id].discard(websocket)
            if not self.company_connections[owner_id]:
                del self.company_connections[owner_id]

        del self.connection_owners[websocket]
        self.last_pong.pop(websocket, None)

        logger.info(f"WebSocket disconnected: {owner_type}={owner_id}")

    async def send_to_user(self, user_id: UUID, message: dict):
        """
        Send a message to all connections for a specific user.

        Args:
            user_id: UUID of the user
            message: Dictionary to send as JSON
        """
        if user_id not in self.user_connections:
            logger.debug(f"No active connections for user {user_id}")
            return

        connections = self.user_connections[user_id].copy()
        disconnected = []

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to user {user_id}: {e}")
                disconnected.append(websocket)

        # Clean up failed connections
        for ws in disconnected:
            self.disconnect(ws)

    async def send_to_company(self, company_id: UUID, message: dict):
        """
        Send a message to all connections for a specific company.

        Args:
            company_id: UUID of the company
            message: Dictionary to send as JSON
        """
        if company_id not in self.company_connections:
            logger.debug(f"No active connections for company {company_id}")
            return

        connections = self.company_connections[company_id].copy()
        disconnected = []

        for websocket in connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error sending to company {company_id}: {e}")
                disconnected.append(websocket)

        # Clean up failed connections
        for ws in disconnected:
            self.disconnect(ws)

    async def broadcast_to_all(self, message: dict):
        """
        Broadcast a message to all connected clients.

        Args:
            message: Dictionary to send as JSON
        """
        all_connections = set()
        for connections in self.user_connections.values():
            all_connections.update(connections)
        for connections in self.company_connections.values():
            all_connections.update(connections)

        disconnected = []
        for websocket in all_connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error(f"Error broadcasting: {e}")
                disconnected.append(websocket)

        for ws in disconnected:
            self.disconnect(ws)

    def update_pong(self, websocket: WebSocket):
        """Update last pong time for connection health tracking."""
        self.last_pong[websocket] = datetime.utcnow()

    def get_connection_count(self) -> dict:
        """Get statistics about active connections."""
        user_count = sum(len(conns) for conns in self.user_connections.values())
        company_count = sum(len(conns) for conns in self.company_connections.values())

        return {
            "total_connections": user_count + company_count,
            "user_connections": user_count,
            "company_connections": company_count,
            "unique_users": len(self.user_connections),
            "unique_companies": len(self.company_connections)
        }


# Global singleton instance
connection_manager = ConnectionManager()
