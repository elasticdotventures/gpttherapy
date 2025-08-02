"""
MCP Tools for GPTTherapy Session Management

Provides secure MCP tool calling for Bedrock models with session ID isolation.
The authentication layer ensures models CANNOT access or specify session IDs directly.

Security Architecture:
1. Lambda maintains session context (session_id is NEVER exposed to model)
2. MCP tools receive pre-authenticated context from lambda
3. Bedrock model can call tools but cannot access session identifiers
4. All session operations are scoped to the authenticated session only

This prevents session hijacking and ensures models operate within their authorized context.
"""

from datetime import datetime
from typing import Any

import structlog
from fastmcp import FastMCP
from returns.result import Failure

from .game_engine import GameEngine
from .state_machines import StateMachineManager
from .storage import StorageManager

logger = structlog.get_logger()


class SessionSecurityContext:
    """
    Secure session context that isolates session ID from model access.

    This is the authentication layer - the lambda sets the session_id
    but the model NEVER sees it or provides it as a parameter.
    """

    def __init__(self, session_id: str, player_email: str, game_type: str):
        self._session_id = session_id  # Private - model cannot access
        self._player_email = player_email
        self._game_type = game_type
        self._created_at = datetime.now()

    @property
    def session_id(self) -> str:
        """Session ID - only accessible to lambda, never exposed to model."""
        return self._session_id

    @property
    def player_email(self) -> str:
        return self._player_email

    @property
    def game_type(self) -> str:
        return self._game_type

    def to_model_context(self) -> dict[str, Any]:
        """
        Returns safe context for model - NO session ID included.
        Model gets enough info to make decisions without security access.
        """
        return {
            "game_type": self._game_type,
            "player_email": self._player_email,
            "timestamp": self._created_at.isoformat(),
        }


