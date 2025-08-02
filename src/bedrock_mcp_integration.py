"""
Bedrock MCP Integration for GPTTherapy

Integrates AWS Bedrock with MCP tool calling while maintaining strict session security.
The session ID is NEVER exposed to the model - it's managed by the lambda context only.

Security Architecture:
1. Lambda authenticates session and creates secure context
2. MCP tools are pre-authorized with session context
3. Bedrock model can call tools but cannot access session identifiers
4. All operations are scoped to the authenticated session
"""

import json
from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError

from .mcp_tools import GPTTherapyMCPServer, SessionSecurityContext

logger = structlog.get_logger()


class BedrockMCPAgent:
    """
    Enhanced AI Agent with MCP tool calling capabilities.

    Maintains strict security isolation - session ID never exposed to model.
    """

    def __init__(self):
        from .settings import settings

        self.aws_region = settings.AWS_REGION
        self.bedrock_client = boto3.client(
            "bedrock-runtime", region_name=self.aws_region
        )

        # Model configuration
        self.model_id = "anthropic.claude-3-sonnet-20240229-v1:0"
        self.max_tokens = 2000
        self.temperature = 0.7

        # Initialize MCP server with security context
        self.mcp_server = GPTTherapyMCPServer()
        self._session_context: SessionSecurityContext | None = None

    def set_session_context(self, session_id: str, player_email: str, game_type: str):
        """
        Set authenticated session context for MCP operations.

        SECURITY: This method is ONLY called by lambda after authentication.
        The session_id is stored securely and never exposed to the model.
        """
        self._session_context = SessionSecurityContext(
            session_id=session_id, player_email=player_email, game_type=game_type
        )

        # Configure MCP server with authenticated context
        self.mcp_server.set_session_context(self._session_context)

        logger.info(
            "Bedrock MCP session authenticated",
            game_type=game_type,
            player_email=player_email,
            # NOTE: session_id intentionally not logged for security
        )

    def generate_response_with_tools(
        self,
        game_type: str,
        session_context: dict[str, Any],
        player_input: str,
        turn_history: list[dict[str, Any]] | None = None,
        agent_config: str | None = None,
    ) -> str:
        """
        Generate AI response with MCP tool calling capabilities.

        The model can call tools but session_id remains isolated in lambda context.

        Args:
            game_type: Type of game (dungeon, intimacy)
            session_context: Session metadata (WITHOUT session_id)
            player_input: Player's message
            turn_history: Previous turns for context
            agent_config: Agent role configuration

        Returns:
            Generated response with tool calls executed
        """
        if self._session_context is None:
            raise ValueError(
                "Session context not authenticated - lambda security violation"
            )

        try:
            # Build prompts with MCP tool capabilities
            system_prompt = self._build_system_prompt_with_tools(
                agent_config, game_type, session_context
            )
            user_prompt = self._build_user_prompt(player_input, turn_history)

            # Get tool definitions (NO session ID exposed)
            tools = self.mcp_server.get_tools_for_model()

            # Call Bedrock with tool support
            response = self._call_bedrock_with_tools(system_prompt, user_prompt, tools)

            return response

        except Exception as e:
            logger.error("Error in MCP-enabled response generation", error=str(e))
            return self._get_fallback_response(game_type)

    def _build_system_prompt_with_tools(
        self,
        agent_config: str | None,
        game_type: str,
        session_context: dict[str, Any],
    ) -> str:
        """
        Build system prompt with MCP tool capabilities.

        SECURITY: session_context provided here does NOT contain session_id.
        Only safe context information is included.
        """
        base_config = agent_config or self._get_default_agent_config(game_type)

        # Add MCP tool instructions (no session ID references)
        tool_instructions = """

## Available Tools

You have access to the following tools to enhance your responses:

1. **get_session_status()** - Get current session status and game state
2. **get_turn_history(limit=5)** - Get recent conversation history
3. **update_game_state(state_update, reason)** - Update game state based on your analysis
4. **check_player_status(player_email)** - Check status of specific players
5. **get_game_rules()** - Get game rules and configuration

### Tool Usage Guidelines:

- Use tools BEFORE generating your response to get current context
- Always call get_session_status() first to understand current state
- Use get_turn_history() to understand conversation flow
- Update game state when story/therapy progresses significantly
- Tools help you provide more contextual and accurate responses

### Security Note:
- You CANNOT access or specify session IDs - they are managed securely
- Focus on using tools to enhance player experience within your authorized context
- All tool calls are automatically scoped to the current session
"""

        # Add safe session context (NO session_id)
        safe_context = f"""

## Session Context
- Game Type: {game_type}
- Turn Count: {session_context.get("turn_count", 0)}
- Status: {session_context.get("status", "active")}
- Player Count: {len(session_context.get("players", []))}

Remember: Use tools to get real-time information before responding.
"""

        return base_config + tool_instructions + safe_context

    def _build_user_prompt(
        self, player_input: str, turn_history: list[dict[str, Any]] | None = None
    ) -> str:
        """Build user prompt with current input."""
        prompt_parts = []

        # Add recent history context if available
        if turn_history:
            prompt_parts.append("## Recent History (for reference)")
            for turn in turn_history[-3:]:  # Last 3 turns
                player = turn.get("player_email", "Player")
                content = turn.get("content", "")[:150] + "..."
                prompt_parts.append(f"**{player}**: {content}")
            prompt_parts.append("")

        # Add current input
        prompt_parts.append("## Current Player Message")
        prompt_parts.append(player_input)
        prompt_parts.append("")

        # Add tool usage reminder
        prompt_parts.append("## Instructions")
        prompt_parts.append(
            "Before generating your response, use the available tools to:"
            "\n1. Check current session status"
            "\n2. Get recent turn history if needed"
            "\n3. Update game state if story/therapy has progressed"
            "\n\nThen provide an engaging, contextual response."
        )

        return "\n".join(prompt_parts)

    def _call_bedrock_with_tools(
        self, system_prompt: str, user_prompt: str, tools: list[dict[str, Any]]
    ) -> str:
        """
        Call Bedrock with tool support using Claude 3.5's function calling.

        Handles tool calls and executes them through MCP server.
        """
        try:
            # Prepare messages
            messages = [{"role": "user", "content": user_prompt}]

            # Bedrock request body with tools
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "system": system_prompt,
                "messages": messages,
                "tools": tools,
            }

            # Make initial request
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())

            # Process response and handle tool calls
            return self._process_bedrock_response(response_body, messages, tools)

        except ClientError as e:
            logger.error("Bedrock API error", error=str(e))
            raise
        except Exception as e:
            logger.error("Unexpected error calling Bedrock", error=str(e))
            raise

    def _process_bedrock_response(
        self,
        response_body: dict[str, Any],
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str:
        """
        Process Bedrock response and handle tool calls.

        If model requests tool calls, execute them and continue conversation.
        """
        if "content" not in response_body:
            return "I apologize, but I'm having trouble generating a response."

        content = response_body["content"]

        # Check for tool calls
        tool_calls = []
        text_content = ""

        for item in content:
            if item.get("type") == "text":
                text_content += item.get("text", "")
            elif item.get("type") == "tool_use":
                tool_calls.append(item)

        # If no tool calls, return text response
        if not tool_calls:
            return text_content

        # Execute tool calls
        tool_results = []
        for tool_call in tool_calls:
            tool_name = tool_call.get("name")
            tool_input = tool_call.get("input", {})
            tool_id = tool_call.get("id")

            try:
                # Execute tool with authenticated session context
                result = self._execute_mcp_tool(tool_name, tool_input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(result),
                    }
                )
            except Exception as e:
                logger.error("Tool execution failed", tool=tool_name, error=str(e))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": json.dumps(
                            {"error": f"Tool execution failed: {str(e)}"}
                        ),
                        "is_error": True,
                    }
                )

        # Continue conversation with tool results
        if tool_results:
            return self._continue_conversation_with_tools(
                messages, content, tool_results, tools
            )
        else:
            return text_content

    async def _execute_mcp_tool(
        self, tool_name: str, tool_input: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Execute MCP tool with authenticated session context.

        SECURITY: Session context is pre-authenticated, model cannot specify session_id.
        """
        return await self.mcp_server.execute_tool_call(tool_name, tool_input)

    def _continue_conversation_with_tools(
        self,
        messages: list[dict[str, Any]],
        assistant_content: list[dict[str, Any]],
        tool_results: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> str:
        """Continue conversation with tool results to get final response."""
        try:
            # Add assistant message with tool calls
            messages.append({"role": "assistant", "content": assistant_content})

            # Add tool results as user message
            messages.append({"role": "user", "content": tool_results})

            # Make follow-up request for final response
            body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "messages": messages,
                "tools": tools,
            }

            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )

            response_body = json.loads(response["body"].read())

            # Extract final text response
            if "content" in response_body:
                text_parts = []
                for item in response_body["content"]:
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                return "".join(text_parts)

            return "Response generated with tool assistance."

        except Exception as e:
            logger.error("Error in tool conversation continuation", error=str(e))
            return "I've gathered information using available tools, but encountered an issue in generating the final response."

    def _get_default_agent_config(self, game_type: str) -> str:
        """Get default agent configuration if none provided."""
        configs = {
            "dungeon": """You are an experienced Dungeon Master running an engaging fantasy adventure.
Create immersive narratives, manage character interactions, and guide players through exciting quests.""",
            "intimacy": """You are Dr. Alex Chen, a licensed marriage and family therapist.
Provide compassionate, professional guidance to help couples improve their communication and strengthen their relationship.""",
        }
        return configs.get(game_type, "You are a helpful AI assistant.")

    def _get_fallback_response(self, game_type: str) -> str:
        """Fallback response when tool-enabled generation fails."""
        fallbacks = {
            "dungeon": "Thank you for your action! I'm processing the adventure and will respond with an engaging continuation of your quest shortly.",
            "intimacy": "Thank you for sharing. I'm reflecting on your message to provide you with thoughtful therapeutic guidance.",
        }
        return fallbacks.get(
            game_type, "Thank you for your message. I'll respond shortly."
        )


# Convenience functions for Lambda integration
def create_bedrock_mcp_agent() -> BedrockMCPAgent:
    """Create a configured Bedrock MCP agent."""
    return BedrockMCPAgent()


def generate_mcp_response(
    session_id: str,
    player_email: str,
    game_type: str,
    session_context: dict[str, Any],
    player_input: str,
    turn_history: list[dict[str, Any]] | None = None,
    agent_config: str | None = None,
) -> str:
    """
    Generate AI response with MCP tool calling.

    SECURITY: session_id is provided by lambda (trusted) but never exposed to model.

    Args:
        session_id: Authenticated session ID (lambda-only, not exposed to model)
        player_email: Authenticated player email
        game_type: Type of game/therapy
        session_context: Safe session context (no session_id)
        player_input: Player's message
        turn_history: Previous turns
        agent_config: Agent role configuration

    Returns:
        AI-generated response with tool assistance
    """
    agent = create_bedrock_mcp_agent()

    # Set authenticated session context (session_id isolated from model)
    agent.set_session_context(session_id, player_email, game_type)

    # Generate response with tools (model cannot access session_id)
    return agent.generate_response_with_tools(
        game_type=game_type,
        session_context=session_context,
        player_input=player_input,
        turn_history=turn_history,
        agent_config=agent_config,
    )
