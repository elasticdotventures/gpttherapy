"""
AI Agent integration with AWS Bedrock for GPT Therapy responses.
Handles different agent types (dungeon, intimacy) and generates contextual responses.
"""

import json
import logging
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class AIAgent:
    """Manages AI agent interactions using AWS Bedrock."""

    def __init__(self) -> None:
        from .settings import settings

        self.aws_region = settings.AWS_REGION
        self.bedrock_client = boto3.client(
            "bedrock-runtime", region_name=self.aws_region
        )

        # Model configuration
        self.model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
        self.max_tokens = 2000
        self.temperature = 0.7

        # Load agent configurations
        self.agent_configs = self._load_agent_configs()

    def _load_agent_configs(self) -> dict[str, str]:
        """Load agent configuration files from games directory."""
        configs = {}
        games_dir = Path(__file__).parent.parent / "games"

        for game_type in ["dungeon", "intimacy"]:
            agent_file = games_dir / game_type / "AGENT.md"
            try:
                if agent_file.exists():
                    configs[game_type] = agent_file.read_text()
                    logger.info(f"Loaded agent config for {game_type}")
                else:
                    logger.warning(f"Agent config not found for {game_type}")
            except Exception as e:
                logger.error(f"Error loading agent config for {game_type}: {e}")

        return configs

    def generate_response(
        self,
        game_type: str,
        session_context: dict[str, Any],
        player_input: str,
        turn_history: list[dict[str, Any]] | None = None,
        game_state: dict[str, Any] | None = None,
    ) -> str:
        """
        Generate an AI response based on game type and context.

        Args:
            game_type: Type of game/therapy (dungeon, intimacy)
            session_context: Current session state and metadata
            player_input: The player's latest input/email content
            turn_history: Previous turns in the session
            game_state: Rich game state data (characters, world, narrative)

        Returns:
            Generated AI response text
        """
        try:
            # Build the prompt
            system_prompt = self._build_system_prompt(
                game_type, session_context, game_state
            )
            user_prompt = self._build_user_prompt(
                player_input, turn_history, session_context, game_state
            )

            # Call Bedrock
            response = self._call_bedrock(system_prompt, user_prompt)

            logger.info(
                f"Generated response for {game_type} session {session_context.get('session_id')}"
            )
            return response

        except Exception as e:
            logger.error(f"Error generating AI response: {str(e)}")
            return self._get_fallback_response(game_type)

    def _build_system_prompt(
        self,
        game_type: str,
        session_context: dict[str, Any],
        game_state: dict[str, Any] | None = None,
    ) -> str:
        """Build the system prompt with agent configuration."""
        agent_config = self.agent_configs.get(game_type, "")

        if not agent_config:
            logger.warning(f"No agent config found for {game_type}, using default")
            agent_config = "You are a helpful AI assistant facilitating a therapeutic conversation."

        # Add session-specific context
        context_parts = [
            f"""

## Current Session Context
- Session ID: {session_context.get("session_id", "unknown")}
- Game Type: {game_type}
- Turn Count: {session_context.get("turn_count", 0)}
- Players: {", ".join(session_context.get("players", []))}
- Status: {session_context.get("status", "unknown")}"""
        ]

        # Add game state context if available
        if game_state:
            context_parts.append("\n## Game State Information")

            # Add character states for dungeon games
            if game_type == "dungeon" and "character_states" in game_state:
                context_parts.append("### Character States")
                for char_state in game_state["character_states"].values():
                    context_parts.append(
                        f"- {char_state.get('name', 'Unknown')}: Level {char_state.get('level', 1)}, Health {char_state.get('health', 100)}, Location: {char_state.get('location', 'unknown')}"
                    )

            # Add world state for dungeon games
            if (
                game_type == "dungeon"
                and "world_state" in game_state
                and game_state["world_state"]
            ):
                world = game_state["world_state"]
                context_parts.append("### World State")
                context_parts.append(
                    f"- Current Location: {world.get('current_location', 'unknown')}"
                )
                context_parts.append(
                    f"- Time of Day: {world.get('time_of_day', 'unknown')}"
                )
                context_parts.append(f"- Weather: {world.get('weather', 'clear')}")

            # Add therapy state for therapy sessions
            if (
                game_type == "intimacy"
                and "therapy_state" in game_state
                and game_state["therapy_state"]
            ):
                therapy = game_state["therapy_state"]
                context_parts.append("### Therapy Progress")
                context_parts.append(
                    f"- Current Phase: {therapy.get('current_phase', 'assessment')}"
                )
                if therapy.get("therapy_goals"):
                    context_parts.append(
                        f"- Goals: {', '.join(therapy['therapy_goals'])}"
                    )
                if therapy.get("completed_exercises"):
                    context_parts.append(
                        f"- Completed Exercises: {len(therapy['completed_exercises'])}"
                    )

        context_parts.append(
            """

## Response Guidelines
- Keep responses concise and engaging (500-800 words max for email format)
- Maintain character consistency throughout the session
- Use the email response format specified in your agent configuration
- Consider the turn-based nature - advance the story/therapy appropriately
- Remember this is asynchronous email communication, not real-time chat
"""
        )

        system_additions = "".join(context_parts)

        return str(agent_config) + system_additions

    def _build_user_prompt(
        self,
        player_input: str,
        turn_history: list[dict[str, Any]] | None = None,
        session_context: dict[str, Any] | None = None,
        game_state: dict[str, Any] | None = None,
    ) -> str:
        """Build the user prompt with current input and context."""
        prompt_parts = []

        # Add turn history for context
        if turn_history:
            prompt_parts.append("## Previous Session History")
            for turn in turn_history[-5:]:  # Last 5 turns for context
                player_email = turn.get("player_email", "Unknown")
                email_content = turn.get("email_content", {})
                message = email_content.get("body", "No message content")

                prompt_parts.append(f"**{player_email}**: {message[:200]}...")

            prompt_parts.append("")

        # Add current player input
        prompt_parts.append("## Current Player Input")
        prompt_parts.append(
            f"From: {session_context.get('current_player', 'Unknown player') if session_context else 'Unknown player'}"
        )
        prompt_parts.append(f"Message: {player_input}")
        prompt_parts.append("")

        # Add instructions
        prompt_parts.append("## Instructions")
        prompt_parts.append(
            "Please generate an appropriate response based on your role and the session context. "
        )

        if session_context and session_context.get("game_type") == "dungeon":
            prompt_parts.append(
                "Advance the adventure story, respond to the player's actions, and provide engaging narrative descriptions."
            )
        elif session_context and session_context.get("game_type") == "intimacy":
            prompt_parts.append(
                "Provide therapeutic guidance, validate emotions, and suggest constructive exercises or reflections."
            )

        return "\n".join(prompt_parts)

    def _call_bedrock(self, system_prompt: str, user_prompt: str) -> str:
        """Make the actual call to AWS Bedrock."""
        try:
            # Prepare the request body for Claude
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            }

            # Make the request
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            # Parse the response
            response_body = json.loads(response["body"].read())

            if "content" in response_body and len(response_body["content"]) > 0:
                return str(response_body["content"][0]["text"])
            else:
                logger.error("Unexpected response format from Bedrock")
                return "I apologize, but I'm having trouble generating a response right now."

        except ClientError as e:
            logger.error(f"Bedrock API error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error calling Bedrock: {e}")
            raise

    def _get_fallback_response(self, game_type: str) -> str:
        """Provide a fallback response when AI generation fails."""
        fallbacks = {
            "dungeon": """Thank you for your action! I'm currently processing the adventure and will respond with the next part of your story shortly.

Please check back soon as I work on crafting an engaging continuation of your quest.

Best regards,
Your Dungeon Master""",
            "intimacy": """Thank you for sharing your thoughts and feelings. I'm currently reflecting on your message to provide you with the most helpful therapeutic response.

Please know that your willingness to engage in this process is commendable, and I'll respond with thoughtful guidance soon.

Warmly,
Dr. Alex Chen, LMFT""",
        }

        return fallbacks.get(
            game_type, "Thank you for your message. I'll respond shortly."
        )

    def generate_initialization_response(
        self, game_type: str, player_email: str, session_id: str
    ) -> str:
        """Generate an initial welcome response for new sessions."""
        try:
            # Load the init template
            games_dir = Path(__file__).parent.parent / "games"
            init_file = games_dir / game_type / "init-template.md"

            if init_file.exists():
                template = init_file.read_text()
                # Replace placeholders
                template = template.replace("{session_id}", session_id)
                template = template.replace("{player_email}", player_email)
                return template
            else:
                logger.warning(f"Init template not found for {game_type}")
                return self._get_default_init_response(game_type, session_id)

        except Exception as e:
            logger.error(f"Error loading init template: {e}")
            return self._get_default_init_response(game_type, session_id)

    def _get_default_init_response(self, game_type: str, session_id: str) -> str:
        """Default initialization responses."""
        if game_type == "dungeon":
            return f"""Subject: Welcome to Your Adventure - Session {session_id}

Greetings, brave adventurer!

Welcome to your dungeon adventure session. I am your Dungeon Master, ready to guide you through an epic quest filled with mystery, treasure, and danger.

Your adventure begins now. Please reply to this email with:
1. Your character name
2. Your preferred character class (warrior, mage, rogue, or cleric)
3. A brief description of your character's background

Let the adventure begin!

Your Dungeon Master
Session: {session_id}"""

        elif game_type == "intimacy":
            return f"""Subject: Welcome to Couples Therapy Support - Session {session_id}

Dear Participant,

Thank you for taking this important step toward strengthening your relationship. I'm honored to support you both on this journey of growth and connection.

To begin our work together, please reply with:
1. Your name and your partner's name
2. How long you've been together
3. Your main relationship goals for therapy
4. Any specific concerns you'd like to address

This is a safe, confidential space for growth and healing.

Warmly,
Dr. Alex Chen, LMFT
Session: {session_id}"""

        else:
            return f"""Welcome to GPT Therapy Session {session_id}

Thank you for starting your journey with us. Please reply with some information about what you're looking for, and we'll get started.

Session: {session_id}"""


# Convenience function for Lambda usage
def get_ai_agent() -> AIAgent:
    """Get a configured AIAgent instance."""
    return AIAgent()


def generate_ai_response(
    game_type: str,
    session_context: dict[str, Any],
    player_input: str,
    turn_history: list[dict[str, Any]] | None = None,
) -> str:
    """
    Convenience function to generate AI response without creating agent instance.

    Args:
        game_type: Type of game/therapy (dungeon, intimacy)
        session_context: Current session state and metadata
        player_input: The player's latest input/email content
        turn_history: Previous turns in the session

    Returns:
        Generated AI response text
    """
    agent = get_ai_agent()
    return agent.generate_response(
        game_type, session_context, player_input, turn_history
    )
