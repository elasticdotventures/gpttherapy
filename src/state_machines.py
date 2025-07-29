"""
State machine implementations for GPT Therapy sessions.
Uses the transitions library for clean state management.
"""

import logging
from enum import Enum
from typing import Any

from datetime_utils import timestamps
from transitions import Machine

try:
    from storage import StorageManager
except ImportError:
    from storage import StorageManager

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session state enumeration."""

    INITIALIZING = "initializing"
    WAITING_FOR_PLAYERS = "waiting_for_players"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    ARCHIVED = "archived"


class TurnState(Enum):
    """Turn state enumeration."""

    WAITING_FOR_PLAYERS = "waiting_for_players"
    PROCESSING = "processing"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"


class SessionStateMachine:
    """
    State machine for managing session lifecycle.
    Handles transitions between session states with proper validation.
    """

    def __init__(
        self, session_id: str, initial_state: str = None, storage: StorageManager = None
    ):
        self.session_id = session_id
        self.storage = storage or StorageManager()
        self.metadata = {}

        # Define states
        self.states = [state.value for state in SessionState]

        # Define state transitions
        self.transitions = [
            # From INITIALIZING
            {
                "trigger": "start_waiting",
                "source": SessionState.INITIALIZING.value,
                "dest": SessionState.WAITING_FOR_PLAYERS.value,
                "before": "on_start_waiting",
                "after": "save_state",
            },
            {
                "trigger": "activate",
                "source": SessionState.INITIALIZING.value,
                "dest": SessionState.ACTIVE.value,
                "conditions": "can_activate",
                "before": "on_activate",
                "after": "save_state",
            },
            # From WAITING_FOR_PLAYERS
            {
                "trigger": "activate",
                "source": SessionState.WAITING_FOR_PLAYERS.value,
                "dest": SessionState.ACTIVE.value,
                "conditions": "can_activate",
                "before": "on_activate",
                "after": "save_state",
            },
            {
                "trigger": "timeout",
                "source": SessionState.WAITING_FOR_PLAYERS.value,
                "dest": SessionState.TIMED_OUT.value,
                "before": "on_timeout",
                "after": "save_state",
            },
            # From ACTIVE
            {
                "trigger": "pause",
                "source": SessionState.ACTIVE.value,
                "dest": SessionState.PAUSED.value,
                "before": "on_pause",
                "after": "save_state",
            },
            {
                "trigger": "complete",
                "source": SessionState.ACTIVE.value,
                "dest": SessionState.COMPLETED.value,
                "before": "on_complete",
                "after": "save_state",
            },
            {
                "trigger": "timeout",
                "source": SessionState.ACTIVE.value,
                "dest": SessionState.TIMED_OUT.value,
                "before": "on_timeout",
                "after": "save_state",
            },
            # From PAUSED
            {
                "trigger": "resume",
                "source": SessionState.PAUSED.value,
                "dest": SessionState.ACTIVE.value,
                "conditions": "can_resume",
                "before": "on_resume",
                "after": "save_state",
            },
            {
                "trigger": "complete",
                "source": SessionState.PAUSED.value,
                "dest": SessionState.COMPLETED.value,
                "before": "on_complete",
                "after": "save_state",
            },
            {
                "trigger": "timeout",
                "source": SessionState.PAUSED.value,
                "dest": SessionState.TIMED_OUT.value,
                "before": "on_timeout",
                "after": "save_state",
            },
            # From COMPLETED or TIMED_OUT
            {
                "trigger": "archive",
                "source": [SessionState.COMPLETED.value, SessionState.TIMED_OUT.value],
                "dest": SessionState.ARCHIVED.value,
                "before": "on_archive",
                "after": "save_state",
            },
        ]

        # Initialize the state machine
        self.machine = Machine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=initial_state or SessionState.INITIALIZING.value,
            auto_transitions=False,
            ignore_invalid_triggers=True,
        )

        # Load state from storage if it exists
        self.load_state()

    def can_activate(self) -> bool:
        """Check if session can be activated."""
        session_data = self.storage.get_session(self.session_id)
        if not session_data:
            return False

        required_players = session_data.get("min_players", 1)
        current_players = len(session_data.get("players", []))

        return current_players >= required_players

    def can_resume(self) -> bool:
        """Check if session can be resumed."""
        # Check if there are any active players
        session_data = self.storage.get_session(self.session_id)
        if not session_data:
            return False

        return len(session_data.get("players", [])) > 0

    def on_start_waiting(self):
        """Called when transitioning to waiting for players."""
        logger.info(f"Session {self.session_id} started waiting for players")
        self.metadata["waiting_started_at"] = timestamps.now()

    def on_activate(self):
        """Called when session becomes active."""
        logger.info(f"Session {self.session_id} activated")
        self.metadata["activated_at"] = timestamps.now()

        # Update session status in storage
        self.storage.update_session(
            self.session_id, {"status": SessionState.ACTIVE.value}
        )

    def on_pause(self):
        """Called when session is paused."""
        logger.info(f"Session {self.session_id} paused")
        self.metadata["paused_at"] = timestamps.now()

        # Update session status in storage
        self.storage.update_session(
            self.session_id, {"status": SessionState.PAUSED.value}
        )

    def on_resume(self):
        """Called when session is resumed."""
        logger.info(f"Session {self.session_id} resumed")
        self.metadata["resumed_at"] = timestamps.now()

        # Update session status in storage
        self.storage.update_session(
            self.session_id, {"status": SessionState.ACTIVE.value}
        )

    def on_complete(self):
        """Called when session is completed."""
        logger.info(f"Session {self.session_id} completed")
        self.metadata["completed_at"] = timestamps.now()

        # Update session status in storage
        self.storage.update_session(
            self.session_id,
            {
                "status": SessionState.COMPLETED.value,
                "completed_at": self.metadata["completed_at"],
            },
        )

    def on_timeout(self):
        """Called when session times out."""
        logger.info(f"Session {self.session_id} timed out")
        self.metadata["timed_out_at"] = timestamps.now()

        # Update session status in storage
        self.storage.update_session(
            self.session_id,
            {
                "status": SessionState.TIMED_OUT.value,
                "timed_out_at": self.metadata["timed_out_at"],
            },
        )

    def on_archive(self):
        """Called when session is archived."""
        logger.info(f"Session {self.session_id} archived")
        self.metadata["archived_at"] = timestamps.now()

        # Update session status in storage
        self.storage.update_session(
            self.session_id,
            {
                "status": SessionState.ARCHIVED.value,
                "archived_at": self.metadata["archived_at"],
            },
        )

    def save_state(self):
        """Save current state to storage."""
        try:
            state_data = {
                "current_state": self.state,
                "metadata": self.metadata,
                "updated_at": timestamps.now(),
            }

            # Save state machine data
            self.storage.save_game_state(
                self.session_id,
                {
                    "key": f"sessions/{self.session_id}/state_machine.json",
                    "state_machine": state_data,
                },
            )

        except Exception as e:
            logger.error(f"Failed to save state for session {self.session_id}: {e}")

    def load_state(self):
        """Load state from storage."""
        try:
            state_container = self.storage.load_game_state(self.session_id)

            if not state_container:
                return

            # Look for state machine data
            if "state_machine" in state_container:
                state_data = state_container["state_machine"]

                # Set state directly (bypass transitions for loading)
                self.state = state_data.get(
                    "current_state", SessionState.INITIALIZING.value
                )
                self.metadata = state_data.get("metadata", {})

                logger.info(f"Loaded state {self.state} for session {self.session_id}")

        except Exception as e:
            logger.error(f"Failed to load state for session {self.session_id}: {e}")

    def get_current_state(self) -> str:
        """Get current state as string."""
        return self.state

    def is_active(self) -> bool:
        """Check if session is currently active."""
        return self.state == SessionState.ACTIVE.value

    def is_completed(self) -> bool:
        """Check if session is completed."""
        return self.state in [SessionState.COMPLETED.value, SessionState.ARCHIVED.value]

    def is_waiting(self) -> bool:
        """Check if session is waiting for players."""
        return self.state == SessionState.WAITING_FOR_PLAYERS.value


class TurnStateMachine:
    """
    State machine for managing individual turn lifecycle.
    Handles turn progression and player coordination.
    """

    def __init__(
        self,
        session_id: str,
        turn_number: int,
        initial_state: str = None,
        storage: StorageManager = None,
    ):
        self.session_id = session_id
        self.turn_number = turn_number
        self.storage = storage or StorageManager()
        self.metadata = {
            "players_responded": [],
            "players_waiting": [],
            "started_at": timestamps.now(),
        }

        # Define states
        self.states = [state.value for state in TurnState]

        # Define state transitions
        self.transitions = [
            # From WAITING_FOR_PLAYERS
            {
                "trigger": "start_processing",
                "source": TurnState.WAITING_FOR_PLAYERS.value,
                "dest": TurnState.PROCESSING.value,
                "conditions": "can_start_processing",
                "before": "on_start_processing",
                "after": "save_state",
            },
            {
                "trigger": "timeout",
                "source": TurnState.WAITING_FOR_PLAYERS.value,
                "dest": TurnState.TIMED_OUT.value,
                "before": "on_timeout",
                "after": "save_state",
            },
            # From PROCESSING
            {
                "trigger": "complete",
                "source": TurnState.PROCESSING.value,
                "dest": TurnState.COMPLETED.value,
                "before": "on_complete",
                "after": "save_state",
            },
            {
                "trigger": "timeout",
                "source": TurnState.PROCESSING.value,
                "dest": TurnState.TIMED_OUT.value,
                "before": "on_timeout",
                "after": "save_state",
            },
            # From TIMED_OUT
            {
                "trigger": "complete",
                "source": TurnState.TIMED_OUT.value,
                "dest": TurnState.COMPLETED.value,
                "conditions": "can_complete_after_timeout",
                "before": "on_complete",
                "after": "save_state",
            },
        ]

        # Initialize the state machine
        self.machine = Machine(
            model=self,
            states=self.states,
            transitions=self.transitions,
            initial=initial_state or TurnState.WAITING_FOR_PLAYERS.value,
            auto_transitions=False,
            ignore_invalid_triggers=True,
        )

    def can_start_processing(self) -> bool:
        """Check if turn can start processing (all required players responded)."""
        session_data = self.storage.get_session(self.session_id)
        if not session_data:
            return False

        required_players = set(session_data.get("players", []))
        responded_players = set(self.metadata.get("players_responded", []))

        return required_players.issubset(responded_players)

    def can_complete_after_timeout(self) -> bool:
        """Check if turn can be completed even after timeout."""
        # In some games, turns can be completed with partial responses
        session_data = self.storage.get_session(self.session_id)
        if not session_data:
            return False

        game_type = session_data.get("game_type", "dungeon")
        responded_players = len(self.metadata.get("players_responded", []))

        # For dungeon games, allow completion with at least one response
        if game_type == "dungeon" and responded_players >= 1:
            return True

        # For therapy sessions, require both players
        if game_type == "intimacy":
            total_players = len(session_data.get("players", []))
            return responded_players >= total_players

        return False

    def add_player_response(self, player_email: str):
        """Record that a player has responded."""
        if player_email not in self.metadata["players_responded"]:
            self.metadata["players_responded"].append(player_email)

            # Remove from waiting list if present
            if player_email in self.metadata["players_waiting"]:
                self.metadata["players_waiting"].remove(player_email)

            logger.info(f"Player {player_email} responded to turn {self.turn_number}")

            # Check if we can start processing
            if (
                self.can_start_processing()
                and self.state == TurnState.WAITING_FOR_PLAYERS.value
            ):
                self.start_processing()

    def set_waiting_players(self, players: list[str]):
        """Set the list of players we're waiting for."""
        self.metadata["players_waiting"] = [
            player
            for player in players
            if player not in self.metadata["players_responded"]
        ]

    def on_start_processing(self):
        """Called when turn starts processing."""
        logger.info(
            f"Turn {self.turn_number} for session {self.session_id} started processing"
        )
        self.metadata["processing_started_at"] = timestamps.now()

    def on_complete(self):
        """Called when turn is completed."""
        logger.info(f"Turn {self.turn_number} for session {self.session_id} completed")
        self.metadata["completed_at"] = timestamps.now()

    def on_timeout(self):
        """Called when turn times out."""
        logger.info(f"Turn {self.turn_number} for session {self.session_id} timed out")
        self.metadata["timed_out_at"] = timestamps.now()

    def save_state(self):
        """Save current turn state to storage."""
        try:
            state_data = {
                "turn_number": self.turn_number,
                "current_state": self.state,
                "metadata": self.metadata,
                "updated_at": timestamps.now(),
            }

            # Save to turns table
            self.storage.save_turn(
                self.session_id, self.turn_number, "system", state_data
            )

        except Exception as e:
            logger.error(f"Failed to save turn state: {e}")

    def get_current_state(self) -> str:
        """Get current state as string."""
        return self.state

    def is_waiting_for_players(self) -> bool:
        """Check if turn is waiting for player responses."""
        return self.state == TurnState.WAITING_FOR_PLAYERS.value

    def is_completed(self) -> bool:
        """Check if turn is completed."""
        return self.state == TurnState.COMPLETED.value

    def is_timed_out(self) -> bool:
        """Check if turn has timed out."""
        return self.state == TurnState.TIMED_OUT.value

    def get_waiting_players(self) -> list[str]:
        """Get list of players still waiting to respond."""
        return self.metadata.get("players_waiting", [])

    def get_responded_players(self) -> list[str]:
        """Get list of players who have responded."""
        return self.metadata.get("players_responded", [])


