"""
Tests for MCP tool calling security - ensuring session ID isolation.

Critical Security Tests:
1. Session ID is NEVER exposed to the model
2. Tools operate within authenticated session context only
3. Model cannot access or specify session identifiers
4. All operations are properly scoped to authorized session
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bedrock_mcp_integration import BedrockMCPAgent
from src.mcp_tools import GPTTherapyMCPServer, SessionSecurityContext


class TestSessionSecurityContext:
    """Test session security context isolation."""

    def test_session_id_private_access(self):
        """Test that session_id is accessible internally but not exposed to model."""
        context = SessionSecurityContext(
            session_id="secret-session-123",
            player_email="player@example.com",
            game_type="dungeon",
        )

        # Internal access works
        assert context.session_id == "secret-session-123"
        assert context.player_email == "player@example.com"
        assert context.game_type == "dungeon"

    def test_model_context_safe_exposure(self):
        """Test that model context does NOT contain session ID."""
        context = SessionSecurityContext(
            session_id="secret-session-123",
            player_email="player@example.com",
            game_type="dungeon",
        )

        model_context = context.to_model_context()

        # Session ID is NOT exposed to model
        assert "session_id" not in model_context
        assert "secret-session-123" not in json.dumps(model_context)

        # Safe information is included
        assert model_context["game_type"] == "dungeon"
        assert model_context["player_email"] == "player@example.com"
        assert "timestamp" in model_context


class TestMCPToolSecurity:
    """Test MCP tool security isolation."""

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
            session_id="test-session-456",
            player_email="player@example.com",
            game_type="dungeon",
        )
        mcp_server.set_session_context(context)
        return mcp_server

    def test_unauthenticated_tool_access_blocked(self, mcp_server):
        """Test that tools cannot be called without authenticated session."""
        # No session context set - should fail
        with pytest.raises(ValueError, match="No authenticated session context"):
            mcp_server._ensure_authenticated()

    def test_tool_definitions_no_session_id_parameters(self, mcp_server):
        """Test that tool definitions never expose session_id as parameter."""
        tools = mcp_server.get_tools_for_model()

        for tool in tools:
            # Check tool name doesn't reference session
            assert "session" not in tool["name"].lower()
            assert "session_id" not in tool["name"]

            # Check parameters don't include session_id
            params = tool.get("parameters", {})
            properties = params.get("properties", {})

            assert "session_id" not in properties
            assert "sessionId" not in properties

            # Check required parameters don't include session
            required = params.get("required", [])
            assert "session_id" not in required
            assert "sessionId" not in required

    @pytest.mark.asyncio
    async def test_get_session_status_no_session_id_exposure(
        self, authenticated_server
    ):
        """Test get_session_status doesn't expose session_id in response."""
        # Mock storage to return session data
        mock_session = {
            "session_id": "test-session-456",  # This should NOT be in tool response
            "status": "active",
            "game_type": "dungeon",
            "turn_count": 3,
            "players": ["player1@example.com", "player2@example.com"],
            "created_at": "2024-01-01T00:00:00Z",
            "last_activity": "2024-01-01T01:00:00Z",
        }

        from returns.result import Success

        authenticated_server.storage.get_session.return_value = Success(mock_session)

        # Execute tool
        result = await authenticated_server.mcp.get_session_status()

        # Verify session_id is NOT in response
        assert "session_id" not in result
        assert "test-session-456" not in json.dumps(result)

        # Verify safe data is included
        assert result["status"] == "active"
        assert result["game_type"] == "dungeon"
        assert result["turn_count"] == 3
        assert result["player_count"] == 2

    @pytest.mark.asyncio
    async def test_get_turn_history_sanitized(self, authenticated_server):
        """Test turn history removes session_id references."""
        # Mock turn history with session_id references
        mock_turns = [
            {
                "session_id": "test-session-456",  # Should be removed
                "turn_number": 1,
                "player_email": "player@example.com",
                "content": "I attack the goblin",
                "timestamp": "2024-01-01T00:00:00Z",
                "ai_response": "The goblin dodges!",
            },
            {
                "session_id": "test-session-456",  # Should be removed
                "turn_number": 2,
                "player_email": "player@example.com",
                "content": "I cast fireball",
                "timestamp": "2024-01-01T00:05:00Z",
                "ai_response": "Flames engulf the area!",
            },
        ]

        from returns.result import Success

        authenticated_server.storage.get_session_turns.return_value = Success(
            mock_turns
        )

        # Execute tool
        result = await authenticated_server.mcp.get_turn_history(limit=2)

        # Verify session_id removed from all turns
        for turn in result:
            assert "session_id" not in turn
            assert "test-session-456" not in json.dumps(turn)

        # Verify safe data preserved
        assert len(result) == 2
        assert result[0]["turn_number"] == 1
        assert result[0]["content"] == "I attack the goblin"