class GPTTherapyMCPServer:
    """
    Secure MCP server for GPTTherapy session management.

    Key Security Features:
    - Session ID isolation (models cannot access or specify session IDs)
    - Pre-authenticated context injection by lambda
    - Scoped operations (tools only work within authenticated session)
    """

    def __init__(self):
        self.mcp = FastMCP("GPTTherapy Session Manager")
        self.storage = StorageManager()
        self.game_engine = GameEngine()
        self.state_manager = StateMachineManager()
        self._session_context: SessionSecurityContext | None = None
        self._tool_functions = {}  # Store tool function references

        # Register secure tools
        self._register_tools()

    def set_session_context(self, context: SessionSecurityContext):
        """
        Lambda-only method to set authenticated session context.

        SECURITY: This method is ONLY called by the lambda function
        after it has authenticated the email/session. The model
        NEVER has access to this method or the session_id.
        """
        self._session_context = context
        logger.info(
            "Session context authenticated",
            game_type=context.game_type,
            player_email=context.player_email,
            # NOTE: session_id is NOT logged for security
        )

    def _ensure_authenticated(self) -> SessionSecurityContext:
        """Ensure session is authenticated before tool execution."""
        if self._session_context is None:
            raise ValueError(
                "No authenticated session context - lambda security violation"
            )
        return self._session_context

    def _register_tools(self):
        """Register MCP tools with security isolation."""

        @self.mcp.tool
        async def get_session_status() -> dict[str, Any]:
            """
            Get current session status and state.

            Returns session information without exposing session ID.
            Model can use this to understand current game state.
            """
            ctx = self._ensure_authenticated()

            # Use session_id internally but don't expose to model
            result = self.storage.get_session(ctx.session_id)
            if isinstance(result, Failure):
                return {"error": "Failed to retrieve session", "status": "error"}

            session = result.unwrap()
            if not session:
                return {"error": "Session not found", "status": "error"}

            # Return safe session info (no session_id exposed)
            return {
                "status": session.get("status", "unknown"),
                "game_type": session.get("game_type", "unknown"),
                "turn_count": session.get("turn_count", 0),
                "player_count": len(session.get("players", [])),
                "created_at": session.get("created_at"),
                "last_activity": session.get("last_activity"),
            }

        @self.mcp.tool
        async def get_turn_history(limit: int = 5) -> list[dict[str, Any]]:
            """
            Get recent turn history for current session.

            Args:
                limit: Number of recent turns to retrieve (default 5)

            Returns:
                List of recent turns without exposing session ID
            """
            ctx = self._ensure_authenticated()

            result = self.storage.get_session_turns(ctx.session_id, limit=limit)
            if isinstance(result, Failure):
                return [{"error": "Failed to retrieve turns"}]

            turns = result.unwrap()

            # Sanitize turns for model consumption (remove session_id references)
            safe_turns = []
            for turn in turns:
                safe_turn = {
                    "turn_number": turn.get("turn_number"),
                    "player_email": turn.get("player_email"),
                    "content": turn.get("content"),
                    "timestamp": turn.get("timestamp"),
                    "ai_response": turn.get("ai_response"),
                }
                safe_turns.append(safe_turn)

            return safe_turns

        @self.mcp.tool
        async def update_game_state(
            state_update: str, reason: str = "AI decision"
        ) -> dict[str, Any]:
            """
            Update game state based on AI analysis.

            Args:
                state_update: Description of state change to make
                reason: Reason for the state change

            Returns:
                Result of state update without session ID exposure
            """
            ctx = self._ensure_authenticated()

            try:
                # Use authenticated session_id internally
                session_result = self.storage.get_session(ctx.session_id)
                if isinstance(session_result, Failure):
                    return {"error": "Session access failed", "success": False}

                session = session_result.unwrap()
                if not session:
                    return {"error": "Session not found", "success": False}

                # Update session with state change
                session["last_ai_action"] = {
                    "action": state_update,
                    "reason": reason,
                    "timestamp": datetime.now().isoformat(),
                }
                session["last_activity"] = datetime.now().isoformat()

                update_result = self.storage.update_session(ctx.session_id, session)
                if isinstance(update_result, Failure):
                    return {"error": "State update failed", "success": False}

                return {
                    "success": True,
                    "action": state_update,
                    "reason": reason,
                    "timestamp": session["last_activity"],
                }

            except Exception as e:
                logger.error("State update error", error=str(e))
                return {"error": "Internal state update error", "success": False}

        @self.mcp.tool
        async def check_player_status(player_email: str) -> dict[str, Any]:
            """
            Check status of a specific player in the current session.

            Args:
                player_email: Email of player to check

            Returns:
                Player status without session ID exposure
            """
            ctx = self._ensure_authenticated()

            result = self.storage.get_player_status(player_email, ctx.session_id)
            if isinstance(result, Failure):
                return {"error": "Failed to check player status", "found": False}

            player_data = result.unwrap()
            if not player_data:
                return {"found": False, "player_email": player_email}

            return {
                "found": True,
                "player_email": player_email,
                "status": player_data.get("status", "unknown"),
                "last_turn": player_data.get("last_turn_timestamp"),
                "turn_count": player_data.get("turn_count", 0),
            }

        @self.mcp.tool
        async def add_player(player_email: str) -> dict[str, Any]:
            """
            Add a new player to the current session.

            SECURITY: Only allowed during initialization phase.
            Fails once game has started to prevent session tampering.

            Args:
                player_email: Email of player to add to session

            Returns:
                Result of player addition without session ID exposure
            """
            ctx = self._ensure_authenticated()

            try:
                # Get current session to check state
                session_result = self.storage.get_session(ctx.session_id)
                if isinstance(session_result, Failure):
                    return {"error": "Session access failed", "success": False}

                session = session_result.unwrap()
                if not session:
                    return {"error": "Session not found", "success": False}

                # Check if game is in initialization phase
                session_status = session.get("status", "unknown")
                if session_status not in ["initializing", "waiting_for_players"]:
                    return {
                        "error": "Cannot add players after game has started",
                        "success": False,
                        "current_status": session_status,
                        "allowed_statuses": ["initializing", "waiting_for_players"],
                    }

                # Check if player already exists
                current_players = session.get("players", [])
                if player_email in current_players:
                    return {
                        "error": "Player already in session",
                        "success": False,
                        "player_email": player_email,
                    }

                # Add player to session
                current_players.append(player_email)
                session["players"] = current_players
                session["last_activity"] = datetime.now().isoformat()

                # Update session in storage
                update_result = self.storage.update_session(ctx.session_id, session)
                if isinstance(update_result, Failure):
                    return {"error": "Failed to update session", "success": False}

                return {
                    "success": True,
                    "player_email": player_email,
                    "player_count": len(current_players),
                    "session_status": session_status,
                    "message": f"Player {player_email} added successfully",
                }

            except Exception as e:
                logger.error("Add player error", error=str(e))
                return {"error": "Internal error adding player", "success": False}

        @self.mcp.tool
        async def get_game_rules() -> dict[str, Any]:
            """
            Get game rules and configuration for current game type.

            Returns:
                Game rules without session-specific information
            """
            ctx = self._ensure_authenticated()

            # Load game rules based on game type
            rules_path = f"games/{ctx.game_type}/AGENT.md"
            try:
                from pathlib import Path

                rules_file = Path(rules_path)
                if rules_file.exists():
                    rules_content = rules_file.read_text()
                    return {
                        "game_type": ctx.game_type,
                        "rules_content": rules_content,
                        "loaded": True,
                    }
                else:
                    return {
                        "game_type": ctx.game_type,
                        "error": "Rules file not found",
                        "loaded": False,
                    }
            except Exception as e:
                return {
                    "game_type": ctx.game_type,
                    "error": f"Failed to load rules: {str(e)}",
                    "loaded": False,
                }

    def get_tools_for_model(self) -> list[dict[str, Any]]:
        """
        Get tool definitions for Bedrock model.

        Returns tool schemas without any session ID references.
        The model sees tool capabilities but cannot access session context.
        """
        return [
            {
                "name": "get_session_status",
                "description": "Get current session status and game state",
                "parameters": {"type": "object", "properties": {}},
            },
            {
                "name": "get_turn_history",
                "description": "Get recent turn history for context",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {
                            "type": "integer",
                            "description": "Number of recent turns to retrieve",
                            "default": 5,
                        }
                    },
                },
            },
            {
                "name": "update_game_state",
                "description": "Update game state based on AI analysis",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "state_update": {
                            "type": "string",
                            "description": "Description of state change to make",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reason for the state change",
                            "default": "AI decision",
                        },
                    },
                    "required": ["state_update"],
                },
            },
            {
                "name": "check_player_status",
                "description": "Check status of a specific player",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "player_email": {
                            "type": "string",
                            "description": "Email of player to check",
                        }
                    },
                    "required": ["player_email"],
                },
            },
            {
                "name": "add_player",
                "description": "Add a new player to the session (only during initialization)",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "player_email": {
                            "type": "string",
                            "description": "Email of player to add to session",
                        }
                    },
                    "required": ["player_email"],
                },
            },
            {
                "name": "get_game_rules",
                "description": "Get game rules and configuration",
                "parameters": {"type": "object", "properties": {}},
            },
        ]

    async def execute_tool_call(
        self, tool_name: str, parameters: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Execute MCP tool call with authenticated session context.

        SECURITY: Session context is pre-authenticated by lambda.
        Model cannot specify or access session_id parameters.
        """
        if self._session_context is None:
            return {"error": "No authenticated session context"}

        try:
            # Use FastMCP's internal tool execution
            # The tools are already registered with @self.mcp.tool decorators
            # We need to call them through the FastMCP server directly

            if tool_name == "get_session_status":
                # Call the registered tool function
                async def get_session_status_wrapper():
                    ctx = self._ensure_authenticated()
                    result = self.storage.get_session(ctx.session_id)
                    if isinstance(result, Failure):
                        return {
                            "error": "Failed to retrieve session",
                            "status": "error",
                        }

                    session = result.unwrap()
                    if not session:
                        return {"error": "Session not found", "status": "error"}

                    return {
                        "status": session.get("status", "unknown"),
                        "game_type": session.get("game_type", "unknown"),
                        "turn_count": session.get("turn_count", 0),
                        "player_count": len(session.get("players", [])),
                        "created_at": session.get("created_at"),
                        "last_activity": session.get("last_activity"),
                    }

                return await get_session_status_wrapper()

            elif tool_name == "get_turn_history":
                limit = parameters.get("limit", 5)

                async def get_turn_history_wrapper():
                    ctx = self._ensure_authenticated()
                    result = self.storage.get_session_turns(ctx.session_id, limit=limit)
                    if isinstance(result, Failure):
                        return [{"error": "Failed to retrieve turns"}]

                    turns = result.unwrap()
                    safe_turns = []
                    for turn in turns:
                        safe_turn = {
                            "turn_number": turn.get("turn_number"),
                            "player_email": turn.get("player_email"),
                            "content": turn.get("content"),
                            "timestamp": turn.get("timestamp"),
                            "ai_response": turn.get("ai_response"),
                        }
                        safe_turns.append(safe_turn)
                    return safe_turns

                return await get_turn_history_wrapper()

            elif tool_name == "update_game_state":
                state_update = parameters.get("state_update")
                reason = parameters.get("reason", "AI decision")

                async def update_game_state_wrapper():
                    ctx = self._ensure_authenticated()
                    try:
                        session_result = self.storage.get_session(ctx.session_id)
                        if isinstance(session_result, Failure):
                            return {"error": "Session access failed", "success": False}

                        session = session_result.unwrap()
                        if not session:
                            return {"error": "Session not found", "success": False}

                        session["last_ai_action"] = {
                            "action": state_update,
                            "reason": reason,
                            "timestamp": datetime.now().isoformat(),
                        }
                        session["last_activity"] = datetime.now().isoformat()

                        update_result = self.storage.update_session(
                            ctx.session_id, session
                        )
                        if isinstance(update_result, Failure):
                            return {"error": "State update failed", "success": False}

                        return {
                            "success": True,
                            "action": state_update,
                            "reason": reason,
                            "timestamp": session["last_activity"],
                        }
                    except Exception as e:
                        logger.error("State update error", error=str(e))
                        return {
                            "error": "Internal state update error",
                            "success": False,
                        }

                return await update_game_state_wrapper()

            elif tool_name == "check_player_status":
                player_email = parameters.get("player_email")

                async def check_player_status_wrapper():
                    ctx = self._ensure_authenticated()
                    result = self.storage.get_player_status(
                        player_email, ctx.session_id
                    )
                    if isinstance(result, Failure):
                        return {
                            "error": "Failed to check player status",
                            "found": False,
                        }

                    player_data = result.unwrap()
                    if not player_data:
                        return {"found": False, "player_email": player_email}

                    return {
                        "found": True,
                        "player_email": player_email,
                        "status": player_data.get("status", "unknown"),
                        "last_turn": player_data.get("last_turn_timestamp"),
                        "turn_count": player_data.get("turn_count", 0),
                    }

                return await check_player_status_wrapper()

            elif tool_name == "add_player":
                player_email = parameters.get("player_email")

                async def add_player_wrapper():
                    ctx = self._ensure_authenticated()
                    try:
                        session_result = self.storage.get_session(ctx.session_id)
                        if isinstance(session_result, Failure):
                            return {"error": "Session access failed", "success": False}

                        session = session_result.unwrap()
                        if not session:
                            return {"error": "Session not found", "success": False}

                        session_status = session.get("status", "unknown")
                        if session_status not in [
                            "initializing",
                            "waiting_for_players",
                        ]:
                            return {
                                "error": "Cannot add players after game has started",
                                "success": False,
                                "current_status": session_status,
                                "allowed_statuses": [
                                    "initializing",
                                    "waiting_for_players",
                                ],
                            }

                        current_players = session.get("players", [])
                        if player_email in current_players:
                            return {
                                "error": "Player already in session",
                                "success": False,
                                "player_email": player_email,
                            }

                        current_players.append(player_email)
                        session["players"] = current_players
                        session["last_activity"] = datetime.now().isoformat()

                        update_result = self.storage.update_session(
                            ctx.session_id, session
                        )
                        if isinstance(update_result, Failure):
                            return {
                                "error": "Failed to update session",
                                "success": False,
                            }

                        return {
                            "success": True,
                            "player_email": player_email,
                            "player_count": len(current_players),
                            "session_status": session_status,
                            "message": f"Player {player_email} added successfully",
                        }
                    except Exception as e:
                        logger.error("Add player error", error=str(e))
                        return {
                            "error": "Internal error adding player",
                            "success": False,
                        }

                return await add_player_wrapper()

            elif tool_name == "get_game_rules":

                async def get_game_rules_wrapper():
                    ctx = self._ensure_authenticated()
                    rules_path = f"games/{ctx.game_type}/AGENT.md"
                    try:
                        from pathlib import Path

                        rules_file = Path(rules_path)
                        if rules_file.exists():
                            rules_content = rules_file.read_text()
                            return {
                                "game_type": ctx.game_type,
                                "rules_content": rules_content,
                                "loaded": True,
                            }
                        else:
                            return {
                                "game_type": ctx.game_type,
                                "error": "Rules file not found",
                                "loaded": False,
                            }
                    except Exception as e:
                        return {
                            "game_type": ctx.game_type,
                            "error": f"Failed to load rules: {str(e)}",
                            "loaded": False,
                        }

                return await get_game_rules_wrapper()
            else:
                return {"error": f"Tool {tool_name} not found"}

        except Exception as e:
            logger.error("Tool execution error", tool=tool_name, error=str(e))
            return {"error": f"Tool execution failed: {str(e)}"}
