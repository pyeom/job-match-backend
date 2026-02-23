"""
WebSocket connection manager for real-time notifications.

This module manages active WebSocket connections, authentication,
and broadcasting of notifications to connected clients.

Multi-server delivery is handled via Redis pub/sub:
- send_to_user / send_to_company deliver to local connections first
  (fast path), then publish to a Redis channel so other instances
  can deliver to their local connections.
- Messages sent while a recipient has no connections on any instance
  are persisted in a Redis list (offline queue, 24-hour TTL) and
  flushed to the client on their next WebSocket connect.
"""

import json
import asyncio
import uuid as _uuid_module
from typing import Dict, Set, Optional
from fastapi import WebSocket
from uuid import UUID
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Unique identifier for this process instance — used to suppress
# re-delivery of messages that were already sent via the local fast path.
_INSTANCE_ID = str(_uuid_module.uuid4())

_OFFLINE_QUEUE_TTL = 86_400  # 24 hours in seconds


class ConnectionManager:
    """
    Manages WebSocket connections for real-time notifications.

    Tracks connections by user_id and company_id, handles broadcasting,
    implements connection health checks via ping/pong, and uses Redis
    pub/sub for cross-instance message delivery.
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

        # WebSocket → JWT token (for periodic re-validation)
        self.connection_tokens: Dict[WebSocket, str] = {}

        # Background pub/sub listener task
        self._pubsub_task: Optional[asyncio.Task] = None

    # ── Connection lifecycle ──────────────────────────────────────────────────

    async def connect(
        self,
        websocket: WebSocket,
        owner_type: str,  # "user" or "company"
        owner_id: UUID,
        token: str = "",
    ):
        """
        Register a new WebSocket connection and drain any offline queue.

        NOTE: websocket.accept() should be called BEFORE this method.
        """
        logger.info(
            "[ConnectionManager] Registering connection — type: %s, id: %s",
            owner_type,
            owner_id,
        )

        if owner_type == "user":
            if owner_id not in self.user_connections:
                self.user_connections[owner_id] = set()
            self.user_connections[owner_id].add(websocket)
            logger.info(
                "[ConnectionManager] ✅ user_connections[%s] — total: %d",
                owner_id,
                len(self.user_connections[owner_id]),
            )
        elif owner_type == "company":
            if owner_id not in self.company_connections:
                self.company_connections[owner_id] = set()
            self.company_connections[owner_id].add(websocket)
            logger.info(
                "[ConnectionManager] ✅ company_connections[%s] — total: %d",
                owner_id,
                len(self.company_connections[owner_id]),
            )

        self.connection_owners[websocket] = (owner_type, owner_id)
        self.last_pong[websocket] = datetime.utcnow()
        self.connection_tokens[websocket] = token

        logger.info(
            "[ConnectionManager] ✅ registered: %s=%s | users=%d companies=%d",
            owner_type,
            owner_id,
            len(self.user_connections),
            len(self.company_connections),
        )

        # Drain offline queue so the client receives any messages that
        # arrived while they were disconnected.
        await self._drain_offline_queue(websocket, owner_type, owner_id)

    async def _drain_offline_queue(
        self, websocket: WebSocket, owner_type: str, owner_id: UUID
    ):
        """Send queued offline messages to a freshly connected client."""
        offline_key = _offline_key(owner_type, owner_id)
        try:
            from app.core.cache import get_redis

            r = await get_redis()
            msgs = await r.lrange(offline_key, 0, -1)
            if not msgs:
                return
            logger.info(
                "[ConnectionManager] Draining %d offline message(s) for %s=%s",
                len(msgs),
                owner_type,
                owner_id,
            )
            for raw in msgs:
                try:
                    await websocket.send_text(raw)
                except Exception as e:
                    logger.warning(
                        "[ConnectionManager] Offline drain send failed: %s", e
                    )
                    break
            await r.delete(offline_key)
        except Exception as e:
            logger.warning("[ConnectionManager] Offline queue drain error: %s", e)

    async def revalidate_token(self, websocket: WebSocket) -> bool:
        """
        Re-validate the JWT token stored for a connection.

        Checks whether the token is still valid and not blacklisted.
        If validation fails, closes the WebSocket with code 1008 and
        disconnects it from the manager.
        """
        from app.core.security import verify_token

        token = self.connection_tokens.get(websocket)
        if not token:
            logger.warning("[ConnectionManager] revalidate_token: no token found")
            try:
                await websocket.close(code=1008)
            except Exception:
                pass
            self.disconnect(websocket)
            return False

        result = await verify_token(token)
        if result is None:
            logger.info(
                "[ConnectionManager] revalidate_token: token expired or revoked"
            )
            try:
                await websocket.close(code=1008, reason="Token expired or revoked")
            except Exception:
                pass
            self.disconnect(websocket)
            return False

        return True

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket not in self.connection_owners:
            logger.debug("[ConnectionManager] Disconnect called for untracked websocket")
            return

        owner_type, owner_id = self.connection_owners[websocket]
        logger.info("[ConnectionManager] Disconnecting %s=%s", owner_type, owner_id)

        if owner_type == "user" and owner_id in self.user_connections:
            self.user_connections[owner_id].discard(websocket)
            remaining = len(self.user_connections[owner_id])
            if not self.user_connections[owner_id]:
                del self.user_connections[owner_id]
            logger.info(
                "[ConnectionManager] user_connections[%s] remaining: %d",
                owner_id,
                remaining,
            )

        elif owner_type == "company" and owner_id in self.company_connections:
            self.company_connections[owner_id].discard(websocket)
            remaining = len(self.company_connections[owner_id])
            if not self.company_connections[owner_id]:
                del self.company_connections[owner_id]
            logger.info(
                "[ConnectionManager] company_connections[%s] remaining: %d",
                owner_id,
                remaining,
            )

        del self.connection_owners[websocket]
        self.last_pong.pop(websocket, None)
        self.connection_tokens.pop(websocket, None)

        logger.info(
            "[ConnectionManager] ✅ disconnected: %s=%s | users=%d companies=%d",
            owner_type,
            owner_id,
            len(self.user_connections),
            len(self.company_connections),
        )

    # ── Local delivery helpers ────────────────────────────────────────────────

    async def _deliver_local_user(self, user_id: UUID, message: dict) -> int:
        """Deliver *message* to all local connections for *user_id*.

        Returns the number of websockets successfully written to.
        """
        if user_id not in self.user_connections:
            return 0

        connections = self.user_connections[user_id].copy()
        delivered = 0
        disconnected = []

        for ws in connections:
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception as e:
                logger.error(
                    "[WebSocketManager] send_json failed for user %s: %s", user_id, e
                )
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

        return delivered

    async def _deliver_local_company(self, company_id: UUID, message: dict) -> int:
        """Deliver *message* to all local connections for *company_id*.

        Returns the number of websockets successfully written to.
        """
        if company_id not in self.company_connections:
            return 0

        connections = self.company_connections[company_id].copy()
        delivered = 0
        disconnected = []

        for ws in connections:
            try:
                await ws.send_json(message)
                delivered += 1
            except Exception as e:
                logger.error(
                    "[WebSocketManager] send_json failed for company %s: %s",
                    company_id,
                    e,
                )
                disconnected.append(ws)

        for ws in disconnected:
            self.disconnect(ws)

        return delivered

    # ── Public send methods ───────────────────────────────────────────────────

    async def send_to_user(self, user_id: UUID, message: dict):
        """
        Send *message* to all connections for *user_id*.

        Delivery order:
        1. Local connections on this instance (fast path).
        2. Publish to Redis channel ``ws:user:{user_id}`` so other
           instances can deliver to their local connections.
        3. If this instance has no local connections for the user, push
           *message* to the offline queue (Redis list, 24-hour TTL).
           The queue is drained the next time the user connects.
        """
        logger.info(
            "[WebSocketManager] send_to_user %s | local_users=%d",
            user_id,
            len(self.user_connections),
        )

        local_count = await self._deliver_local_user(user_id, message)

        try:
            from app.core.cache import get_redis

            r = await get_redis()
            # Tag with instance ID so the pub/sub listener on this same
            # instance skips re-delivery (already handled above).
            tagged = {**message, "_src": _INSTANCE_ID}
            await r.publish(f"ws:user:{user_id}", json.dumps(tagged))

            if local_count == 0:
                key = _offline_key("user", user_id)
                await r.rpush(key, json.dumps(message))
                await r.expire(key, _OFFLINE_QUEUE_TTL)
                logger.debug(
                    "[WebSocketManager] Queued offline message for user %s", user_id
                )
        except Exception as e:
            logger.error(
                "[WebSocketManager] Redis error in send_to_user %s: %s", user_id, e
            )

    async def send_to_company(self, company_id: UUID, message: dict):
        """
        Send *message* to all connections for *company_id*.

        Same multi-instance delivery semantics as :meth:`send_to_user`.
        """
        local_count = await self._deliver_local_company(company_id, message)

        try:
            from app.core.cache import get_redis

            r = await get_redis()
            tagged = {**message, "_src": _INSTANCE_ID}
            await r.publish(f"ws:company:{company_id}", json.dumps(tagged))

            if local_count == 0:
                key = _offline_key("company", company_id)
                await r.rpush(key, json.dumps(message))
                await r.expire(key, _OFFLINE_QUEUE_TTL)
                logger.debug(
                    "[WebSocketManager] Queued offline message for company %s",
                    company_id,
                )
        except Exception as e:
            logger.error(
                "[WebSocketManager] Redis error in send_to_company %s: %s",
                company_id,
                e,
            )

    async def broadcast_to_all(self, message: dict):
        """Broadcast a message to all locally connected clients."""
        all_connections: set[WebSocket] = set()
        for connections in self.user_connections.values():
            all_connections.update(connections)
        for connections in self.company_connections.values():
            all_connections.update(connections)

        disconnected = []
        for websocket in all_connections:
            try:
                await websocket.send_json(message)
            except Exception as e:
                logger.error("[WebSocketManager] broadcast error: %s", e)
                disconnected.append(websocket)

        for ws in disconnected:
            self.disconnect(ws)

    # ── Redis pub/sub listener ────────────────────────────────────────────────

    async def start_pubsub_listener(self):
        """Launch the Redis pub/sub background task (idempotent)."""
        if self._pubsub_task and not self._pubsub_task.done():
            logger.debug("[ConnectionManager] pub/sub listener already running")
            return
        self._pubsub_task = asyncio.create_task(
            self._pubsub_loop(), name="ws-pubsub-listener"
        )
        logger.info("[ConnectionManager] Redis pub/sub listener started (instance=%s)", _INSTANCE_ID)

    async def stop_pubsub_listener(self):
        """Cancel and await the Redis pub/sub background task."""
        if self._pubsub_task and not self._pubsub_task.done():
            self._pubsub_task.cancel()
            try:
                await self._pubsub_task
            except asyncio.CancelledError:
                pass
        self._pubsub_task = None
        logger.info("[ConnectionManager] Redis pub/sub listener stopped")

    async def _pubsub_loop(self):
        """
        Persistent pub/sub listener that subscribes to ``ws:user:*`` and
        ``ws:company:*`` channels and forwards messages to local WebSocket
        connections.

        Reconnects automatically with exponential back-off on any error.
        """
        from app.core.cache import get_redis

        retry_delay = 1.0

        while True:
            pubsub = None
            try:
                r = await get_redis()
                pubsub = r.pubsub()
                await pubsub.psubscribe("ws:user:*", "ws:company:*")
                logger.info(
                    "[ConnectionManager] pub/sub subscribed to ws:user:* and ws:company:*"
                )

                async for raw_msg in pubsub.listen():
                    if raw_msg["type"] != "pmessage":
                        continue

                    channel: str = raw_msg["channel"]

                    try:
                        data: dict = json.loads(raw_msg["data"])
                    except (json.JSONDecodeError, TypeError) as exc:
                        logger.warning(
                            "[ConnectionManager] pub/sub bad JSON on %s: %s",
                            channel,
                            exc,
                        )
                        continue

                    # Skip messages that originated from this instance —
                    # they were already delivered via the local fast path.
                    src = data.pop("_src", None)
                    if src == _INSTANCE_ID:
                        continue

                    await self._route_pubsub_message(channel, data, r)

                # If listen() returns normally (shouldn't happen), reset delay
                retry_delay = 1.0

            except asyncio.CancelledError:
                logger.info("[ConnectionManager] pub/sub listener cancelled")
                return
            except Exception as exc:
                logger.error(
                    "[ConnectionManager] pub/sub error — retry in %.1fs: %s",
                    retry_delay,
                    exc,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 30.0)
            finally:
                if pubsub is not None:
                    try:
                        await pubsub.close()
                    except Exception:
                        pass

    async def _route_pubsub_message(self, channel: str, data: dict, r):
        """Parse a pub/sub channel name and deliver *data* to local connections."""
        # channel format: ws:user:<uuid>  or  ws:company:<uuid>
        parts = channel.split(":")
        if len(parts) < 3:
            logger.warning("[ConnectionManager] Unexpected channel format: %s", channel)
            return

        owner_type = parts[1]  # "user" or "company"
        try:
            owner_id = UUID(parts[2])
        except ValueError:
            logger.warning(
                "[ConnectionManager] Invalid UUID in channel %s", channel
            )
            return

        if owner_type == "user":
            delivered = await self._deliver_local_user(owner_id, data)
            if delivered > 0:
                # User is connected here — clear offline queue
                try:
                    await r.delete(_offline_key("user", owner_id))
                except Exception:
                    pass

        elif owner_type == "company":
            delivered = await self._deliver_local_company(owner_id, data)
            if delivered > 0:
                try:
                    await r.delete(_offline_key("company", owner_id))
                except Exception:
                    pass

    # ── Utility methods ───────────────────────────────────────────────────────

    def update_pong(self, websocket: WebSocket):
        """Update last pong time for connection health tracking."""
        self.last_pong[websocket] = datetime.utcnow()

    def get_all_connections(self) -> list[WebSocket]:
        """Return a flat list of all active WebSocket connections."""
        all_connections: list[WebSocket] = []
        for conns in self.user_connections.values():
            all_connections.extend(conns)
        for conns in self.company_connections.values():
            all_connections.extend(conns)
        return all_connections

    def get_connection_count(self) -> dict:
        """Get statistics about active connections."""
        user_count = sum(len(c) for c in self.user_connections.values())
        company_count = sum(len(c) for c in self.company_connections.values())
        return {
            "total_connections": user_count + company_count,
            "user_connections": user_count,
            "company_connections": company_count,
            "unique_users": len(self.user_connections),
            "unique_companies": len(self.company_connections),
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _offline_key(owner_type: str, owner_id: UUID) -> str:
    """Return the Redis key for an owner's offline message queue."""
    return f"ws:offline:{owner_type}:{owner_id}"


# Global singleton instance
connection_manager = ConnectionManager()
