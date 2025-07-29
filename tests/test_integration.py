"""
Integration tests to verify AI agent works with actual game configurations.
"""

import os
from unittest.mock import Mock, patch

import pytest

from src.ai_agent import AIAgent

os.environ.update({"AWS_REGION": "us-east-1", "IS_TEST_ENV": "true"})


@pytest.fixture
def mock_bedrock_client():
    """Mock Bedrock client for integration tests."""
    with patch("boto3.client") as mock_client:
        mock_bedrock = Mock()
        mock_client.return_value = mock_bedrock
        yield mock_bedrock


@pytest.fixture
def ai_agent_with_real_configs(mock_bedrock_client):
    """Get AIAgent instance that loads real game configurations."""
    return AIAgent()


class TestIntegration:
    """Integration tests with real game configurations."""

    def test_load_real_game_configs(self, ai_agent_with_real_configs) -> None:
        """Test that real game configurations are loaded correctly."""
        agent = ai_agent_with_real_configs

        # Check if dungeon config was loaded
        if "dungeon" in agent.agent_configs:
            dungeon_config = agent.agent_configs["dungeon"]
            assert "Dungeon Master" in dungeon_config
            assert "Role" in dungeon_config
            assert "adventure" in dungeon_config.lower()

        # Check if intimacy config was loaded
        if "intimacy" in agent.agent_configs:
            intimacy_config = agent.agent_configs["intimacy"]
            assert "therapist" in intimacy_config.lower()
            assert "couples" in intimacy_config.lower()

    def test_system_prompt_with_real_config(self, ai_agent_with_real_configs) -> None:
        """Test system prompt generation with real configurations."""
        agent = ai_agent_with_real_configs

        session_context = {
            "session_id": "test-123",
            "game_type": "dungeon",
            "turn_count": 3,
            "players": ["player@example.com"],
            "status": "active",
        }

        system_prompt = agent._build_system_prompt("dungeon", session_context)

        # Should include session context
        assert "test-123" in system_prompt
        assert "Turn Count: 3" in system_prompt
        assert "player@example.com" in system_prompt

        # Should include response guidelines
        assert "email response format" in system_prompt.lower()
        assert "turn-based" in system_prompt.lower()

    def test_user_prompt_formatting(self, ai_agent_with_real_configs) -> None:
        """Test user prompt formatting with context."""
        agent = ai_agent_with_real_configs

        turn_history = [
            {
                "turn_number": 1,
                "player_email": "player@example.com",
                "email_content": {
                    "body": "I want to explore the mysterious castle",
                    "timestamp": "2023-01-01T10:00:00Z",
                },
            }
        ]

        session_context = {
            "game_type": "dungeon",
            "current_player": "player@example.com",
        }

        user_prompt = agent._build_user_prompt(
            player_input="I cast a light spell",
            turn_history=turn_history,
            session_context=session_context,
        )

        assert "Previous Session History" in user_prompt
        assert "mysterious castle" in user_prompt
        assert "I cast a light spell" in user_prompt
        assert "adventure story" in user_prompt

    def test_intimacy_prompt_differences(self, ai_agent_with_real_configs) -> None:
        """Test that intimacy prompts have different instructions."""
        agent = ai_agent_with_real_configs

        session_context = {
            "game_type": "intimacy",
            "current_player": "partner1@example.com",
        }

        user_prompt = agent._build_user_prompt(
            player_input="We've been having communication issues",
            session_context=session_context,
        )

        assert "therapeutic guidance" in user_prompt
        assert "validate emotions" in user_prompt
        assert "communication issues" in user_prompt

    def test_fallback_responses_are_appropriate(
        self, ai_agent_with_real_configs
    ) -> None:
        """Test that fallback responses match game types."""
        agent = ai_agent_with_real_configs

        dungeon_fallback = agent._get_fallback_response("dungeon")
        intimacy_fallback = agent._get_fallback_response("intimacy")

        # Dungeon fallback should be adventure-themed
        assert "adventure" in dungeon_fallback.lower()
        assert "Dungeon Master" in dungeon_fallback

        # Intimacy fallback should be therapeutic
        assert "therapeutic" in intimacy_fallback.lower()
        assert "Dr." in intimacy_fallback
        assert "LMFT" in intimacy_fallback

    def test_initialization_response_loads_templates(
        self, ai_agent_with_real_configs
    ) -> None:
        """Test that initialization responses use real templates if available."""
        agent = ai_agent_with_real_configs

        # Test dungeon initialization
        dungeon_response = agent.generate_initialization_response(
            game_type="dungeon",
            player_email="player@example.com",
            session_id="test-456",
        )

        assert "test-456" in dungeon_response
        assert (
            "player@example.com" in dungeon_response
            or "adventurer" in dungeon_response.lower()
        )

        # Test intimacy initialization
        intimacy_response = agent.generate_initialization_response(
            game_type="intimacy",
            player_email="couple@example.com",
            session_id="test-789",
        )

        assert "test-789" in intimacy_response
        assert (
            "couple@example.com" in intimacy_response
            or "therapy" in intimacy_response.lower()
        )


class TestConfigValidation:
    """Validate that game configurations have required elements."""

    def test_config_files_exist(self) -> None:
        """Test that required configuration files exist."""
        from pathlib import Path

        games_dir = Path(__file__).parent.parent / "games"

        # Check dungeon files
        dungeon_dir = games_dir / "dungeon"
        assert (dungeon_dir / "AGENT.md").exists(), "Dungeon AGENT.md missing"
        assert (
            dungeon_dir / "init-template.md"
        ).exists(), "Dungeon init-template.md missing"
        assert (
            dungeon_dir / "invite-template.md"
        ).exists(), "Dungeon invite-template.md missing"

        # Check intimacy files
        intimacy_dir = games_dir / "intimacy"
        assert (intimacy_dir / "AGENT.md").exists(), "Intimacy AGENT.md missing"
        assert (
            intimacy_dir / "init-template.md"
        ).exists(), "Intimacy init-template.md missing"
        assert (
            intimacy_dir / "invite-template.md"
        ).exists(), "Intimacy invite-template.md missing"

    def test_agent_configs_have_required_sections(self) -> None:
        """Test that agent configurations have required sections."""
        from pathlib import Path

        games_dir = Path(__file__).parent.parent / "games"

        # Test dungeon config
        dungeon_config = (games_dir / "dungeon" / "AGENT.md").read_text()
        assert "# Role" in dungeon_config or "## Role" in dungeon_config
        assert "response" in dungeon_config.lower()

        # Test intimacy config
        intimacy_config = (games_dir / "intimacy" / "AGENT.md").read_text()
        assert "therapist" in intimacy_config.lower()
        assert "response" in intimacy_config.lower()

    def test_init_templates_have_placeholders(self) -> None:
        """Test that init templates have required placeholders."""
        from pathlib import Path

        games_dir = Path(__file__).parent.parent / "games"

        # Test dungeon init template
        dungeon_init = (games_dir / "dungeon" / "init-template.md").read_text()
        assert "{session_id}" in dungeon_init or "session" in dungeon_init.lower()

        # Test intimacy init template
        intimacy_init = (games_dir / "intimacy" / "init-template.md").read_text()
        assert "{session_id}" in intimacy_init or "session" in intimacy_init.lower()
