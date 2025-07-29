"""
Tests for storage management functionality.
Uses test data from JSON files and flags test records.
"""

import json
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from src.storage import StorageManager, extract_session_id_from_email


@pytest.fixture
def mock_aws_clients():
    """Mock AWS client setup."""
    with patch("boto3.resource") as mock_dynamodb, patch("boto3.client") as mock_s3:
        # Mock DynamoDB tables
        mock_table = Mock()
        mock_dynamodb.return_value.Table.return_value = mock_table

        # Mock S3 client
        mock_s3_client = Mock()
        mock_s3.return_value = mock_s3_client

        yield {"dynamodb": mock_dynamodb, "s3": mock_s3_client, "table": mock_table}


@pytest.fixture
def storage_manager(mock_aws_clients):
    """Get StorageManager instance with mocked clients."""
    return StorageManager()


@pytest.fixture
def sample_session_data():
    """Sample session data for testing."""
    return {
        "game_type": "dungeon",
        "initiator_email": "player1@example.com",
        "session_data": {
            "mission": "treasure-hunt",
            "difficulty": "medium",
            "max_players": 4,
        },
    }


@pytest.fixture
def sample_turn_data():
    """Sample turn data for testing."""
    return {
        "action": "move_north",
        "message": "I want to explore the northern passage",
        "player_state": {"health": 100, "inventory": ["sword", "potion"]},
    }