class StateMachineManager:
    """
    Manager for creating and managing state machines for sessions and turns.
    """

    def __init__(self, storage: StorageManager = None):
        self.storage = storage or StorageManager()
        self._session_machines: dict[str, SessionStateMachine] = {}
        self._turn_machines: dict[str, TurnStateMachine] = {}

    def get_session_machine(self, session_id: str) -> SessionStateMachine:
        """Get or create a session state machine."""
        if session_id not in self._session_machines:
            self._session_machines[session_id] = SessionStateMachine(
                session_id=session_id, storage=self.storage
            )

        return self._session_machines[session_id]

    def get_turn_machine(self, session_id: str, turn_number: int) -> TurnStateMachine:
        """Get or create a turn state machine."""
        machine_key = f"{session_id}_{turn_number}"

        if machine_key not in self._turn_machines:
            self._turn_machines[machine_key] = TurnStateMachine(
                session_id=session_id, turn_number=turn_number, storage=self.storage
            )

        return self._turn_machines[machine_key]

    def cleanup_completed_turns(self, session_id: str, keep_recent: int = 3):
        """Clean up state machines for completed turns to prevent memory leaks."""
        to_remove = []

        for key, machine in self._turn_machines.items():
            if (
                key.startswith(f"{session_id}_")
                and machine.is_completed()
                and machine.turn_number
                < (self.get_current_turn(session_id) - keep_recent)
            ):
                to_remove.append(key)

        for key in to_remove:
            del self._turn_machines[key]
            logger.debug(f"Cleaned up turn machine: {key}")

    def get_current_turn(self, session_id: str) -> int:
        """Get current turn number for a session."""
        session_data = self.storage.get_session(session_id)
        return session_data.get("turn_count", 0) if session_data else 0

    def get_session_state_summary(self, session_id: str) -> dict[str, Any]:
        """Get a summary of session and turn states."""
        session_machine = self.get_session_machine(session_id)
        current_turn = self.get_current_turn(session_id)

        summary = {
            "session_id": session_id,
            "session_state": session_machine.get_current_state(),
            "session_active": session_machine.is_active(),
            "session_completed": session_machine.is_completed(),
            "current_turn": current_turn,
            "turn_states": {},
        }

        # Include states for recent turns
        for turn_num in range(max(1, current_turn - 2), current_turn + 1):
            machine_key = f"{session_id}_{turn_num}"
            if machine_key in self._turn_machines:
                turn_machine = self._turn_machines[machine_key]
                summary["turn_states"][turn_num] = {
                    "state": turn_machine.get_current_state(),
                    "waiting_players": turn_machine.get_waiting_players(),
                    "responded_players": turn_machine.get_responded_players(),
                }

        return summary


# Global state machine manager instance
state_machine_manager = StateMachineManager()


def get_state_machine_manager() -> StateMachineManager:
    """Get the global state machine manager instance."""
    return state_machine_manager
