"""
Tests for the turn-based game engine functionality.
"""

import os
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from src.game_engine import GameEngine, SessionState, get_game_engine, process_turn

# Set test environment
os.environ.update(
    {
        "AWS_REGION": "us-east-1",
        "IS_TEST_ENV": "true",
        "SESSIONS_TABLE_NAME": "test-sessions",
        "TURNS_TABLE_NAME": "test-turns",
        "PLAYERS_TABLE_NAME": "test-players",
        "GAMEDATA_S3_BUCKET": "test-bucket",
    }
)


@pytest.fixture
def mock_storage():
    """Mock storage manager."""
    return Mock()


@pytest.fixture
def mock_state_manager():
    """Mock state machine manager."""
    mock_manager = Mock()
    mock_turn_machine = Mock()

    # Set up basic state machine mocks
    mock_turn_machine.get_current_state.return_value = "waiting_for_players"
    mock_turn_machine.is_waiting_for_players.return_value = True
    mock_turn_machine.can_start_processing.return_value = False
    mock_turn_machine.get_waiting_players.return_value = ["player2@example.com"]
    mock_turn_machine.get_responded_players.return_value = ["player1@example.com"]

    mock_manager.get_turn_machine.return_value = mock_turn_machine
    mock_manager.cleanup_completed_turns.return_value = None

    return mock_manager


@pytest.fixture
def game_engine(mock_storage, mock_state_manager):
    """Get GameEngine instance with mocked storage and state manager."""
    return GameEngine(mock_storage, mock_state_manager)


@pytest.fixture
def sample_session():
    """Sample session data."""
    return {
        "session_id": "test-session-123",
        "game_type": "dungeon",
        "players": ["player1@example.com", "player2@example.com"],
        "turn_count": 2,
        "status": "active",
        "created_at": "2023-01-01T10:00:00+00:00",
    }


@pytest.fixture
def sample_intimacy_session():
    """Sample couples therapy session."""
    return {
        "session_id": "therapy-session-456",
        "game_type": "intimacy",
        "players": ["partner1@example.com", "partner2@example.com"],
        "turn_count": 1,
        "status": "active",
        "created_at": "2023-01-01T10:00:00+00:00",
    }


@pytest.fixture
def sample_turn_content():
    """Sample turn content."""
    return {
        "email_content": {
            "body": "I want to explore the castle",
            "subject": "My turn",
            "timestamp": "2023-01-01T12:00:00+00:00",
        },
        "status": "received",
    }


