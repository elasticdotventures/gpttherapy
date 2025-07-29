"""
Tests for game state persistence functionality.
"""

import os
from unittest.mock import Mock, patch

import pytest

from src.game_state import (
    CharacterState,
    GameStateManager,
    GameStateType,
    TherapyState,
    WorldState,
    get_game_state_manager,
    load_character_state,
    save_character_state,
    update_world_state,
)

# Set test environment
os.environ.update(
    {
        #
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
def game_state_manager(mock_storage):
    """Get GameStateManager instance with mocked storage."""
    return GameStateManager(mock_storage)


@pytest.fixture
def sample_character_data():
    """Sample character data."""
    return {
        "name": "Aragorn",
        "background": "warrior",
        "health": 100,
        "inventory": ["sword", "shield"],
        "skills": {"combat": 8, "leadership": 7},
        "location": "forest_entrance",
    }


@pytest.fixture
def sample_world_data():
    """Sample world state data."""
    return {
        "current_location": "ancient_castle",
        "discovered_locations": ["entrance", "courtyard", "ancient_castle"],
        "time_of_day": "evening",
        "weather": "stormy",
        "environmental_changes": ["bridge_collapsed"],
    }


class TestDataClasses:
    """Test game state data classes."""

    def test_character_state_creation(self) -> None:
        """Test CharacterState creation and defaults."""
        character = CharacterState(name="Test Hero", background="mage")

        assert character.name == "Test Hero"
        assert character.background == "mage"
        assert character.health == 100
        assert character.inventory == []
        assert character.skills == {}
        assert character.level == 1
        assert character.location == "starting_area"
        assert character.status_effects == []

    def test_world_state_creation(self) -> None:
        """Test WorldState creation and defaults."""
        world = WorldState(current_location="dungeon_entrance")

        assert world.current_location == "dungeon_entrance"
        assert world.discovered_locations == ["dungeon_entrance"]
        assert world.time_of_day == "morning"
        assert world.weather == "clear"
        assert world.active_npcs == {}
        assert world.environmental_changes == []

    def test_therapy_state_creation(self) -> None:
        """Test TherapyState creation and defaults."""
        therapy = TherapyState(current_phase="communication_skills")

        assert therapy.current_phase == "communication_skills"
        assert therapy.completed_exercises == []
        assert therapy.therapy_goals == []
        assert therapy.progress_notes == []
        assert therapy.relationship_metrics == {}
        assert therapy.communication_patterns == {}


class TestGameStateManager:
    """Test GameStateManager functionality."""

    def test_init(self, game_state_manager) -> None:
        """Test GameStateManager initialization."""
        assert game_state_manager.storage is not None

    def test_save_game_state_dict(self, game_state_manager, mock_storage) -> None:
        """Test saving game state with dictionary data."""
        mock_storage.save_game_state.return_value = True

        state_data = {"test": "data"}
        result = game_state_manager.save_game_state(
            "session-123", GameStateType.WORLD_STATE, state_data
        )

        assert result is True
        mock_storage.save_game_state.assert_called_once()

        # Check the call arguments
        call_args = mock_storage.save_game_state.call_args[0]
        assert call_args[0] == "session-123"
        save_data = call_args[1]
        assert "key" in save_data
        assert "state_document" in save_data
        assert (
            save_data["state_document"]["state_type"] == GameStateType.WORLD_STATE.value
        )
        assert save_data["state_document"]["state_data"] == state_data

    def test_save_game_state_dataclass(self, game_state_manager, mock_storage) -> None:
        """Test saving game state with dataclass."""
        mock_storage.save_game_state.return_value = True

        character = CharacterState(name="Test Hero", background="warrior")
        result = game_state_manager.save_game_state(
            "session-123",
            GameStateType.CHARACTER_STATE,
            character,
            "player@example.com",
        )

        assert result is True
        mock_storage.save_game_state.assert_called_once()

        # Check that dataclass was converted to dict
        call_args = mock_storage.save_game_state.call_args[0]
        save_data = call_args[1]
        state_data = save_data["state_document"]["state_data"]
        assert state_data["name"] == "Test Hero"
        assert state_data["background"] == "warrior"
        assert state_data["health"] == 100  # Default value

    def test_load_game_state_success(self, game_state_manager, mock_storage) -> None:
        """Test loading game state successfully."""
        stored_data = {
            "key": "sessions/session-123/states/world_state/global.json",
            "state_document": {
                "state_type": "world_state",
                "state_data": {"current_location": "castle"},
            },
        }
        mock_storage.load_game_state.return_value = stored_data

        result = game_state_manager.load_game_state(
            "session-123", GameStateType.WORLD_STATE
        )

        assert result == {"current_location": "castle"}
        mock_storage.load_game_state.assert_called_once_with("session-123")

    def test_load_game_state_not_found(self, game_state_manager, mock_storage) -> None:
        """Test loading game state when not found."""
        mock_storage.load_game_state.return_value = None

        result = game_state_manager.load_game_state(
            "nonexistent", GameStateType.WORLD_STATE
        )

        assert result is None

    def test_create_character_state(
        self, game_state_manager, mock_storage, sample_character_data
    ) -> None:
        """Test creating character state."""
        mock_storage.save_game_state.return_value = True

        character = game_state_manager.create_character_state(
            "session-123", "player@example.com", sample_character_data
        )

        assert isinstance(character, CharacterState)
        assert character.name == "Aragorn"
        assert character.background == "warrior"
        assert character.health == 100
        assert "sword" in character.inventory
        assert character.skills["combat"] == 8

        # Verify it was saved
        mock_storage.save_game_state.assert_called_once()

    def test_update_character_state(self, game_state_manager, mock_storage) -> None:
        """Test updating existing character state."""
        # Mock existing character state
        existing_state = {"name": "Hero", "health": 80, "location": "forest"}
        mock_storage.load_game_state.return_value = {"state_data": existing_state}
        mock_storage.save_game_state.return_value = True

        # Update health and location
        updates = {"health": 90, "location": "castle"}
        result = game_state_manager.update_character_state(
            "session-123", "player@example.com", updates
        )

        assert result is True

        # Check that save was called with updated data
        save_call = mock_storage.save_game_state.call_args[0]
        saved_data = save_call[1]["state_document"]["state_data"]
        assert saved_data["health"] == 90
        assert saved_data["location"] == "castle"
        assert saved_data["name"] == "Hero"  # Unchanged

    def test_update_character_state_not_found(
        self, game_state_manager, mock_storage
    ) -> None:
        """Test updating character state when none exists."""
        mock_storage.load_game_state.return_value = None

        result = game_state_manager.update_character_state(
            "session-123", "player@example.com", {"health": 90}
        )

        assert result is False

    def test_create_world_state(self, game_state_manager, mock_storage) -> None:
        """Test creating world state."""
        mock_storage.save_game_state.return_value = True

        world = game_state_manager.create_world_state("session-123", "dungeon_entrance")

        assert isinstance(world, WorldState)
        assert world.current_location == "dungeon_entrance"
        assert "dungeon_entrance" in world.discovered_locations
        assert world.time_of_day == "morning"

        # Verify it was saved
        mock_storage.save_game_state.assert_called_once()

    def test_update_world_state_existing(
        self, game_state_manager, mock_storage, sample_world_data
    ) -> None:
        """Test updating existing world state."""
        # Mock existing world state
        existing_state = {"current_location": "entrance", "time_of_day": "morning"}
        mock_storage.load_game_state.return_value = {"state_data": existing_state}
        mock_storage.save_game_state.return_value = True

        updates = {"current_location": "castle", "weather": "rainy"}
        result = game_state_manager.update_world_state("session-123", updates)

        assert result is True

        # Check that save was called with updated data
        save_call = mock_storage.save_game_state.call_args[0]
        saved_data = save_call[1]["state_data"]
        assert saved_data["current_location"] == "castle"
        assert saved_data["weather"] == "rainy"
        assert saved_data["time_of_day"] == "morning"  # Unchanged

    def test_update_world_state_new(self, game_state_manager, mock_storage) -> None:
        """Test updating world state when none exists (creates new)."""
        mock_storage.load_game_state.return_value = None
        mock_storage.save_game_state.return_value = True

        updates = {"current_location": "new_location", "weather": "stormy"}
        result = game_state_manager.update_world_state("session-123", updates)

        assert result is True

        # Check that new world state was created and saved
        save_call = mock_storage.save_game_state.call_args[0]
        saved_data = save_call[1]["state_data"]
        assert saved_data["current_location"] == "new_location"
        assert saved_data["weather"] == "stormy"

    def test_create_therapy_state(self, game_state_manager, mock_storage) -> None:
        """Test creating therapy state."""
        mock_storage.save_game_state.return_value = True

        goals = ["improve communication", "resolve conflicts"]
        therapy = game_state_manager.create_therapy_state("session-123", goals)

        assert isinstance(therapy, TherapyState)
        assert therapy.therapy_goals == goals
        assert therapy.current_phase == "assessment"

        # Verify it was saved
        mock_storage.save_game_state.assert_called_once()

    def test_update_therapy_progress(self, game_state_manager, mock_storage) -> None:
        """Test updating therapy progress."""
        # Mock existing therapy state
        existing_state = {"current_phase": "assessment", "progress_notes": []}
        mock_storage.load_game_state.return_value = {"state_data": existing_state}
        mock_storage.save_game_state.return_value = True

        progress_update = {
            "current_phase": "communication_skills",
            "progress_note": "Couple showing improvement in listening skills",
        }

        result = game_state_manager.update_therapy_progress(
            "session-123", progress_update
        )

        assert result is True

        # Check that progress note was added
        save_call = mock_storage.save_game_state.call_args[0]
        saved_data = save_call[1]["state_data"]
        assert saved_data["current_phase"] == "communication_skills"
        assert len(saved_data["progress_notes"]) == 1
        assert "listening skills" in saved_data["progress_notes"][0]["note"]

    def test_get_session_summary(self, game_state_manager, mock_storage) -> None:
        """Test getting comprehensive session summary."""

        # Mock different state types
        def mock_load_game_state(session_id, state_type):
            if state_type == GameStateType.WORLD_STATE:
                return {
                    "current_location": "castle",
                    "updated_at": "2023-01-01T12:00:00Z",
                }
            elif state_type == GameStateType.THERAPY_STATE:
                return {
                    "current_phase": "communication",
                    "updated_at": "2023-01-01T13:00:00Z",
                }
            else:
                return None

        game_state_manager.load_game_state = mock_load_game_state

        result = game_state_manager.get_session_summary("session-123")

        assert result["session_id"] == "session-123"
        assert result["world_state"]["current_location"] == "castle"
        assert result["therapy_state"]["current_phase"] == "communication"
        assert result["last_updated"] == "2023-01-01T13:00:00Z"  # Latest timestamp

    def test_backup_session_state(self, game_state_manager, mock_storage) -> None:
        """Test backing up session state."""
        # Mock session summary
        game_state_manager.get_session_summary = Mock(
            return_value={
                "session_id": "session-123",
                "world_state": {"current_location": "castle"},
            }
        )
        mock_storage.save_game_state.return_value = True

        result = game_state_manager.backup_session_state("session-123")

        assert result is True
        mock_storage.save_game_state.assert_called_once()

        # Check backup data structure
        save_call = mock_storage.save_game_state.call_args[0]
        backup_data = save_call[1]
        assert "key" in backup_data
        assert "backups/session-123/" in backup_data["key"]
        assert "backup_data" in backup_data


class TestUtilityFunctions:
    """Test utility functions."""

    def test_get_game_state_manager(self) -> None:
        """Test get_game_state_manager function."""
        with patch("src.game_state.StorageManager"):
            manager = get_game_state_manager()
            assert isinstance(manager, GameStateManager)

    def test_save_character_state_convenience(self, mock_storage) -> None:
        """Test save_character_state convenience function."""
        with patch("src.game_state.GameStateManager") as mock_manager_class:
            mock_instance = Mock()
            mock_instance.create_character_state.return_value = CharacterState(
                name="Test", background="warrior"
            )
            mock_manager_class.return_value = mock_instance

            result = save_character_state(
                "session-123", "player@example.com", {"name": "Test"}
            )

            assert result is True
            mock_instance.create_character_state.assert_called_once()

    def test_load_character_state_convenience(self, mock_storage) -> None:
        """Test load_character_state convenience function."""
        with patch("src.game_state.GameStateManager") as mock_manager_class:
            mock_instance = Mock()
            mock_instance.load_game_state.return_value = {"name": "Test Hero"}
            mock_manager_class.return_value = mock_instance

            result = load_character_state("session-123", "player@example.com")

            assert result == {"name": "Test Hero"}
            mock_instance.load_game_state.assert_called_once_with(
                "session-123", GameStateType.CHARACTER_STATE, "player@example.com"
            )

    def test_update_world_state_convenience(self, mock_storage) -> None:
        """Test update_world_state convenience function."""
        with patch("src.game_state.GameStateManager") as mock_manager_class:
            mock_instance = Mock()
            mock_instance.update_world_state.return_value = True
            mock_manager_class.return_value = mock_instance

            result = update_world_state("session-123", {"current_location": "castle"})

            assert result is True
            mock_instance.update_world_state.assert_called_once_with(
                "session-123", {"current_location": "castle"}
            )


class TestErrorHandling:
    """Test error handling scenarios."""

    def test_save_game_state_storage_error(
        self, game_state_manager, mock_storage
    ) -> None:
        """Test handling storage errors during save."""
        mock_storage.save_game_state.side_effect = Exception("Storage error")

        result = game_state_manager.save_game_state(
            "session-123", GameStateType.WORLD_STATE, {"test": "data"}
        )

        assert result is False

    def test_load_game_state_storage_error(
        self, game_state_manager, mock_storage
    ) -> None:
        """Test handling storage errors during load."""
        mock_storage.load_game_state.side_effect = Exception("Storage error")

        result = game_state_manager.load_game_state(
            "session-123", GameStateType.WORLD_STATE
        )

        assert result is None

    def test_get_session_summary_error(self, game_state_manager, mock_storage) -> None:
        """Test handling errors during session summary."""
        # Mock a more fundamental error that would cause the whole operation to fail
        with patch.object(
            game_state_manager, "load_game_state", side_effect=Exception("Load error")
        ):
            # Since individual load failures are handled gracefully,
            # this should still return a valid summary structure
            result = game_state_manager.get_session_summary("session-123")

            # Should return a valid structure even if individual loads fail
            assert "session_id" in result
            assert result["session_id"] == "session-123"
            assert "character_states" in result
