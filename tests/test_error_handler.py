"""
Tests for error handling utilities.
"""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest

from src.error_handler import (
    ErrorContext,
    ErrorMetrics,
    ErrorType,
    GPTTherapyError,
    PlayerError,
    SessionError,
    StorageError,
    TurnError,
    create_error_context,
    handle_error,
    log_error,
    with_error_handling,
)


class TestErrorTypes:
    """Test error type enumerations."""

    def test_error_types_exist(self) -> None:
        """Test that all required error types are defined."""
        assert ErrorType.SESSION_NOT_FOUND
        assert ErrorType.PLAYER_NOT_FOUND
        assert ErrorType.INVALID_TURN
        assert ErrorType.STORAGE_ERROR
        assert ErrorType.AI_GENERATION_ERROR
        assert ErrorType.EMAIL_PROCESSING_ERROR
        assert ErrorType.VALIDATION_ERROR
        assert ErrorType.TIMEOUT_ERROR
        assert ErrorType.EXTERNAL_SERVICE_ERROR
        assert ErrorType.UNKNOWN_ERROR


class TestErrorContext:
    """Test error context data structure."""

    def test_error_context_creation(self) -> None:
        """Test creating error context."""
        context = ErrorContext(
            error_type=ErrorType.SESSION_NOT_FOUND,
            session_id="test-123",
            player_email="player@example.com",
        )

        assert context.error_type == ErrorType.SESSION_NOT_FOUND
        assert context.session_id == "test-123"
        assert context.player_email == "player@example.com"
        assert context.timestamp is not None

    def test_error_context_auto_timestamp(self) -> None:
        """Test that timestamp is automatically set."""
        context = ErrorContext(error_type=ErrorType.UNKNOWN_ERROR)

        assert context.timestamp is not None
        # Timestamp should be recent
        timestamp_dt = datetime.fromisoformat(context.timestamp.replace("Z", "+00:00"))
        now = datetime.now(UTC)
        assert (now - timestamp_dt).total_seconds() < 1


class TestCustomExceptions:
    """Test custom exception classes."""

    def test_gpt_therapy_error(self) -> None:
        """Test base GPTTherapyError."""
        error = GPTTherapyError("Test error", ErrorType.UNKNOWN_ERROR)

        assert str(error) == "Test error"
        assert error.error_type == ErrorType.UNKNOWN_ERROR
        assert error.recoverable is True
        assert error.context is not None

    def test_session_error(self) -> None:
        """Test SessionError."""
        error = SessionError("Session not found", "session-123")

        assert str(error) == "Session not found"
        assert error.error_type == ErrorType.SESSION_NOT_FOUND
        assert error.context.session_id == "session-123"

    def test_player_error(self) -> None:
        """Test PlayerError."""
        error = PlayerError("Player not found", "player@example.com", "session-123")

        assert str(error) == "Player not found"
        assert error.error_type == ErrorType.PLAYER_NOT_FOUND
        assert error.context.player_email == "player@example.com"
        assert error.context.session_id == "session-123"

    def test_turn_error(self) -> None:
        """Test TurnError."""
        error = TurnError("Invalid turn", "session-123", "player@example.com", 5)

        assert str(error) == "Invalid turn"
        assert error.error_type == ErrorType.INVALID_TURN
        assert error.context.session_id == "session-123"
        assert error.context.player_email == "player@example.com"
        assert error.context.turn_number == 5

    def test_storage_error(self) -> None:
        """Test StorageError."""
        error = StorageError("Failed to save", operation="save_session")

        assert str(error) == "Failed to save"
        assert error.error_type == ErrorType.STORAGE_ERROR
        assert error.context.additional_data["operation"] == "save_session"


class TestErrorLogging:
    """Test error logging functionality."""

    @patch("src.error_handler.logger")
    def test_log_error_basic(self, mock_logger) -> None:
        """Test basic error logging."""
        error = GPTTherapyError("Test error", ErrorType.SESSION_NOT_FOUND)

        error_id = log_error(error)

        assert error_id.startswith("err_")
        mock_logger.error.assert_called_once()

        # Check log call arguments - structured logging passes data as kwargs
        call_args = mock_logger.error.call_args
        assert "Error: GPTTherapyError" in call_args[0][0]
        # Check that structured data is passed as keyword arguments
        assert "error_id" in call_args[1]
        assert "error_type" in call_args[1]

    @patch("src.error_handler.logger")
    def test_log_error_with_context(self, mock_logger) -> None:
        """Test error logging with context."""
        context = ErrorContext(
            error_type=ErrorType.PLAYER_NOT_FOUND,
            session_id="test-123",
            player_email="player@example.com",
        )
        error = Exception("Test error")

        error_id = log_error(error, context)

        assert error_id.startswith("err_")
        mock_logger.error.assert_called_once()

        # Check that context was included as keyword arguments
        call_args = mock_logger.error.call_args
        assert "session_id" in call_args[1]
        assert call_args[1]["session_id"] == "test-123"
        assert "player_email" in call_args[1]
        assert call_args[1]["player_email"] == "player@example.com"

    @patch("src.error_handler.logger")
    def test_log_error_different_levels(self, mock_logger) -> None:
        """Test logging at different levels."""
        error = Exception("Test error")

        # Test WARNING level
        log_error(error, level="WARNING")
        mock_logger.warning.assert_called_once()

        # Test CRITICAL level
        log_error(error, level="CRITICAL")
        mock_logger.critical.assert_called_once()