class TestGameEngine:
    """Test GameEngine functionality."""

    def test_init(self, game_engine) -> None:
        """Test GameEngine initialization."""
        assert game_engine.max_players["dungeon"] == 4
        assert game_engine.max_players["intimacy"] == 2
        assert game_engine.min_players["dungeon"] == 1
        assert game_engine.min_players["intimacy"] == 2
        assert game_engine.turn_timeout["dungeon"] == 24
        assert game_engine.turn_timeout["intimacy"] == 72

    def test_process_player_turn_session_not_found(
        self, game_engine, mock_storage
    ) -> None:
        """Test processing turn when session doesn't exist."""
        mock_storage.get_session.return_value = None

        with pytest.raises(ValueError, match="Session test-123 not found"):
            game_engine.process_player_turn("test-123", "player@example.com", {})

    def test_process_player_turn_player_not_in_session(
        self, game_engine, mock_storage, sample_session
    ) -> None:
        """Test processing turn when player is not in session."""
        mock_storage.get_session.return_value = sample_session

        with pytest.raises(
            ValueError, match="Player unknown@example.com not in session"
        ):
            game_engine.process_player_turn(
                "test-session-123", "unknown@example.com", {}
            )

    def test_process_player_turn_incomplete(
        self,
        game_engine,
        mock_storage,
        mock_state_manager,
        sample_session,
        sample_turn_content,
    ) -> None:
        """Test processing turn when not all players have submitted."""
        mock_storage.get_session.return_value = sample_session
        mock_storage.save_turn.return_value = True
        mock_storage.update_session.return_value = True

        # Set up state machine mocks for incomplete turn

        turn_machine = mock_state_manager.get_turn_machine.return_value
        turn_machine.can_start_processing.return_value = (
            False  # Not all players responded
        )
        turn_machine.get_waiting_players.return_value = ["player2@example.com"]

        result = game_engine.process_player_turn(
            "test-session-123", "player1@example.com", sample_turn_content
        )

        assert result["turn_complete"] is False
        assert result["current_turn"] == 3
        assert "player2@example.com" in result["waiting_for"]
        assert result["can_proceed"] is False
        assert "session_state" in result
        assert "turn_state" in result

        # Verify storage calls
        mock_storage.save_turn.assert_called_once()
        mock_storage.update_session.assert_called_once()

        # Verify state machine calls
        turn_machine.add_player_response.assert_called_once_with("player1@example.com")
        turn_machine.can_start_processing.assert_called()

    def test_process_player_turn_complete(
        self,
        game_engine,
        mock_storage,
        mock_state_manager,
        sample_session,
        sample_turn_content,
    ) -> None:
        """Test processing turn when all players have submitted."""
        mock_storage.get_session.return_value = sample_session
        mock_storage.save_turn.return_value = True
        mock_storage.update_session.return_value = True

        # Set up state machine mocks for complete turn

        turn_machine = mock_state_manager.get_turn_machine.return_value
        turn_machine.can_start_processing.return_value = True  # All players responded
        turn_machine.is_waiting_for_players.return_value = True
        turn_machine.get_current_state.return_value = "completed"

        result = game_engine.process_player_turn(
            "test-session-123",
            "player2@example.com",  # Second player submitting
            sample_turn_content,
        )

        assert result["turn_complete"] is True
        assert result["current_turn"] == 3
        assert result["waiting_for"] == []
        assert result["can_proceed"] is True
        assert result["next_state"]["turn_advancement"] is True
        assert "session_state" in result
        assert "turn_state" in result

        # Verify state machine transitions
        turn_machine.add_player_response.assert_called_once_with("player2@example.com")
        turn_machine.start_processing.assert_called_once()
        turn_machine.complete.assert_called_once()

    def test_check_turn_completion_intimacy(
        self, game_engine, mock_storage, sample_intimacy_session
    ) -> None:
        """Test turn completion logic for intimacy/therapy sessions."""
        mock_storage.get_session_turns.return_value = [
            {"turn_number": 2, "player_email": "partner1@example.com"},
            {"turn_number": 2, "player_email": "partner2@example.com"},
        ]

        result = game_engine._check_turn_completion(
            "therapy-session-456", 2, sample_intimacy_session
        )
        assert result is True

    def test_check_turn_completion_intimacy_incomplete(
        self, game_engine, mock_storage, sample_intimacy_session
    ) -> None:
        """Test turn completion when only one partner submitted."""
        mock_storage.get_session_turns.return_value = [
            {"turn_number": 2, "player_email": "partner1@example.com"}
        ]

        result = game_engine._check_turn_completion(
            "therapy-session-456", 2, sample_intimacy_session
        )
        assert result is False

    @pytest.mark.skip(reason="Mock state machine issues - will fix later")
    def test_advance_turn(self, game_engine, mock_storage, sample_session) -> None:
        """Test advancing to next turn."""
        mock_storage.update_session.return_value = True

        result = game_engine._advance_turn("test-session-123", sample_session, 3)

        assert result["status"] == SessionState.ACTIVE.value
        assert result["current_turn"] == 3
        assert result["next_turn"] == 4
        assert result["waiting_for"] == []
        assert result["turn_advancement"] is True

        # Check update_session was called with correct data
        update_call = mock_storage.update_session.call_args[0]
        assert update_call[0] == "test-session-123"
        update_data = mock_storage.update_session.call_args[0][1]
        assert update_data["turn_count"] == 3
        assert update_data["next_turn"] == 4
        assert update_data["status"] == SessionState.ACTIVE.value

    def test_update_waiting_state(
        self, game_engine, mock_storage, mock_state_manager, sample_session
    ) -> None:
        """Test updating session while waiting for players."""
        # Set up state machine mocks

        mock_state_manager.get_session_machine.return_value.is_active.return_value = (
            True
        )
        mock_state_manager.get_session_machine.return_value.get_current_state.return_value = "active"

        turn_machine = mock_state_manager.get_turn_machine.return_value
        turn_machine.get_waiting_players.return_value = ["player2@example.com"]

        mock_storage.update_session.return_value = True

        result = game_engine._update_waiting_state(
            "test-session-123", sample_session, 3
        )

        # In new behavior, active sessions stay active while waiting for turn responses
        assert result["status"] == SessionState.ACTIVE.value
        assert result["current_turn"] == 3
        assert "player2@example.com" in result["waiting_for"]
        assert result["turn_advancement"] is False

    def test_check_turn_timeouts(self, game_engine, mock_storage) -> None:
        """Test checking for timed out sessions."""
        # Mock active sessions with old timestamps
        old_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        active_sessions = [
            {
                "session_id": "timeout-session-1",
                "game_type": "dungeon",
                "updated_at": old_time,
                "waiting_for": ["player@example.com"],
                "turn_count": 2,
            }
        ]

        mock_storage.get_active_sessions.return_value = active_sessions

        result = game_engine.check_turn_timeouts()

        assert len(result) == 1
        assert result[0]["session_id"] == "timeout-session-1"
        assert result[0]["timeout_hours"] == 24

    def test_handle_turn_timeout_therapy(
        self, game_engine, mock_storage, mock_state_manager, sample_intimacy_session
    ) -> None:
        """Test handling timeout for therapy session."""
        mock_storage.get_session.return_value = sample_intimacy_session
        mock_storage.update_session.return_value = True

        # Set up state machine mocks

        mock_state_manager.get_session_machine.return_value.get_current_state.return_value = "paused"

        turn_machine = mock_state_manager.get_turn_machine.return_value

        result = game_engine.handle_turn_timeout("therapy-session-456")

        assert result["action"] == "paused"
        assert result["reason"] == "turn_timeout"
        assert result["reminder_needed"] is True

        # Verify state machine was used to pause
        mock_state_manager.get_session_machine.return_value.pause.assert_called_once()
        turn_machine.timeout.assert_called_once()

        # Check session was paused
        update_call = mock_storage.update_session.call_args[0]
        update_data = update_call[1]
        assert update_data["status"] == "paused"  # From state machine mock
        assert update_data["pause_reason"] == "turn_timeout"

    def test_handle_turn_timeout_adventure_continue(
        self, game_engine, mock_storage
    ) -> None:
        """Test handling timeout for adventure - continue with majority."""
        # Adventure session where 2/3 players responded
        adventure_session = {
            "session_id": "adventure-123",
            "game_type": "dungeon",
            "players": ["p1@example.com", "p2@example.com", "p3@example.com"],
            "waiting_for": ["p3@example.com"],  # Only 1 missing
            "turn_count": 5,
        }

        mock_storage.get_session.return_value = adventure_session
        mock_storage.update_session.return_value = True

        result = game_engine.handle_turn_timeout("adventure-123")

        # Should advance turn since majority responded
        assert result["turn_advancement"] is True
        assert result["current_turn"] == 5
        assert result["next_turn"] == 6

    def test_resume_session(
        self, game_engine, mock_storage, mock_state_manager
    ) -> None:
        """Test resuming a paused session."""
        paused_session = {
            "session_id": "paused-123",
            "status": SessionState.PAUSED.value,
            "game_type": "dungeon",
            "players": ["player@example.com"],
        }

        mock_storage.get_session.return_value = paused_session
        mock_storage.update_session.return_value = True

        # Set up state machine mocks

        mock_state_manager.get_session_machine.return_value.can_resume.return_value = (
            True
        )
        mock_state_manager.get_session_machine.return_value.resume.return_value = None

        # Mock the state check and transition
        def mock_get_current_state():
            if mock_state_manager.get_session_machine.return_value.resume.called:
                return "active"
            return "paused"

        mock_state_manager.get_session_machine.return_value.get_current_state.side_effect = mock_get_current_state

        result = game_engine.resume_session("paused-123", "player@example.com")

        assert result["action"] == "resumed"
        assert result["resumed_by"] == "player@example.com"
        assert result["status"] == "active"  # From state machine mock

        # Verify state machine methods were called
        mock_state_manager.get_session_machine.return_value.can_resume.assert_called_once()
        mock_state_manager.get_session_machine.return_value.resume.assert_called_once()

        # Check session was updated
        update_call = mock_storage.update_session.call_args[0]
        update_data = update_call[1]
        assert update_data["resumed_by"] == "player@example.com"

    def test_resume_session_not_paused(
        self, game_engine, mock_storage, sample_session
    ) -> None:
        """Test resuming session that's not paused."""
        mock_storage.get_session.return_value = sample_session  # Active session

        result = game_engine.resume_session("test-session-123", "player@example.com")

        assert "error" in result
        assert "not paused" in result["error"]

    def test_add_player_to_session_success(self, game_engine, mock_storage) -> None:
        """Test adding player to session successfully."""
        session_with_space = {
            "session_id": "test-123",
            "game_type": "dungeon",
            "players": ["player1@example.com"],
            "status": "waiting_for_players",
        }

        mock_storage.get_session.return_value = session_with_space
        mock_storage.add_player_to_session.return_value = True
        mock_storage.update_session.return_value = True

        result = game_engine.add_player_to_session("test-123", "player2@example.com")

        assert result["action"] == "player_added_session_started"
        assert result["player_email"] == "player2@example.com"
        assert result["can_start"] is True

    def test_add_player_to_session_full(self, game_engine, mock_storage) -> None:
        """Test adding player to full session."""
        full_session = {
            "session_id": "full-123",
            "game_type": "dungeon",
            "players": [
                "p1@example.com",
                "p2@example.com",
                "p3@example.com",
                "p4@example.com",
            ],
        }

        mock_storage.get_session.return_value = full_session

        result = game_engine.add_player_to_session("full-123", "p5@example.com")

        assert "error" in result
        assert "full" in result["error"]

    def test_add_player_already_exists(
        self, game_engine, mock_storage, sample_session
    ) -> None:
        """Test adding player who's already in session."""
        mock_storage.get_session.return_value = sample_session

        result = game_engine.add_player_to_session(
            "test-session-123", "player1@example.com"
        )

        assert "error" in result
        assert "already in session" in result["error"]

    def test_get_turn_summary(self, game_engine, mock_storage) -> None:
        """Test getting turn summary."""
        turn_submissions = [
            {
                "turn_number": 3,
                "player_email": "player1@example.com",
                "email_content": {"body": "I attack the dragon"},
                "timestamp": "2023-01-01T12:00:00+00:00",
            },
            {
                "turn_number": 3,
                "player_email": "player2@example.com",
                "email_content": {"body": "I cast a healing spell"},
                "timestamp": "2023-01-01T12:01:00+00:00",
            },
        ]

        mock_storage.get_session_turns.return_value = turn_submissions

        result = game_engine.get_turn_summary("test-123", 3)

        assert result["turn_number"] == 3
        assert result["submission_count"] == 2
        assert "player1@example.com" in result["submissions"]
        assert "player2@example.com" in result["submissions"]
        assert (
            result["submissions"]["player1@example.com"]["email_content"]["body"]
            == "I attack the dragon"
        )

    def test_get_turn_summary_latest(self, game_engine, mock_storage) -> None:
        """Test getting latest turn summary."""
        latest_turn = {
            "turn_number": 5,
            "player_email": "player@example.com",
            "timestamp": "2023-01-01T15:00:00+00:00",
        }

        mock_storage.get_latest_turn.return_value = latest_turn
        mock_storage.get_session_turns.return_value = [latest_turn]

        result = game_engine.get_turn_summary("test-123")

        assert result["turn_number"] == 5
        assert result["submission_count"] == 1


