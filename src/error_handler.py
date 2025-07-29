"""
Centralized error handling and logging utilities for GPT Therapy.

Provides structured error handling, logging with context, and error recovery patterns.
"""

import traceback
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

# Import structured logging configuration
from datetime_utils import timestamps, utc_now
from logging_config import get_logger

logger = get_logger(__name__)


class ErrorType(Enum):
    """Enumeration of error types for structured logging and handling."""

    SESSION_NOT_FOUND = "session_not_found"
    PLAYER_NOT_FOUND = "player_not_found"
    INVALID_TURN = "invalid_turn"
    STORAGE_ERROR = "storage_error"
    AI_GENERATION_ERROR = "ai_generation_error"
    EMAIL_PROCESSING_ERROR = "email_processing_error"
    VALIDATION_ERROR = "validation_error"
    TIMEOUT_ERROR = "timeout_error"
    EXTERNAL_SERVICE_ERROR = "external_service_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ErrorContext:
    """Structured error context for logging and debugging."""

    error_type: ErrorType
    session_id: str | None = None
    player_email: str | None = None
    turn_number: int | None = None
    message_id: str | None = None
    request_id: str | None = None
    timestamp: str | None = None
    additional_data: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = timestamps.now()


class GPTTherapyError(Exception):
    """Base exception class for GPT Therapy application errors."""

    def __init__(
        self,
        message: str,
        error_type: ErrorType = ErrorType.UNKNOWN_ERROR,
        context: ErrorContext | None = None,
        recoverable: bool = True,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.context = context or ErrorContext(error_type=error_type)
        self.recoverable = recoverable


class SessionError(GPTTherapyError):
    """Session-related errors."""

    def __init__(self, message: str, session_id: str, **kwargs: Any) -> None:
        context = ErrorContext(
            error_type=ErrorType.SESSION_NOT_FOUND, session_id=session_id
        )
        super().__init__(message, ErrorType.SESSION_NOT_FOUND, context, **kwargs)


class PlayerError(GPTTherapyError):
    """Player-related errors."""

    def __init__(
        self,
        message: str,
        player_email: str,
        session_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        context = ErrorContext(
            error_type=ErrorType.PLAYER_NOT_FOUND,
            player_email=player_email,
            session_id=session_id,
        )
        super().__init__(message, ErrorType.PLAYER_NOT_FOUND, context, **kwargs)


class TurnError(GPTTherapyError):
    """Turn processing errors."""

    def __init__(
        self,
        message: str,
        session_id: str,
        player_email: str,
        turn_number: int | None = None,
        **kwargs: Any,
    ) -> None:
        context = ErrorContext(
            error_type=ErrorType.INVALID_TURN,
            session_id=session_id,
            player_email=player_email,
            turn_number=turn_number,
        )
        super().__init__(message, ErrorType.INVALID_TURN, context, **kwargs)


class StorageError(GPTTherapyError):
    """Storage operation errors."""

    def __init__(
        self, message: str, operation: str | None = None, **kwargs: Any
    ) -> None:
        context = ErrorContext(
            error_type=ErrorType.STORAGE_ERROR,
            additional_data={"operation": operation} if operation else None,
        )
        super().__init__(message, ErrorType.STORAGE_ERROR, context, **kwargs)


def log_error(
    error: Exception, context: ErrorContext | None = None, level: str = "ERROR"
) -> str:
    """
    Log an error with structured context information.

    Args:
        error: The exception to log
        context: Optional error context
        level: Log level (ERROR, WARNING, CRITICAL)

    Returns:
        Error ID for tracking
    """
    error_id = f"err_{int(utc_now().timestamp())}"

    # Build structured log data
    log_data = {
        "error_id": error_id,
        "error_message": str(error),
        "error_type": getattr(error, "error_type", ErrorType.UNKNOWN_ERROR).value,
        "error_class": error.__class__.__name__,
        "traceback": traceback.format_exc(),
        "recoverable": getattr(error, "recoverable", True),
    }

    # Add context if available
    if context:
        log_data.update(asdict(context))
    elif hasattr(error, "context") and error.context:
        log_data.update(asdict(error.context))

    # Log with structured data
    if level == "CRITICAL":
        logger.critical(f"Critical error: {error.__class__.__name__}", **log_data)
    elif level == "WARNING":
        logger.warning(f"Warning: {error.__class__.__name__}", **log_data)
    else:
        logger.error(f"Error: {error.__class__.__name__}", **log_data)

    return error_id


def handle_error(
    error: Exception,
    context: ErrorContext | None = None,
    notify_user: bool = True,
    user_email: str | None = None,
) -> dict[str, Any]:
    """
    Centralized error handling with logging, user notification, and recovery.

    Args:
        error: The exception to handle
        context: Optional error context
        notify_user: Whether to send user notification
        user_email: User email for notifications

    Returns:
        Error response dictionary
    """
    error_id = log_error(error, context)

    # Determine if error is recoverable
    is_recoverable = getattr(error, "recoverable", True)
    error_type = getattr(error, "error_type", ErrorType.UNKNOWN_ERROR)

    # Build response
    response = {
        "error_id": error_id,
        "error_type": error_type.value,
        "message": str(error),
        "recoverable": is_recoverable,
        "timestamp": context.timestamp if context else timestamps.now(),
    }

    # Add context info if available
    if context:
        response["context"] = {
            "session_id": context.session_id,
            "player_email": context.player_email,
            "turn_number": context.turn_number,
        }

    # Send user notification if requested
    if notify_user and user_email:
        try:
            send_error_notification(user_email, error_type, error_id, str(error))
        except Exception as e:
            logger.critical(
                "Failed to send error notification",
                notification_error=str(e),
                target_email=user_email,
                original_error_id=error_id,
            )

    return response


def send_error_notification(
    user_email: str, error_type: ErrorType, error_id: str, error_message: str
) -> None:
    """
    Send error notification to user (placeholder - would integrate with email system).

    Args:
        user_email: User's email address
        error_type: Type of error
        error_id: Error tracking ID
        error_message: Human-readable error message
    """
    # This would integrate with the actual email sending system
    logger.info(
        "Error notification would be sent",
        target_email=user_email,
        error_type=error_type.value,
        error_id=error_id,
        error_message=error_message,
    )


def create_error_context(
    session_id: str | None = None,
    player_email: str | None = None,
    turn_number: int | None = None,
    message_id: str | None = None,
    request_id: str | None = None,
    **additional_data: Any,
) -> ErrorContext:
    """
    Convenience function to create error context.

    Args:
        session_id: Session identifier
        player_email: Player email address
        turn_number: Turn number
        message_id: Email message ID
        request_id: Request/correlation ID
        **additional_data: Additional context data

    Returns:
        ErrorContext object
    """
    return ErrorContext(
        error_type=ErrorType.UNKNOWN_ERROR,  # Will be overridden by specific error
        session_id=session_id,
        player_email=player_email,
        turn_number=turn_number,
        message_id=message_id,
        request_id=request_id,
        additional_data=additional_data if additional_data else None,
    )


def with_error_handling(func: Any) -> Any:
    """
    Decorator for adding error handling to functions.

    Usage:
        @with_error_handling
        def my_function():
            # Function code that might raise exceptions
            pass
    """

    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except GPTTherapyError as e:
            # Already structured error - just log and re-raise
            log_error(e)
            raise
        except Exception as e:
            # Convert to structured error
            logger.error(
                "Unhandled error in function",
                function_name=func.__name__,
                error_message=str(e),
                exc_info=True,
            )
            structured_error = GPTTherapyError(
                f"Unexpected error in {func.__name__}: {str(e)}",
                ErrorType.UNKNOWN_ERROR,
            )
            raise structured_error from e

    return wrapper


class ErrorMetrics:
    """Simple error metrics tracking."""

    def __init__(self) -> None:
        self.error_counts: dict[str, int] = {}
        self.last_errors: list[dict[str, Any]] = []
        self.max_recent_errors = 100

    def record_error(
        self, error_type: ErrorType, session_id: str | None = None
    ) -> None:
        """Record an error occurrence."""
        key = error_type.value
        self.error_counts[key] = self.error_counts.get(key, 0) + 1

        self.last_errors.append(
            {
                "error_type": error_type.value,
                "session_id": session_id,
                "timestamp": timestamps.now(),
            }
        )

        # Keep only recent errors
        if len(self.last_errors) > self.max_recent_errors:
            self.last_errors = self.last_errors[-self.max_recent_errors :]

    def get_error_summary(self) -> dict[str, Any]:
        """Get error metrics summary."""
        return {
            "total_errors": sum(self.error_counts.values()),
            "error_counts": self.error_counts.copy(),
            "recent_errors": len(self.last_errors),
            "most_common": (
                max(self.error_counts.items(), key=lambda x: x[1])
                if self.error_counts
                else None
            ),
        }


# Global error metrics instance
error_metrics = ErrorMetrics()