class TestBedrockMCPIntegration:
    """Test Bedrock MCP integration security."""

    @pytest.fixture
    def bedrock_agent(self):
        """Create Bedrock MCP agent with mocked dependencies."""
        with (
            patch("src.bedrock_mcp_integration.boto3"),
            patch("src.bedrock_mcp_integration.GPTTherapyMCPServer"),
        ):
            return BedrockMCPAgent()

    def test_session_context_isolation(self, bedrock_agent):
        """Test session context is set securely and isolated from model."""
        # Set session context (lambda-only operation)
        bedrock_agent.set_session_context(
            session_id="secret-123",
            player_email="player@example.com",
            game_type="dungeon",
        )

        # Verify context is set internally
        assert bedrock_agent._session_context is not None
        assert bedrock_agent._session_context.session_id == "secret-123"

        # Verify MCP server received authenticated context
        bedrock_agent.mcp_server.set_session_context.assert_called_once()
        context_arg = bedrock_agent.mcp_server.set_session_context.call_args[0][0]
        assert context_arg.session_id == "secret-123"

    def test_system_prompt_no_session_id(self, bedrock_agent):
        """Test system prompt never contains session ID."""
        bedrock_agent.set_session_context(
            session_id="secret-456",
            player_email="player@example.com",
            game_type="dungeon",
        )

        # Build system prompt with safe context
        safe_context = {
            "turn_count": 5,
            "status": "active",
            "players": ["player1@example.com"],
        }

        prompt = bedrock_agent._build_system_prompt_with_tools(
            agent_config="You are a DM",
            game_type="dungeon",
            session_context=safe_context,
        )

        # Verify session ID never appears in prompt
        assert "secret-456" not in prompt
        assert "session_id" not in prompt.lower()

        # Verify safe context is included
        assert "Turn Count: 5" in prompt
        assert "Status: active" in prompt

    @patch("src.bedrock_mcp_integration.BedrockMCPAgent._call_bedrock_with_tools")
    def test_generate_response_session_isolation(
        self, mock_bedrock_call, bedrock_agent
    ):
        """Test response generation maintains session ID isolation."""
        # Setup authenticated session
        bedrock_agent.set_session_context(
            session_id="isolated-789",
            player_email="player@example.com",
            game_type="dungeon",
        )

        # Mock Bedrock response
        mock_bedrock_call.return_value = "The dragon roars menacingly!"

        # Safe session context (no session_id)
        safe_context = {
            "turn_count": 3,
            "status": "active",
            "players": ["player@example.com"],
        }

        # Generate response
        bedrock_agent.generate_response_with_tools(
            game_type="dungeon",
            session_context=safe_context,
            player_input="I approach the dragon",
            turn_history=[],
            agent_config="You are a DM",
        )

        # Verify Bedrock was called
        assert mock_bedrock_call.called

        # Get the arguments passed to Bedrock
        call_args = mock_bedrock_call.call_args[0]
        system_prompt = call_args[0]
        user_prompt = call_args[1]
        tools = call_args[2]

        # Verify session ID never exposed to model
        assert "isolated-789" not in system_prompt
        assert "isolated-789" not in user_prompt
        assert "isolated-789" not in json.dumps(tools)

        # Verify no session_id parameters in tools
        for tool in tools:
            params = tool.get("parameters", {})
            properties = params.get("properties", {})
            assert "session_id" not in properties

    def test_unauthenticated_generation_blocked(self, bedrock_agent):
        """Test response generation fails without authenticated session."""
        # No session context set
        with pytest.raises(ValueError, match="Session context not authenticated"):
            bedrock_agent.generate_response_with_tools(
                game_type="dungeon", session_context={}, player_input="test input"
            )

    @pytest.mark.asyncio
    async def test_tool_execution_uses_authenticated_context(self, bedrock_agent):
        """Test tool execution uses pre-authenticated session context."""
        # Set authenticated context
        bedrock_agent.set_session_context(
            session_id="auth-context-123",
            player_email="player@example.com",
            game_type="dungeon",
        )

        # Mock tool execution
        bedrock_agent.mcp_server.execute_tool_call = AsyncMock(
            return_value={"status": "success"}
        )

        # Execute tool (no session_id parameter provided by model)
        result = await bedrock_agent._execute_mcp_tool(
            tool_name="get_session_status",
            tool_input={},  # Note: NO session_id in input
        )

        # Verify tool was called with authenticated context
        bedrock_agent.mcp_server.execute_tool_call.assert_called_once_with(
            "get_session_status", {}
        )

        assert result["status"] == "success"


class TestMCPConvenienceFunctions:
    """Test convenience functions maintain security."""

    @patch("src.bedrock_mcp_integration.BedrockMCPAgent")
    def test_generate_mcp_response_security(self, mock_agent_class):
        """Test convenience function maintains session ID isolation."""
        from src.bedrock_mcp_integration import generate_mcp_response

        mock_agent = MagicMock()
        mock_agent_class.return_value = mock_agent
        mock_agent.generate_response_with_tools.return_value = "Test response"

        # Call convenience function with session_id (lambda-provided)
        response = generate_mcp_response(
            session_id="lambda-provided-456",  # Trusted by lambda
            player_email="player@example.com",
            game_type="dungeon",
            session_context={"turn_count": 2},  # Safe context (no session_id)
            player_input="I enter the dungeon",
        )

        # Verify agent created and session context set securely
        mock_agent_class.assert_called_once()
        mock_agent.set_session_context.assert_called_once_with(
            "lambda-provided-456", "player@example.com", "dungeon"
        )

        # Verify response generation called with safe context
        mock_agent.generate_response_with_tools.assert_called_once()
        call_args = mock_agent.generate_response_with_tools.call_args

        # Safe context passed to model (no session_id)
        session_context = call_args[1]["session_context"]
        assert "session_id" not in session_context
        assert "lambda-provided-456" not in json.dumps(session_context)

        assert response == "Test response"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