class TestStorageManager:
    """Test StorageManager functionality."""

    def test_init(self, storage_manager) -> None:
        """Test StorageManager initialization."""
        assert storage_manager.is_test is True
        assert storage_manager.aws_region == "us-east-1"
        assert storage_manager.sessions_table_name == "test-gpttherapy-sessions"

    def test_test_prefix(self, storage_manager) -> None:
        """Test that test records get test/ prefix."""
        key = "sessions/123/data.json"
        prefixed = storage_manager._test_prefix(key)
        assert prefixed == "test/sessions/123/data.json"

    def test_create_session(
        self, storage_manager, sample_session_data, mock_aws_clients
    ) -> None:
        """Test session creation."""
        mock_table = mock_aws_clients["table"]
        mock_table.put_item.return_value = {}

        session_id = storage_manager.create_session(
            game_type=sample_session_data["game_type"],
            initiator_email=sample_session_data["initiator_email"],
            session_data=sample_session_data["session_data"],
        )

        assert session_id is not None
        assert len(session_id) == 12  # Nanoid length
        mock_table.put_item.assert_called_once()

        # Check the session item structure
        call_args = mock_table.put_item.call_args
        session_item = call_args[1]["Item"]
        assert session_item["session_id"] == session_id
        assert session_item["game_type"] == "dungeon"
        assert session_item["status"] == "initializing"
        assert session_item["is_test"] is True
        assert session_item["player_count"] == 1
        assert sample_session_data["initiator_email"] in session_item["players"]

    def test_get_session(self, storage_manager, mock_aws_clients) -> None:
        """Test session retrieval."""
        mock_table = mock_aws_clients["table"]
        session_id = "test-session-123"
        expected_session = {
            "session_id": session_id,
            "game_type": "dungeon",
            "status": "active",
        }
        mock_table.get_item.return_value = {"Item": expected_session}

        result = storage_manager.get_session(session_id)

        assert result == expected_session
        mock_table.get_item.assert_called_once_with(Key={"session_id": session_id})

    def test_get_session_not_found(self, storage_manager, mock_aws_clients) -> None:
        """Test session retrieval when session doesn't exist."""
        mock_table = mock_aws_clients["table"]
        mock_table.get_item.return_value = {}

        result = storage_manager.get_session("nonexistent")

        assert result is None

    def test_update_session(self, storage_manager, mock_aws_clients) -> None:
        """Test session update."""
        mock_table = mock_aws_clients["table"]
        mock_table.update_item.return_value = {}

        session_id = "test-session-123"
        updates = {"status": "active", "player_count": 2}

        result = storage_manager.update_session(session_id, updates)

        assert result is True
        mock_table.update_item.assert_called_once()

        # Check update expression includes updated_at
        call_args = mock_table.update_item.call_args[1]
        assert ":updated_at" in call_args["ExpressionAttributeValues"]

    def test_add_player_to_session(self, storage_manager, mock_aws_clients) -> None:
        """Test adding player to session."""
        mock_table = mock_aws_clients["table"]
        mock_table.update_item.return_value = {}

        session_id = "test-session-123"
        player_email = "player2@example.com"

        result = storage_manager.add_player_to_session(session_id, player_email)

        assert result is True
        mock_table.update_item.assert_called_once()

    def test_save_turn(
        self, storage_manager, sample_turn_data, mock_aws_clients
    ) -> None:
        """Test saving a turn."""
        mock_table = mock_aws_clients["table"]
        mock_table.put_item.return_value = {}
        mock_table.update_item.return_value = {}

        session_id = "test-session-123"
        turn_number = 1
        player_email = "player1@example.com"

        result = storage_manager.save_turn(
            session_id, turn_number, player_email, sample_turn_data
        )

        assert result is True
        assert mock_table.put_item.call_count == 1
        assert mock_table.update_item.call_count == 1

        # Check turn item structure
        put_call = mock_table.put_item.call_args
        turn_item = put_call[1]["Item"]
        assert turn_item["session_id"] == session_id
        assert turn_item["turn_number"] == turn_number
        assert turn_item["player_email"] == player_email
        assert turn_item["is_test"] is True
        assert turn_item["action"] == sample_turn_data["action"]

    def test_get_session_turns(self, storage_manager, mock_aws_clients) -> None:
        """Test retrieving session turns."""
        mock_table = mock_aws_clients["table"]
        expected_turns = [
            {"session_id": "test-123", "turn_number": 1},
            {"session_id": "test-123", "turn_number": 2},
        ]
        mock_table.query.return_value = {"Items": expected_turns}

        result = storage_manager.get_session_turns("test-123")

        assert result == expected_turns
        mock_table.query.assert_called_once()

    def test_get_latest_turn(self, storage_manager, mock_aws_clients) -> None:
        """Test getting latest turn."""
        mock_table = mock_aws_clients["table"]
        latest_turn = {"session_id": "test-123", "turn_number": 5}
        mock_table.query.return_value = {"Items": [latest_turn]}

        result = storage_manager.get_latest_turn("test-123")

        assert result == latest_turn
        mock_table.query.assert_called_once()

        # Check that ScanIndexForward=False for descending order
        call_args = mock_table.query.call_args[1]
        assert call_args["ScanIndexForward"] is False
        assert call_args["Limit"] == 1

    def test_create_player(self, storage_manager, mock_aws_clients) -> None:
        """Test creating new player."""
        mock_table = mock_aws_clients["table"]
        mock_table.get_item.return_value = {}  # Player doesn't exist
        mock_table.put_item.return_value = {}

        player_email = "newplayer@example.com"
        player_data = {"name": "New Player", "preferences": {"difficulty": "easy"}}

        result = storage_manager.create_or_update_player(player_email, player_data)

        assert result is True
        mock_table.put_item.assert_called_once()

        # Check player item includes created_at
        call_args = mock_table.put_item.call_args
        player_item = call_args[1]["Item"]
        assert player_item["email"] == player_email
        assert "created_at" in player_item
        assert player_item["is_test"] is True

    def test_save_game_state(self, storage_manager, mock_aws_clients) -> None:
        """Test saving game state to S3."""
        mock_s3 = mock_aws_clients["s3"]
        mock_s3.put_object.return_value = {}

        session_id = "test-session-123"
        state_data = {"current_location": "forest", "inventory": ["sword"]}

        result = storage_manager.save_game_state(session_id, state_data)

        assert result is True
        mock_s3.put_object.assert_called_once()

        # Check S3 key includes test prefix
        call_args = mock_s3.put_object.call_args[1]
        assert call_args["Key"].startswith("test/sessions/")
        assert call_args["ContentType"] == "application/json"

    def test_load_game_state(self, storage_manager, mock_aws_clients) -> None:
        """Test loading game state from S3."""
        mock_s3 = mock_aws_clients["s3"]
        state_data = {"current_location": "forest", "inventory": ["sword"]}
        mock_response = {"Body": Mock()}
        mock_response["Body"].read.return_value.decode.return_value = json.dumps(
            state_data
        )
        mock_s3.get_object.return_value = mock_response

        result = storage_manager.load_game_state("test-session-123")

        assert result == state_data
        mock_s3.get_object.assert_called_once()

    def test_load_game_state_not_found(self, storage_manager, mock_aws_clients) -> None:
        """Test loading game state when file doesn't exist."""
        mock_s3 = mock_aws_clients["s3"]
        error = ClientError(
            error_response={"Error": {"Code": "NoSuchKey"}}, operation_name="GetObject"
        )
        mock_s3.get_object.side_effect = error

        result = storage_manager.load_game_state("nonexistent")

        assert result is None

    def test_archive_email(self, storage_manager, mock_aws_clients) -> None:
        """Test archiving email to S3."""
        mock_s3 = mock_aws_clients["s3"]
        mock_s3.put_object.return_value = {}

        session_id = "test-session-123"
        email_data = {
            "from": "player@example.com",
            "subject": "My turn",
            "body": "I cast a spell",
        }

        result = storage_manager.archive_email(session_id, email_data)

        assert result is True
        mock_s3.put_object.assert_called_once()

        # Check key structure
        call_args = mock_s3.put_object.call_args[1]
        key = call_args["Key"]
        assert key.startswith("test/sessions/")
        assert "/emails/" in key
        assert key.endswith(".json")


