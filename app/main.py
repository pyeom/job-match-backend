import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import uuid4

import structlog
from app.core.logging import configure_logging

logger = logging.getLogger(__name__)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from app.core.config import settings

configure_logging(app_env=settings.app_env)

# Log active configuration at startup (secrets are masked)
settings.log_config()
from app.api.v1 import auth, jobs, swipes, applications, users, companies, notifications, filters
from app.api.v1 import websocket, media, documents, ai
from app.core.database import engine
from app.core.cache import get_redis, close_redis_pool
from app.services.embedding_service import embedding_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logger.info("Starting up Job Match backend...")

    # 1. Verify database connectivity
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.error("Database connection failed at startup: %s", e)
        if settings.app_env == "production":
            raise RuntimeError(f"Cannot start: database unreachable: {e}") from e

    # 2. Verify Redis connectivity
    try:
        r = await get_redis()
        await r.ping()
        logger.info("Redis connection verified")
    except Exception as e:
        logger.error("Redis connection failed at startup: %s", e)
        if settings.app_env == "production":
            raise RuntimeError(f"Cannot start: Redis unreachable: {e}") from e

    # 3. Verify Elasticsearch connectivity and ensure index exists
    from app.services.elasticsearch_service import elasticsearch_service
    try:
        index_created = await elasticsearch_service.ensure_index()
        logger.info("Elasticsearch index ready")
        if index_created:
            # Enqueue background bulk reindex of existing jobs
            from app.core.arq import get_arq_pool
            arq_pool = await get_arq_pool()
            await arq_pool.enqueue_job("reindex_all_jobs")
            logger.info("Enqueued bulk Elasticsearch reindex task")
    except Exception as e:
        logger.error("Elasticsearch initialization failed: %s", e)
        if settings.app_env == "production":
            raise RuntimeError(f"Cannot start: Elasticsearch unreachable: {e}") from e

    # 4. Pre-load embedding model (fail hard in production, warn in dev)
    logger.info("Loading embedding model: %s", settings.embedding_model)
    try:
        await asyncio.to_thread(embedding_service.ensure_loaded)
        logger.info("Embedding model loaded successfully")
    except Exception as e:
        if settings.app_env == "production":
            raise RuntimeError(f"Cannot start: embedding model failed to load: {e}") from e
        logger.warning("Embedding model failed to load — running degraded: %s", e)

    # 5. Start WebSocket Redis pub/sub listener for cross-instance delivery
    from app.core.websocket_manager import connection_manager
    await connection_manager.start_pubsub_listener()

    logger.info("Startup complete")
    yield  # ── Application running ────────────────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────────
    logger.info("Shutting down...")

    # Stop pub/sub listener before closing connections
    await connection_manager.stop_pubsub_listener()

    # Close all active WebSocket connections with a proper close frame so
    # clients receive a clean disconnect rather than a sudden TCP reset.
    from app.core.websocket_manager import connection_manager
    active_connections = connection_manager.get_all_connections()
    if active_connections:
        logger.info("Closing %d active WebSocket connection(s)...", len(active_connections))
        close_tasks = [
            ws.close(code=1001, reason="Server shutting down")
            for ws in active_connections
        ]
        await asyncio.gather(*close_tasks, return_exceptions=True)
        logger.info("All WebSocket connections closed")

    from app.services.elasticsearch_service import elasticsearch_service
    await elasticsearch_service.close()
    await close_redis_pool()
    logger.info("Shutdown complete")


_is_prod = settings.app_env == "production"
app = FastAPI(
    title="Job Match API",
    description="FastAPI + ML backend for job matching application",
    version="1.0.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
    lifespan=lifespan,
)

# Add CORS middleware with explicit method and header allowlist.
# allow_origin_regex covers ngrok tunnels used during local development —
# their subdomains rotate so they cannot be hardcoded in allowed_origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_origin_regex=r"https://.*\.ngrok-free\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "Accept",
        "X-Request-ID",
        "ngrok-skip-browser-warning",  # injected by api.ts when backend URL is a ngrok tunnel
    ],
    expose_headers=["X-Request-ID"],
)


@app.middleware("http")
async def request_timeout_middleware(request: Request, call_next):
    """Return HTTP 504 if any request takes longer than 30 seconds."""
    try:
        return await asyncio.wait_for(call_next(request), timeout=30.0)
    except asyncio.TimeoutError:
        logger.warning(
            "Request timed out after 30s: %s %s",
            request.method,
            request.url.path,
        )
        return JSONResponse({"error": "Request timeout"}, status_code=504)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add standard security headers to every response."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Assign a unique request ID to every request for end-to-end tracing."""
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    request.state.request_id = request_id
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# Include API routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(users.router, prefix="/api/v1/users", tags=["Users"])
app.include_router(jobs.router, prefix="/api/v1/jobs", tags=["Jobs"])  # Job seeker endpoints (discover, view)
app.include_router(companies.router, prefix="/api/v1/companies", tags=["Companies"])  # Company endpoints with nested job management
app.include_router(swipes.router, prefix="/api/v1/swipes", tags=["Swipes"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])  # User notifications
app.include_router(filters.router, prefix="/api/v1/filters", tags=["Filters"])  # Filter presets and suggestions
# Applications endpoints: user-specific RESTful routes only.
app.include_router(applications.router, prefix="/api/v1/users", tags=["User Applications"])
# TODO: The duplicate registration below under /api/v1/applications was removed (Task 7.9).
# All clients must use the /api/v1/users/{user_id}/applications routes instead.
# app.include_router(applications.router, prefix="/api/v1/applications", tags=["Applications (Legacy)"], deprecated=True)
# Document management endpoints
app.include_router(documents.router, prefix="/api/v1/documents", tags=["Documents"])
# WebSocket endpoint for real-time notifications
app.include_router(websocket.router, tags=["WebSocket"])
# Media serving endpoint for avatars and other files
app.include_router(media.router, prefix="/api/v1/media", tags=["Media"])
# AI-powered features (match explanations, insights)
app.include_router(ai.router, prefix="/api/v1/ai", tags=["AI Features"])


@app.get("/healthz")
async def health_check():
    """Health check endpoint (liveness — always returns 200 if the process is alive)"""
    return {"status": "ok", "version": "1.0.0"}


@app.get("/healthz/live")
async def liveness():
    """Kubernetes liveness probe — is the process alive?"""
    return {"status": "ok"}


@app.get("/healthz/ready")
async def readiness():
    """Kubernetes readiness probe — is the app ready to serve traffic?"""
    checks: dict[str, str] = {}

    try:
        async with engine.begin() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    try:
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    checks["embedding_model"] = "ok" if embedding_service.is_loaded else "not_loaded"

    from app.services.elasticsearch_service import elasticsearch_service
    try:
        info = await elasticsearch_service.client.cluster.health()
        checks["elasticsearch"] = "ok" if info["status"] in ("green", "yellow") else f"status:{info['status']}"
    except Exception as e:
        checks["elasticsearch"] = f"error: {e}"

    all_ok = all(v == "ok" for v in checks.values())
    status_code = 200 if all_ok else 503
    return JSONResponse(
        {"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=status_code,
    )


@app.get("/")
async def root():
    """Root endpoint"""
    return {"message": "Job Match API", "docs": "/docs"}