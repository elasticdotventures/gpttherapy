"""
Structured logging configuration using structlog.

This module configures structlog for use throughout the GPT Therapy application,
providing consistent, structured logging with proper JSON formatting for production
and readable console output for development.
"""

import logging
import sys
from typing import Any, cast

import structlog


def configure_structlog(
    log_level: str = "INFO", json_logs: bool = False, include_stdlib_logs: bool = True
) -> None:
    """
    Configure structlog for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        json_logs: Whether to output logs in JSON format (useful for production)
        include_stdlib_logs: Whether to include standard library logs in structured format
    """

    # Configure timestamping
    timestamper = structlog.processors.TimeStamper(fmt="ISO")

    # Configure common processors
    processors: list[Any] = [
        # Add log level and timestamp
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        timestamper,
        # Add stack info for exceptions
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        # Add call site information in development
        (
            structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            )
            if not json_logs
            else structlog.processors.CallsiteParameterAdder(
                [
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                ]
            )
        ),
    ]

    if json_logs:
        # Production JSON logging
        processors.extend([structlog.processors.JSONRenderer()])
    else:
        # Development console logging with colors
        processors.extend([structlog.dev.ConsoleRenderer(colors=True)])

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        context_class=dict,
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging if requested
    if include_stdlib_logs:
        formatter = structlog.stdlib.ProcessorFormatter(
            processor=(
                structlog.dev.ConsoleRenderer(colors=not json_logs)
                if not json_logs
                else structlog.processors.JSONRenderer()
            ),
        )

        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(formatter)

        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        root_logger.setLevel(getattr(logging, log_level.upper()))

        # Set levels for noisy third-party libraries
        logging.getLogger("boto3").setLevel(logging.WARNING)
        logging.getLogger("botocore").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """
    Get a configured structlog logger.

    Args:
        name: Logger name (defaults to calling module)

    Returns:
        Configured structlog logger
    """
    return cast(structlog.BoundLogger, structlog.get_logger(name))


def add_global_context(**kwargs: Any) -> None:
    """
    Add global context that will be included in all log messages.

    Args:
        **kwargs: Key-value pairs to add to global context
    """
    structlog.configure(context_class=dict, **kwargs)


# Context managers for temporary log context
class LogContext:
    """Context manager for adding temporary structured logging context."""

    def __init__(self, logger: structlog.BoundLogger, **context: Any):
        self.logger = logger
        self.context = context
        self.bound_logger: structlog.BoundLogger | None = None

    def __enter__(self) -> structlog.BoundLogger:
        self.bound_logger = self.logger.bind(**self.context)
        return self.bound_logger

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass


def with_context(logger: structlog.BoundLogger, **context: Any) -> LogContext:
    """
    Create a log context manager.

    Usage:
        logger = get_logger(__name__)
        with with_context(logger, session_id="123", user="test@example.com") as log:
            log.info("Processing request")
            # All log messages within this block will include session_id and user

    Args:
        logger: The base logger
        **context: Context to add to log messages

    Returns:
        LogContext manager
    """
    return LogContext(logger, **context)


# Lambda-specific logging setup
def configure_lambda_logging() -> None:
    """
    Configure structured logging specifically for AWS Lambda environment.
    Enables JSON logging and sets appropriate log levels.
    """
    from settings import settings

    configure_structlog(
        log_level=settings.LOG_LEVEL,
        json_logs=True,  # Always JSON in Lambda
        include_stdlib_logs=True,
    )

    # Add Lambda-specific global context
    if settings.IS_LAMBDA_ENV:
        add_global_context(
            lambda_function=settings.AWS_LAMBDA_FUNCTION_NAME,
            lambda_version=settings.AWS_LAMBDA_FUNCTION_VERSION,
            aws_region=settings.AWS_REGION,
        )


# Development logging setup
def configure_dev_logging() -> None:
    """
    Configure structured logging for development environment.
    Enables colored console output and debug logging.
    """
    from settings import settings

    # Use DEBUG level for development, unless explicitly set
    log_level = settings.LOG_LEVEL if settings.LOG_LEVEL != "INFO" else "DEBUG"

    configure_structlog(
        log_level=log_level,
        json_logs=False,  # Console-friendly in development
        include_stdlib_logs=True,
    )


# Auto-configuration based on environment
def auto_configure() -> None:
    """
    Automatically configure logging based on environment variables.
    """
    from settings import settings

    if settings.IS_LAMBDA_ENV:
        configure_lambda_logging()
    elif settings.IS_TEST_ENV:
        configure_dev_logging()
    else:
        # Default to development setup
        configure_dev_logging()


# Initialize logging when module is imported
auto_configure()