class TestUtilityFunctions:
    """Test utility functions."""

    def test_extract_session_id_simple(self) -> None:
        """Test extracting session ID from new prefix+sessionid format."""
        email = "dungeon+abc123@aws.promptexecution.com"
        session_id = extract_session_id_from_email(email)
        assert session_id == "abc123"

    def test_extract_session_id_nanoid(self) -> None:
        """Test extracting nanoid session ID from new format."""
        email = "intimacy+k4NzWcr47GBd@aws.promptexecution.com"
        session_id = extract_session_id_from_email(email)
        assert session_id == "k4NzWcr47GBd"

    def test_extract_session_id_invalid(self) -> None:
        """Test extracting from invalid email format."""
        assert extract_session_id_from_email("invalid-email") is None
        assert extract_session_id_from_email("") is None
        assert extract_session_id_from_email(None) is None

    def test_extract_session_id_new_session_format(self) -> None:
        """Test that new session format (no session ID) returns None."""
        # These should return None because they're for new session creation
        assert extract_session_id_from_email("dungeon@aws.promptexecution.com") is None
        assert extract_session_id_from_email("intimacy@aws.promptexecution.com") is None

    def test_extract_session_id_invalid_game_type(self) -> None:
        """Test that invalid game types return None."""
        # These should return None because 'invalid' is not a valid game type
        assert (
            extract_session_id_from_email("invalid+abc123@aws.promptexecution.com")
            is None
        )


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_dynamodb_error_propagation(
        self, storage_manager, mock_aws_clients
    ) -> None:
        """Test that DynamoDB errors are properly propagated."""
        mock_table = mock_aws_clients["table"]
        error = ClientError(
            error_response={"Error": {"Code": "ValidationException"}},
            operation_name="PutItem",
        )
        mock_table.put_item.side_effect = error

        with pytest.raises(ClientError):
            storage_manager.create_session("dungeon", "test@example.com", {})

    def test_s3_error_propagation(self, storage_manager, mock_aws_clients) -> None:
        """Test that S3 errors are properly propagated."""
        mock_s3 = mock_aws_clients["s3"]
        error = ClientError(
            error_response={"Error": {"Code": "AccessDenied"}},
            operation_name="PutObject",
        )
        mock_s3.put_object.side_effect = error

        with pytest.raises(ClientError):
            storage_manager.save_game_state("test-123", {"data": "test"})
