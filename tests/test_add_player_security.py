"""
Tests for add_player MCP tool security and state validation.

Critical Security Tests:
1. Player addition only allowed during initialization phases
2. Fails appropriately when game has started
3. No session ID exposure in any responses
4. Proper duplicate player handling
"""

from unittest.mock import patch

import pytest
from returns.result import Failure, Success

from src.mcp_tools import GPTTherapyMCPServer, SessionSecurityContext


class TestAddPlayerSecurity:
    """Test add_player tool security and state validation."""

    @pytest.fixture
    def mcp_server(self):
        """Create MCP server with mocked dependencies."""
        with (
            patch("src.mcp_tools.StorageManager"),
            patch("src.mcp_tools.GameEngine"),
            patch("src.mcp_tools.StateMachineManager"),
        ):
            return GPTTherapyMCPServer()

    @pytest.fixture
    def authenticated_server(self, mcp_server):
        """MCP server with authenticated session context."""
        context = SessionSecurityContext(
            session_id="test-session-789",
            player_email="admin@example.com",
            game_type="dungeon",
        )
        mcp_server.set_session_context(context)
        return mcp_server

    @pytest.mark.asyncio
    async def test_add_player_during_initialization_success(self, authenticated_server):
        """Test successful player addition during initialization phase."""
        # Mock session in initialization state
        mock_session = {
            "session_id": "test-session-789",
            "status": "initializing",
            "game_type": "dungeon",
            "players": ["admin@example.com"],
            "created_at": "2024-01-01T00:00:00Z",
        }

        authenticated_server.storage.get_session.return_value = Success(mock_session)
        authenticated_server.storage.update_session.return_value = Success(True)

        # Add new player using execute_tool_call (MCP pattern)
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player2@example.com"}
        )

        # Verify success response (no session_id exposure)
        assert result["success"] is True
        assert result["player_email"] == "player2@example.com"
        assert result["player_count"] == 2
        assert result["session_status"] == "initializing"
        assert "session_id" not in result
        assert "test-session-789" not in str(result)

    @pytest.mark.asyncio
    async def test_add_player_during_waiting_for_players_success(
        self, authenticated_server
    ):
        """Test successful player addition during waiting_for_players phase."""
        # Mock session in waiting_for_players state
        mock_session = {
            "session_id": "test-session-789",
            "status": "waiting_for_players",
            "game_type": "dungeon",
            "players": ["admin@example.com"],
            "created_at": "2024-01-01T00:00:00Z",
        }

        authenticated_server.storage.get_session.return_value = Success(mock_session)
        authenticated_server.storage.update_session.return_value = Success(True)

        # Add new player using execute_tool_call (MCP pattern)
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player2@example.com"}
        )

        # Verify success
        assert result["success"] is True
        assert result["session_status"] == "waiting_for_players"

    @pytest.mark.asyncio
    async def test_add_player_after_game_started_blocked(self, authenticated_server):
        """Test player addition blocked after game has started."""
        # Mock session in active state (game started)
        mock_session = {
            "session_id": "test-session-789",
            "status": "active",
            "game_type": "dungeon",
            "players": ["admin@example.com", "player2@example.com"],
            "created_at": "2024-01-01T00:00:00Z",
        }

        authenticated_server.storage.get_session.return_value = Success(mock_session)

        # Try to add player after game started
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player3@example.com"}
        )

        # Verify blocked with proper error message
        assert result["success"] is False
        assert "Cannot add players after game has started" in result["error"]
        assert result["current_status"] == "active"
        assert result["allowed_statuses"] == ["initializing", "waiting_for_players"]

        # Verify no session ID exposure
        assert "session_id" not in result
        assert "test-session-789" not in str(result)

    @pytest.mark.asyncio
    async def test_add_player_duplicate_blocked(self, authenticated_server):
        """Test adding duplicate player is blocked."""
        # Mock session with existing player
        mock_session = {
            "session_id": "test-session-789",
            "status": "initializing",
            "game_type": "dungeon",
            "players": ["admin@example.com", "player2@example.com"],
            "created_at": "2024-01-01T00:00:00Z",
        }

        authenticated_server.storage.get_session.return_value = Success(mock_session)

        # Try to add existing player
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player2@example.com"}
        )

        # Verify duplicate blocked
        assert result["success"] is False
        assert "Player already in session" in result["error"]
        assert result["player_email"] == "player2@example.com"

        # Verify no session ID exposure
        assert "session_id" not in result
        assert "test-session-789" not in str(result)

    @pytest.mark.asyncio
    async def test_add_player_session_not_found(self, authenticated_server):
        """Test add_player handles missing session gracefully."""
        # Mock session not found
        authenticated_server.storage.get_session.return_value = Success(None)

        # Try to add player
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player@example.com"}
        )

        # Verify error handling
        assert result["success"] is False
        assert "Session not found" in result["error"]
        assert "session_id" not in result

    @pytest.mark.asyncio
    async def test_add_player_storage_failure(self, authenticated_server):
        """Test add_player handles storage failures gracefully."""
        # Mock storage failure
        authenticated_server.storage.get_session.return_value = Failure(
            RuntimeError("Storage connection failed")
        )

        # Try to add player
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player@example.com"}
        )

        # Verify error handling
        assert result["success"] is False
        assert "Session access failed" in result["error"]
        assert "session_id" not in result

    @pytest.mark.asyncio
    async def test_add_player_update_failure(self, authenticated_server):
        """Test add_player handles update failures gracefully."""
        # Mock session get success but update failure
        mock_session = {
            "session_id": "test-session-789",
            "status": "initializing",
            "players": ["admin@example.com"],
        }

        authenticated_server.storage.get_session.return_value = Success(mock_session)
        authenticated_server.storage.update_session.return_value = Failure(
            RuntimeError("Update failed")
        )

        # Try to add player
        result = await authenticated_server.execute_tool_call(
            "add_player", {"player_email": "player2@example.com"}
        )

        # Verify error handling
        assert result["success"] is False
        assert "Failed to update session" in result["error"]
        assert "session_id" not in result

    def test_add_player_tool_definition_security(self, authenticated_server):
        """Test add_player tool definition contains no session_id parameters."""
        tools = authenticated_server.get_tools_for_model()

        add_player_tool = None
        for tool in tools:
            if tool["name"] == "add_player":
                add_player_tool = tool
                break

        assert add_player_tool is not None

        # Verify tool definition security
        params = add_player_tool.get("parameters", {})
        properties = params.get("properties", {})

        # No session_id parameters exposed
        assert "session_id" not in properties
        assert "sessionId" not in properties

        # Only player_email parameter
        assert "player_email" in properties
        assert properties["player_email"]["type"] == "string"

        # Required parameters don't include session
        required = params.get("required", [])
        assert "player_email" in required
        assert "session_id" not in required


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