class TestErrorHandling:
    """Test error handling function."""

    @patch("src.error_handler.log_error")
    def test_handle_error_basic(self, mock_log_error) -> None:
        """Test basic error handling."""
        mock_log_error.return_value = "err_123"
        error = GPTTherapyError("Test error", ErrorType.SESSION_NOT_FOUND)

        result = handle_error(error)

        assert result["error_id"] == "err_123"
        assert result["error_type"] == ErrorType.SESSION_NOT_FOUND.value
        assert result["message"] == "Test error"
        assert result["recoverable"] is True
        assert "timestamp" in result

    @patch("src.error_handler.log_error")
    def test_handle_error_with_context(self, mock_log_error) -> None:
        """Test error handling with context."""
        mock_log_error.return_value = "err_123"

        context = ErrorContext(
            error_type=ErrorType.PLAYER_NOT_FOUND,
            session_id="test-123",
            player_email="player@example.com",
        )
        error = PlayerError("Player not found", "player@example.com", "test-123")

        result = handle_error(error, context)

        assert "context" in result
        assert result["context"]["session_id"] == "test-123"
        assert result["context"]["player_email"] == "player@example.com"


class TestUtilityFunctions:
    """Test utility functions."""

    def test_create_error_context(self) -> None:
        """Test error context creation utility."""
        context = create_error_context(
            session_id="test-123",
            player_email="player@example.com",
            turn_number=5,
            custom_field="custom_value",
        )

        assert context.session_id == "test-123"
        assert context.player_email == "player@example.com"
        assert context.turn_number == 5
        assert context.additional_data["custom_field"] == "custom_value"

    def test_with_error_handling_decorator(self) -> None:
        """Test error handling decorator."""

        @with_error_handling
        def test_function():
            raise ValueError("Test error")

        with pytest.raises(GPTTherapyError):
            test_function()

    def test_with_error_handling_gpt_therapy_error(self) -> None:
        """Test decorator with GPTTherapyError (should not wrap)."""

        @with_error_handling
        def test_function():
            raise SessionError("Session not found", "test-123")

        with pytest.raises(SessionError):
            test_function()


class TestErrorMetrics:
    """Test error metrics tracking."""

    def test_error_metrics_init(self) -> None:
        """Test error metrics initialization."""
        metrics = ErrorMetrics()

        assert metrics.error_counts == {}
        assert metrics.last_errors == []
        assert metrics.max_recent_errors == 100

    def test_record_error(self) -> None:
        """Test recording errors."""
        metrics = ErrorMetrics()

        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-123")

        assert metrics.error_counts[ErrorType.SESSION_NOT_FOUND.value] == 1
        assert len(metrics.last_errors) == 1
        assert metrics.last_errors[0]["error_type"] == ErrorType.SESSION_NOT_FOUND.value
        assert metrics.last_errors[0]["session_id"] == "session-123"

    def test_error_summary(self) -> None:
        """Test getting error summary."""
        metrics = ErrorMetrics()

        # Record some errors
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-1")
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-2")
        metrics.record_error(ErrorType.PLAYER_NOT_FOUND, "session-3")

        summary = metrics.get_error_summary()

        assert summary["total_errors"] == 3
        assert summary["error_counts"][ErrorType.SESSION_NOT_FOUND.value] == 2
        assert summary["error_counts"][ErrorType.PLAYER_NOT_FOUND.value] == 1
        assert summary["recent_errors"] == 3
        assert summary["most_common"][0] == ErrorType.SESSION_NOT_FOUND.value
        assert summary["most_common"][1] == 2

    def test_error_metrics_limit(self) -> None:
        """Test that error metrics respect size limits."""
        metrics = ErrorMetrics()
        metrics.max_recent_errors = 2

        # Record more errors than the limit
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-1")
        metrics.record_error(ErrorType.PLAYER_NOT_FOUND, "session-2")
        metrics.record_error(ErrorType.INVALID_TURN, "session-3")

        # Should only keep the most recent errors
        assert len(metrics.last_errors) == 2
        assert metrics.last_errors[0]["error_type"] == ErrorType.PLAYER_NOT_FOUND.value
        assert metrics.last_errors[1]["error_type"] == ErrorType.INVALID_TURN.value
