"""
Turn-based game engine for GPT Therapy sessions.
Handles player coordination, turn ordering, and game state progression.
"""

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from datetime_utils import timestamps

try:
    from state_machines import (
        SessionState,
        StateMachineManager,
        get_state_machine_manager,
    )
    from storage import StorageManager
except ImportError:
    from state_machines import (
        SessionState,
        StateMachineManager,
        get_state_machine_manager,
    )
    from storage import StorageManager

logger = logging.getLogger(__name__)


class GameEngine:
    """Manages turn-based game logic and player coordination."""

    def __init__(
        self,
        storage_manager: StorageManager = None,
        state_manager: StateMachineManager = None,
    ):
        self.storage = storage_manager or StorageManager()
        self.state_manager = state_manager or get_state_machine_manager()

        # Game configuration
        self.max_players = {"dungeon": 4, "intimacy": 2}

        self.min_players = {"dungeon": 1, "intimacy": 2}

        # Turn timeout settings (in hours)
        self.turn_timeout = {
            "dungeon": 24,  # 24 hours for adventure games
            "intimacy": 72,  # 72 hours for therapy sessions
        }

    def process_player_turn(
        self, session_id: str, player_email: str, turn_content: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Process a player's turn and determine next game state.

        Args:
            session_id: Session identifier
            player_email: Player's email address
            turn_content: Player's turn data

        Returns:
            Game state update information
        """
        try:
            # Get current session
            session = self.storage.get_session(session_id)
            if not session:
                raise ValueError(f"Session {session_id} not found")

            # Validate player is in session
            if player_email not in session.get("players", []):
                raise ValueError(f"Player {player_email} not in session {session_id}")

            # Get current turn information
            current_turn = session.get("turn_count", 0) + 1

            # Get state machines
            session_machine = self.state_manager.get_session_machine(session_id)
            turn_machine = self.state_manager.get_turn_machine(session_id, current_turn)

            # Save the player's turn
            self.storage.save_turn(session_id, current_turn, player_email, turn_content)

            # Update turn machine with player response
            turn_machine.add_player_response(player_email)

            # Check turn completion and update states
            turn_complete = turn_machine.can_start_processing()

            if turn_complete:
                # Transition turn to processing then complete
                if turn_machine.is_waiting_for_players():
                    turn_machine.start_processing()
                turn_machine.complete()

                # Advance session to next turn
                next_state = self._advance_turn_with_state_machine(
                    session_id, session, current_turn
                )
            else:
                # Update waiting state
                next_state = self._update_waiting_state_with_state_machine(
                    session_id, session, current_turn, turn_machine
                )

            return {
                "turn_complete": turn_complete,
                "current_turn": current_turn,
                "next_state": next_state,
                "waiting_for": next_state.get("waiting_for", []),
                "can_proceed": turn_complete,
                "session_state": session_machine.get_current_state(),
                "turn_state": turn_machine.get_current_state(),
            }

        except Exception as e:
            logger.error(
                f"Error processing turn for {player_email} in {session_id}: {e}"
            )
            raise

    def _check_turn_completion(
        self, session_id: str, turn_number: int, session: dict[str, Any]
    ) -> bool:
        """Check if all required players have submitted for the current turn."""
        try:
            # Get all turns for this turn number
            all_turns = self.storage.get_session_turns(session_id)
            current_turn_submissions = [
                turn for turn in all_turns if turn.get("turn_number") == turn_number
            ]

            # Get expected players for this turn
            expected_players = set(session.get("players", []))
            submitted_players = {
                turn.get("player_email") for turn in current_turn_submissions
            }

            game_type = session.get("game_type")

            # Special logic for different game types
            if game_type == "intimacy":
                # Couples therapy: both partners must respond
                return len(submitted_players) >= 2 and submitted_players.issubset(
                    expected_players
                )

            elif game_type == "dungeon":
                # Adventure game: flexible based on session settings
                min_required = session.get("min_players_per_turn", 1)
                return len(submitted_players) >= min_required

            else:
                # Default: all players must respond
                return submitted_players == expected_players

        except Exception as e:
            logger.error(f"Error checking turn completion: {e}")
            return False

    def _advance_turn_with_state_machine(
        self, session_id: str, session: dict[str, Any], completed_turn: int
    ) -> dict[str, Any]:
        """Advance the game to the next turn using state machines."""
        try:
            next_turn = completed_turn + 1

            # Get session state machine
            session_machine = self.state_manager.get_session_machine(session_id)

            # Ensure session is active
            if not session_machine.is_active():
                if session_machine.state == SessionState.WAITING_FOR_PLAYERS.value:
                    session_machine.activate()
                elif session_machine.state == SessionState.PAUSED.value:
                    session_machine.resume()

            # Update session state in storage
            updates = {
                "turn_count": completed_turn,
                "status": session_machine.get_current_state(),
                "last_turn_completed": timestamps.now(),
                "next_turn": next_turn,
                "waiting_for": list(session.get("players", [])),  # Reset waiting list
            }

            self.storage.update_session(session_id, updates)

            # Initialize next turn state machine
            next_turn_machine = self.state_manager.get_turn_machine(
                session_id, next_turn
            )
            next_turn_machine.set_waiting_players(session.get("players", []))

            # Clean up old turn machines
            self.state_manager.cleanup_completed_turns(session_id)

            logger.info(f"Advanced session {session_id} to turn {next_turn}")

            return {
                "status": session_machine.get_current_state(),
                "current_turn": completed_turn,
                "next_turn": next_turn,
                "waiting_for": [],
                "turn_advancement": True,
            }

        except Exception as e:
            logger.error(f"Error advancing turn: {e}")
            raise

    def _advance_turn(
        self, session_id: str, session: dict[str, Any], completed_turn: int
    ) -> dict[str, Any]:
        """Legacy method - redirect to state machine version."""
        return self._advance_turn_with_state_machine(
            session_id, session, completed_turn
        )

    def _update_waiting_state_with_state_machine(
        self, session_id: str, session: dict[str, Any], current_turn: int, turn_machine
    ) -> dict[str, Any]:
        """Update session while waiting for remaining players using state machines."""
        try:
            # Get session state machine
            session_machine = self.state_manager.get_session_machine(session_id)

            # Get waiting players from turn machine
            waiting_for = turn_machine.get_waiting_players()

            # Update session to waiting state if not already
            if session_machine.is_active():
                # We don't transition away from active when waiting for more players in a turn
                # This is different from waiting for players to join initially
                current_status = SessionState.ACTIVE.value
            else:
                current_status = session_machine.get_current_state()

            # Update session state in storage
            updates = {
                "status": current_status,
                "waiting_for": waiting_for,
                "last_partial_turn": timestamps.now(),
            }

            self.storage.update_session(session_id, updates)

            logger.info(f"Session {session_id} waiting for players: {waiting_for}")

            return {
                "status": current_status,
                "current_turn": current_turn,
                "waiting_for": waiting_for,
                "turn_advancement": False,
            }

        except Exception as e:
            logger.error(f"Error updating waiting state: {e}")
            raise

    def _update_waiting_state(
        self, session_id: str, session: dict[str, Any], current_turn: int
    ) -> dict[str, Any]:
        """Legacy method - redirect to state machine version."""
        turn_machine = self.state_manager.get_turn_machine(session_id, current_turn)
        return self._update_waiting_state_with_state_machine(
            session_id, session, current_turn, turn_machine
        )

    def check_turn_timeouts(self) -> list[dict[str, Any]]:
        """Check for sessions with timed-out turns and return list for processing."""
        try:
            # Get all active sessions
            active_sessions = self.storage.get_active_sessions()
            timed_out_sessions = []

            current_time = datetime.now(UTC)

            for session in active_sessions:
                game_type = session.get("game_type")
                timeout_hours = self.turn_timeout.get(game_type, 24)

                # Check different timeout conditions
                last_activity = session.get("last_partial_turn") or session.get(
                    "updated_at"
                )
                if last_activity:
                    last_activity_time = datetime.fromisoformat(
                        last_activity.replace("Z", "+00:00")
                    )
                    time_since_activity = current_time - last_activity_time

                    if time_since_activity > timedelta(hours=timeout_hours):
                        timed_out_sessions.append(
                            {
                                "session_id": session["session_id"],
                                "game_type": game_type,
                                "waiting_for": session.get("waiting_for", []),
                                "turn_count": session.get("turn_count", 0),
                                "timeout_hours": timeout_hours,
                                "last_activity": last_activity,
                            }
                        )

            return timed_out_sessions

        except Exception as e:
            logger.error(f"Error checking turn timeouts: {e}")
            return []

    def handle_turn_timeout(self, session_id: str) -> dict[str, Any]:
        """Handle a session that has timed out."""
        try:
            session = self.storage.get_session(session_id)
            if not session:
                return {"error": "Session not found"}

            # Get session state machine
            session_machine = self.state_manager.get_session_machine(session_id)
            current_turn = session.get("turn_count", 0) + 1
            turn_machine = self.state_manager.get_turn_machine(session_id, current_turn)

            # Timeout the current turn
            turn_machine.timeout()

            game_type = session.get("game_type")

            # Different timeout handling for different game types
            if game_type == "intimacy":
                # Therapy sessions: pause and send reminder
                return self._pause_therapy_session_with_state_machine(
                    session_id, session, session_machine
                )

            elif game_type == "dungeon":
                # Adventure games: skip absent players or pause
                return self._handle_adventure_timeout_with_state_machine(
                    session_id, session, session_machine, turn_machine
                )

            else:
                # Default: pause session
                return self._pause_session_with_state_machine(
                    session_id, session, session_machine
                )

        except Exception as e:
            logger.error(f"Error handling timeout for {session_id}: {e}")
            return {"error": str(e)}

    def _pause_therapy_session_with_state_machine(
        self, session_id: str, session: dict[str, Any], session_machine
    ) -> dict[str, Any]:
        """Pause a therapy session due to timeout using state machines."""
        session_machine.pause()

        updates = {
            "status": session_machine.get_current_state(),
            "pause_reason": "turn_timeout",
            "paused_at": timestamps.now(),
        }

        self.storage.update_session(session_id, updates)

        return {
            "action": "paused",
            "reason": "turn_timeout",
            "session_id": session_id,
            "reminder_needed": True,
        }

    def _pause_therapy_session(
        self, session_id: str, session: dict[str, Any]
    ) -> dict[str, Any]:
        """Legacy method - redirect to state machine version."""
        session_machine = self.state_manager.get_session_machine(session_id)
        return self._pause_therapy_session_with_state_machine(
            session_id, session, session_machine
        )

    def _handle_adventure_timeout_with_state_machine(
        self, session_id: str, session: dict[str, Any], session_machine, turn_machine
    ) -> dict[str, Any]:
        """Handle adventure game timeout - more flexible than therapy."""
        waiting_for = turn_machine.get_waiting_players()
        all_players = session.get("players", [])

        # If more than half the players have responded, continue without the others
        responded_count = len(all_players) - len(waiting_for)
        if responded_count >= len(all_players) / 2:
            # Complete the turn despite timeout and continue
            if turn_machine.can_complete_after_timeout():
                turn_machine.complete()
                return self._advance_turn_with_state_machine(
                    session_id, session, session.get("turn_count", 0)
                )
            else:
                return self._pause_session_with_state_machine(
                    session_id, session, session_machine
                )
        else:
            # Not enough players responded - pause
            return self._pause_session_with_state_machine(
                session_id, session, session_machine
            )

    def _handle_adventure_timeout(
        self, session_id: str, session: dict[str, Any]
    ) -> dict[str, Any]:
        """Legacy method - redirect to state machine version."""
        session_machine = self.state_manager.get_session_machine(session_id)
        current_turn = session.get("turn_count", 0) + 1
        turn_machine = self.state_manager.get_turn_machine(session_id, current_turn)
        return self._handle_adventure_timeout_with_state_machine(
            session_id, session, session_machine, turn_machine
        )

    def _pause_session_with_state_machine(
        self, session_id: str, session: dict[str, Any], session_machine
    ) -> dict[str, Any]:
        """Generic session pause using state machines."""
        session_machine.pause()

        updates = {
            "status": session_machine.get_current_state(),
            "pause_reason": "turn_timeout",
            "paused_at": timestamps.now(),
        }

        self.storage.update_session(session_id, updates)

        return {"action": "paused", "reason": "turn_timeout", "session_id": session_id}

    def _pause_session(
        self, session_id: str, session: dict[str, Any]
    ) -> dict[str, Any]:
        """Legacy method - redirect to state machine version."""
        session_machine = self.state_manager.get_session_machine(session_id)
        return self._pause_session_with_state_machine(
            session_id, session, session_machine
        )

    def resume_session(self, session_id: str, resuming_player: str) -> dict[str, Any]:
        """Resume a paused session."""
        try:
            session = self.storage.get_session(session_id)
            if not session:
                return {"error": "Session not found"}

            # Get session state machine
            session_machine = self.state_manager.get_session_machine(session_id)

            if session_machine.get_current_state() != SessionState.PAUSED.value:
                return {"error": "Session is not paused"}

            # Resume via state machine
            if not session_machine.can_resume():
                return {"error": "Session cannot be resumed"}

            session_machine.resume()

            # Update storage
            updates = {
                "status": session_machine.get_current_state(),
                "resumed_at": timestamps.now(),
                "resumed_by": resuming_player,
            }

            self.storage.update_session(session_id, updates)

            logger.info(f"Session {session_id} resumed by {resuming_player}")

            return {
                "action": "resumed",
                "session_id": session_id,
                "resumed_by": resuming_player,
                "status": session_machine.get_current_state(),
            }

        except Exception as e:
            logger.error(f"Error resuming session {session_id}: {e}")
            return {"error": str(e)}

    def add_player_to_session(
        self, session_id: str, player_email: str
    ) -> dict[str, Any]:
        """Add a new player to an existing session."""
        try:
            session = self.storage.get_session(session_id)
            if not session:
                return {"error": "Session not found"}

            # Get session state machine
            session_machine = self.state_manager.get_session_machine(session_id)

            game_type = session.get("game_type")
            current_players = session.get("players", [])
            max_allowed = self.max_players.get(game_type, 4)

            # Check if player already in session
            if player_email in current_players:
                return {"error": "Player already in session"}

            # Check if session is full
            if len(current_players) >= max_allowed:
                return {"error": f"Session is full (max {max_allowed} players)"}

            # Add player to session
            self.storage.add_player_to_session(session_id, player_email)

            # Check if we now have minimum players to start
            min_required = self.min_players.get(game_type, 1)
            if len(current_players) + 1 >= min_required:
                # Can start the session - transition from waiting to active
                if session_machine.can_activate():
                    session_machine.activate()

                updates = {
                    "status": session_machine.get_current_state(),
                    "started_at": timestamps.now(),
                }
                self.storage.update_session(session_id, updates)

                return {
                    "action": "player_added_session_started",
                    "player_email": player_email,
                    "session_id": session_id,
                    "can_start": True,
                    "session_state": session_machine.get_current_state(),
                }
            else:
                # Still waiting for more players - transition to waiting state if needed
                if session_machine.state == SessionState.INITIALIZING.value:
                    session_machine.start_waiting()

                return {
                    "action": "player_added_waiting",
                    "player_email": player_email,
                    "session_id": session_id,
                    "can_start": False,
                    "players_needed": min_required - len(current_players) - 1,
                    "session_state": session_machine.get_current_state(),
                }

        except Exception as e:
            logger.error(
                f"Error adding player {player_email} to session {session_id}: {e}"
            )
            return {"error": str(e)}

    def get_turn_summary(
        self, session_id: str, turn_number: int = None
    ) -> dict[str, Any]:
        """Get a summary of a specific turn or the latest turn."""
        try:
            if turn_number is None:
                # Get the latest turn
                latest_turn = self.storage.get_latest_turn(session_id)
                if not latest_turn:
                    return {"error": "No turns found"}
                turn_number = latest_turn.get("turn_number")

            # Get all submissions for this turn
            all_turns = self.storage.get_session_turns(session_id)
            turn_submissions = [
                turn for turn in all_turns if turn.get("turn_number") == turn_number
            ]

            if not turn_submissions:
                return {"error": f"Turn {turn_number} not found"}

            # Organize by player
            player_submissions = {}
            for turn in turn_submissions:
                player_email = turn.get("player_email")
                player_submissions[player_email] = turn

            return {
                "turn_number": turn_number,
                "submissions": player_submissions,
                "submission_count": len(turn_submissions),
                "timestamp": (
                    turn_submissions[0].get("timestamp") if turn_submissions else None
                ),
            }

        except Exception as e:
            logger.error(f"Error getting turn summary: {e}")
            return {"error": str(e)}


# Convenience functions for Lambda usage
def get_game_engine() -> GameEngine:
    """Get a configured GameEngine instance."""
    return GameEngine()


def process_turn(
    session_id: str, player_email: str, turn_content: dict[str, Any]
) -> dict[str, Any]:
    """
    Convenience function to process a turn without creating engine instance.

    Args:
        session_id: Session identifier
        player_email: Player's email address
        turn_content: Player's turn data

    Returns:
        Game state update information
    """
    engine = get_game_engine()
    return engine.process_player_turn(session_id, player_email, turn_content)