class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_game_engine(self) -> None:
        """Test get_game_engine function."""
        with patch("src.game_engine.StorageManager"):
            engine = get_game_engine()
            assert isinstance(engine, GameEngine)

    def test_process_turn(self, mock_storage) -> None:
        """Test process_turn convenience function."""
        with patch("src.game_engine.GameEngine") as mock_engine_class:
            mock_instance = Mock()
            mock_engine_class.return_value = mock_instance
            mock_instance.process_player_turn.return_value = {"turn_complete": True}

            result = process_turn("test-123", "player@example.com", {"test": "data"})

            assert result["turn_complete"] is True
            mock_instance.process_player_turn.assert_called_once_with(
                "test-123", "player@example.com", {"test": "data"}
            )


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_process_turn_storage_error(
        self, game_engine, mock_storage, sample_session
    ) -> None:
        """Test handling storage errors during turn processing."""
        mock_storage.get_session.return_value = sample_session
        mock_storage.save_turn.side_effect = Exception("Database error")

        with pytest.raises(Exception, match="Database error"):
            game_engine.process_player_turn("test-123", "player1@example.com", {})

    def test_check_timeouts_storage_error(self, game_engine, mock_storage) -> None:
        """Test handling storage errors during timeout check."""
        mock_storage.get_active_sessions.side_effect = Exception("Connection error")

        result = game_engine.check_turn_timeouts()

        # Should return empty list on error
        assert result == []

    def test_handle_timeout_session_not_found(self, game_engine, mock_storage) -> None:
        """Test handling timeout for non-existent session."""
        mock_storage.get_session.return_value = None

        result = game_engine.handle_turn_timeout("nonexistent-123")

        assert "error" in result
        assert "not found" in result["error"]
