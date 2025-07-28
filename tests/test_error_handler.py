"""
Tests for error handling utilities.
"""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

# Set test environment
os.environ.update({
    'AWS_REGION': 'us-east-1',
    'IS_TEST_ENV': 'true',
    'SESSIONS_TABLE_NAME': 'test-sessions',
    'TURNS_TABLE_NAME': 'test-turns',
    'PLAYERS_TABLE_NAME': 'test-players',
    'GAMEDATA_S3_BUCKET': 'test-bucket'
})

from src.error_handler import (
    ErrorType, ErrorContext, GPTTherapyError, SessionError, PlayerError, TurnError, StorageError,
    log_error, handle_error, create_error_context, with_error_handling, ErrorMetrics
)


class TestErrorTypes:
    """Test error type enumerations."""
    
    def test_error_types_exist(self):
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
    
    def test_error_context_creation(self):
        """Test creating error context."""
        context = ErrorContext(
            error_type=ErrorType.SESSION_NOT_FOUND,
            session_id='test-123',
            player_email='player@example.com'
        )
        
        assert context.error_type == ErrorType.SESSION_NOT_FOUND
        assert context.session_id == 'test-123'
        assert context.player_email == 'player@example.com'
        assert context.timestamp is not None
    
    def test_error_context_auto_timestamp(self):
        """Test that timestamp is automatically set."""
        context = ErrorContext(error_type=ErrorType.UNKNOWN_ERROR)
        
        assert context.timestamp is not None
        # Timestamp should be recent
        timestamp_dt = datetime.fromisoformat(context.timestamp.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        assert (now - timestamp_dt).total_seconds() < 1


class TestCustomExceptions:
    """Test custom exception classes."""
    
    def test_gpt_therapy_error(self):
        """Test base GPTTherapyError."""
        error = GPTTherapyError("Test error", ErrorType.UNKNOWN_ERROR)
        
        assert str(error) == "Test error"
        assert error.error_type == ErrorType.UNKNOWN_ERROR
        assert error.recoverable is True
        assert error.context is not None
    
    def test_session_error(self):
        """Test SessionError."""
        error = SessionError("Session not found", "session-123")
        
        assert str(error) == "Session not found"
        assert error.error_type == ErrorType.SESSION_NOT_FOUND
        assert error.context.session_id == "session-123"
    
    def test_player_error(self):
        """Test PlayerError."""
        error = PlayerError("Player not found", "player@example.com", "session-123")
        
        assert str(error) == "Player not found"
        assert error.error_type == ErrorType.PLAYER_NOT_FOUND
        assert error.context.player_email == "player@example.com"
        assert error.context.session_id == "session-123"
    
    def test_turn_error(self):
        """Test TurnError."""
        error = TurnError("Invalid turn", "session-123", "player@example.com", 5)
        
        assert str(error) == "Invalid turn"
        assert error.error_type == ErrorType.INVALID_TURN
        assert error.context.session_id == "session-123"
        assert error.context.player_email == "player@example.com"
        assert error.context.turn_number == 5
    
    def test_storage_error(self):
        """Test StorageError."""
        error = StorageError("Failed to save", operation="save_session")
        
        assert str(error) == "Failed to save"
        assert error.error_type == ErrorType.STORAGE_ERROR
        assert error.context.additional_data['operation'] == "save_session"


class TestErrorLogging:
    """Test error logging functionality."""
    
    @patch('src.error_handler.logger')
    def test_log_error_basic(self, mock_logger):
        """Test basic error logging."""
        error = GPTTherapyError("Test error", ErrorType.SESSION_NOT_FOUND)
        
        error_id = log_error(error)
        
        assert error_id.startswith("err_")
        mock_logger.error.assert_called_once()
        
        # Check log call arguments
        call_args = mock_logger.error.call_args
        assert "GPTTherapyError: Test error" in call_args[0][0]
        assert "extra" in call_args[1]
    
    @patch('src.error_handler.logger')
    def test_log_error_with_context(self, mock_logger):
        """Test error logging with context."""
        context = ErrorContext(
            error_type=ErrorType.PLAYER_NOT_FOUND,
            session_id='test-123',
            player_email='player@example.com'
        )
        error = Exception("Test error")
        
        error_id = log_error(error, context)
        
        assert error_id.startswith("err_")
        mock_logger.error.assert_called_once()
        
        # Check that context was included
        call_args = mock_logger.error.call_args
        log_data = call_args[1]['extra']
        assert 'context' in log_data
        assert log_data['context']['session_id'] == 'test-123'
    
    @patch('src.error_handler.logger')
    def test_log_error_different_levels(self, mock_logger):
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
    
    @patch('src.error_handler.log_error')
    def test_handle_error_basic(self, mock_log_error):
        """Test basic error handling."""
        mock_log_error.return_value = "err_123"
        error = GPTTherapyError("Test error", ErrorType.SESSION_NOT_FOUND)
        
        result = handle_error(error)
        
        assert result['error_id'] == "err_123"
        assert result['error_type'] == ErrorType.SESSION_NOT_FOUND.value
        assert result['message'] == "Test error"
        assert result['recoverable'] is True
        assert 'timestamp' in result
    
    @patch('src.error_handler.log_error')
    def test_handle_error_with_context(self, mock_log_error):
        """Test error handling with context."""
        mock_log_error.return_value = "err_123"
        
        context = ErrorContext(
            error_type=ErrorType.PLAYER_NOT_FOUND,
            session_id='test-123',
            player_email='player@example.com'
        )
        error = PlayerError("Player not found", "player@example.com", "test-123")
        
        result = handle_error(error, context)
        
        assert 'context' in result
        assert result['context']['session_id'] == 'test-123'
        assert result['context']['player_email'] == 'player@example.com'


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_create_error_context(self):
        """Test error context creation utility."""
        context = create_error_context(
            session_id='test-123',
            player_email='player@example.com',
            turn_number=5,
            custom_field='custom_value'
        )
        
        assert context.session_id == 'test-123'
        assert context.player_email == 'player@example.com'
        assert context.turn_number == 5
        assert context.additional_data['custom_field'] == 'custom_value'
    
    def test_with_error_handling_decorator(self):
        """Test error handling decorator."""
        
        @with_error_handling
        def test_function():
            raise ValueError("Test error")
        
        with pytest.raises(GPTTherapyError):
            test_function()
    
    def test_with_error_handling_gpt_therapy_error(self):
        """Test decorator with GPTTherapyError (should not wrap)."""
        
        @with_error_handling
        def test_function():
            raise SessionError("Session not found", "test-123")
        
        with pytest.raises(SessionError):
            test_function()


class TestErrorMetrics:
    """Test error metrics tracking."""
    
    def test_error_metrics_init(self):
        """Test error metrics initialization."""
        metrics = ErrorMetrics()
        
        assert metrics.error_counts == {}
        assert metrics.last_errors == []
        assert metrics.max_recent_errors == 100
    
    def test_record_error(self):
        """Test recording errors."""
        metrics = ErrorMetrics()
        
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-123")
        
        assert metrics.error_counts[ErrorType.SESSION_NOT_FOUND.value] == 1
        assert len(metrics.last_errors) == 1
        assert metrics.last_errors[0]['error_type'] == ErrorType.SESSION_NOT_FOUND.value
        assert metrics.last_errors[0]['session_id'] == "session-123"
    
    def test_error_summary(self):
        """Test getting error summary."""
        metrics = ErrorMetrics()
        
        # Record some errors
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-1")
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-2")
        metrics.record_error(ErrorType.PLAYER_NOT_FOUND, "session-3")
        
        summary = metrics.get_error_summary()
        
        assert summary['total_errors'] == 3
        assert summary['error_counts'][ErrorType.SESSION_NOT_FOUND.value] == 2
        assert summary['error_counts'][ErrorType.PLAYER_NOT_FOUND.value] == 1
        assert summary['recent_errors'] == 3
        assert summary['most_common'][0] == ErrorType.SESSION_NOT_FOUND.value
        assert summary['most_common'][1] == 2
    
    def test_error_metrics_limit(self):
        """Test that error metrics respect size limits."""
        metrics = ErrorMetrics()
        metrics.max_recent_errors = 2
        
        # Record more errors than the limit
        metrics.record_error(ErrorType.SESSION_NOT_FOUND, "session-1")
        metrics.record_error(ErrorType.PLAYER_NOT_FOUND, "session-2")
        metrics.record_error(ErrorType.INVALID_TURN, "session-3")
        
        # Should only keep the most recent errors
        assert len(metrics.last_errors) == 2
        assert metrics.last_errors[0]['error_type'] == ErrorType.PLAYER_NOT_FOUND.value
        assert metrics.last_errors[1]['error_type'] == ErrorType.INVALID_TURN.value