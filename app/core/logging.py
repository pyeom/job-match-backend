"""
Structured logging configuration using structlog.

In development (app_env=dev): colored console output.
In all other environments: JSON output with timestamp, level, message, and all bound context vars (including request_id).

Usage:
    from app.core.logging import configure_logging
    configure_logging(app_env="dev")

    # In any module:
    import structlog
    logger = structlog.get_logger(__name__)
    logger.info("event happened", user_id=str(user_id), job_id=str(job_id))

    # Existing stdlib loggers also work and produce structured output automatically.
    import logging
    logger = logging.getLogger(__name__)
    logger.info("existing log line")  # also structured

Request ID is injected per-request via structlog.contextvars in the middleware:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)
"""

import logging
import sys

import structlog


def configure_logging(app_env: str = "dev") -> None:
    """
    Configure structlog with a stdlib bridge so all loggers (including
    uvicorn, sqlalchemy, etc.) produce structured output.

    Args:
        app_env: Application environment. "dev" → ConsoleRenderer; anything else → JSONRenderer.
    """
    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]

    if app_env == "dev":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=shared_processors,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = []
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)

    # Suppress noisy third-party loggers in production
    if app_env != "dev":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
