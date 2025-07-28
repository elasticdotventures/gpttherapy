"""
Tests for state machine implementations.
"""

import os
import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timezone

# Set test environment
os.environ.update({
    'AWS_REGION': 'us-east-1',
    'IS_TEST_ENV': 'true',
    'SESSIONS_TABLE_NAME': 'test-sessions',
    'TURNS_TABLE_NAME': 'test-turns',
    'PLAYERS_TABLE_NAME': 'test-players',
    'GAMEDATA_S3_BUCKET': 'test-bucket'
})

from src.state_machines import (
    SessionState, TurnState, SessionStateMachine, TurnStateMachine,
    StateMachineManager, get_state_machine_manager
)


class TestSessionStateMachine:
    """Test SessionStateMachine functionality."""
    
    @pytest.fixture
    def mock_storage(self):
        """Mock storage manager."""
        storage = Mock()
        storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com', 'player2@example.com'],
            'min_players': 2
        }
        storage.load_game_state.return_value = None
        storage.save_game_state.return_value = True
        storage.update_session.return_value = True
        return storage
    
    @pytest.fixture
    def session_machine(self, mock_storage):
        """Create SessionStateMachine instance."""
        return SessionStateMachine('test-123', storage=mock_storage)
    
    def test_initial_state(self, session_machine):
        """Test initial state is INITIALIZING."""
        assert session_machine.get_current_state() == SessionState.INITIALIZING.value
        assert not session_machine.is_active()
        assert not session_machine.is_completed()
    
    def test_start_waiting_transition(self, session_machine):
        """Test transition from INITIALIZING to WAITING_FOR_PLAYERS."""
        session_machine.start_waiting()
        
        assert session_machine.get_current_state() == SessionState.WAITING_FOR_PLAYERS.value
        assert session_machine.is_waiting()
        assert 'waiting_started_at' in session_machine.metadata
    
    def test_activate_from_initializing(self, session_machine):
        """Test activation from INITIALIZING state."""
        # Mock the can_activate condition
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
            
            assert session_machine.get_current_state() == SessionState.ACTIVE.value
            assert session_machine.is_active()
            assert 'activated_at' in session_machine.metadata
    
    def test_activate_from_waiting(self, session_machine):
        """Test activation from WAITING_FOR_PLAYERS state."""
        session_machine.start_waiting()
        
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
            
            assert session_machine.get_current_state() == SessionState.ACTIVE.value
            assert session_machine.is_active()
    
    def test_pause_session(self, session_machine):
        """Test pausing an active session."""
        # First activate the session
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
        
        # Then pause it
        session_machine.pause()
        
        assert session_machine.get_current_state() == SessionState.PAUSED.value
        assert 'paused_at' in session_machine.metadata
    
    def test_resume_session(self, session_machine):
        """Test resuming a paused session."""
        # First activate, then pause
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
        session_machine.pause()
        
        # Now resume
        with patch.object(session_machine, 'can_resume', return_value=True):
            session_machine.resume()
            
            assert session_machine.get_current_state() == SessionState.ACTIVE.value
            assert session_machine.is_active()
            assert 'resumed_at' in session_machine.metadata
    
    def test_complete_session(self, session_machine):
        """Test completing a session."""
        # First activate
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
        
        # Then complete
        session_machine.complete()
        
        assert session_machine.get_current_state() == SessionState.COMPLETED.value
        assert session_machine.is_completed()
        assert 'completed_at' in session_machine.metadata
    
    def test_timeout_session(self, session_machine):
        """Test session timeout."""
        # First activate
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
        
        # Then timeout
        session_machine.timeout()
        
        assert session_machine.get_current_state() == SessionState.TIMED_OUT.value
        assert 'timed_out_at' in session_machine.metadata
    
    def test_archive_session(self, session_machine):
        """Test archiving a completed session."""
        # First activate and complete
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
        session_machine.complete()
        
        # Then archive
        session_machine.archive()
        
        assert session_machine.get_current_state() == SessionState.ARCHIVED.value
        assert 'archived_at' in session_machine.metadata
    
    def test_can_activate_condition(self, session_machine, mock_storage):
        """Test can_activate condition logic."""
        # Test with sufficient players
        mock_storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com', 'player2@example.com'],
            'min_players': 2
        }
        assert session_machine.can_activate() is True
        
        # Test with insufficient players
        mock_storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com'],
            'min_players': 2
        }
        assert session_machine.can_activate() is False
    
    def test_save_and_load_state(self, session_machine, mock_storage):
        """Test state persistence."""
        # Activate session to change state
        with patch.object(session_machine, 'can_activate', return_value=True):
            session_machine.activate()
        
        # Verify save was called
        mock_storage.save_game_state.assert_called()
        save_call = mock_storage.save_game_state.call_args[0]
        state_data = save_call[1]['state_machine']
        
        assert state_data['current_state'] == SessionState.ACTIVE.value
        assert 'activated_at' in state_data['metadata']


class TestTurnStateMachine:
    """Test TurnStateMachine functionality."""
    
    @pytest.fixture
    def mock_storage(self):
        """Mock storage manager."""
        storage = Mock()
        storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com', 'player2@example.com'],
            'game_type': 'dungeon'
        }
        storage.save_turn.return_value = True
        return storage
    
    @pytest.fixture
    def turn_machine(self, mock_storage):
        """Create TurnStateMachine instance."""
        return TurnStateMachine('test-123', 1, storage=mock_storage)
    
    def test_initial_state(self, turn_machine):
        """Test initial state is WAITING_FOR_PLAYERS."""
        assert turn_machine.get_current_state() == TurnState.WAITING_FOR_PLAYERS.value
        assert turn_machine.is_waiting_for_players()
        assert not turn_machine.is_completed()
    
    def test_add_player_response(self, turn_machine):
        """Test adding player responses."""
        # Set waiting players
        turn_machine.set_waiting_players(['player1@example.com', 'player2@example.com'])
        
        # Add first response
        turn_machine.add_player_response('player1@example.com')
        
        assert 'player1@example.com' in turn_machine.get_responded_players()
        assert 'player1@example.com' not in turn_machine.get_waiting_players()
        assert turn_machine.is_waiting_for_players()  # Still waiting for player2
    
    def test_turn_completion(self, turn_machine):
        """Test turn completion when all players respond."""
        # Set waiting players
        turn_machine.set_waiting_players(['player1@example.com', 'player2@example.com'])
        
        # Add both responses
        turn_machine.add_player_response('player1@example.com')
        turn_machine.add_player_response('player2@example.com')
        
        # Turn should automatically transition to processing
        assert turn_machine.get_current_state() == TurnState.PROCESSING.value
        assert len(turn_machine.get_responded_players()) == 2
        assert len(turn_machine.get_waiting_players()) == 0
    
    def test_complete_turn(self, turn_machine):
        """Test completing a turn."""
        # First get to processing state
        turn_machine.set_waiting_players(['player1@example.com', 'player2@example.com'])
        turn_machine.add_player_response('player1@example.com')
        turn_machine.add_player_response('player2@example.com')
        
        # Now complete the turn
        turn_machine.complete()
        
        assert turn_machine.get_current_state() == TurnState.COMPLETED.value
        assert turn_machine.is_completed()
        assert 'completed_at' in turn_machine.metadata
    
    def test_turn_timeout(self, turn_machine):
        """Test turn timeout."""
        turn_machine.timeout()
        
        assert turn_machine.get_current_state() == TurnState.TIMED_OUT.value
        assert turn_machine.is_timed_out()
        assert 'timed_out_at' in turn_machine.metadata
    
    def test_complete_after_timeout(self, turn_machine, mock_storage):
        """Test completing turn after timeout."""
        # Set up dungeon game with one response
        turn_machine.set_waiting_players(['player1@example.com', 'player2@example.com'])
        turn_machine.add_player_response('player1@example.com')
        
        # Timeout the turn
        turn_machine.timeout()
        assert turn_machine.is_timed_out()
        
        # Should be able to complete with partial responses for dungeon games
        with patch.object(turn_machine, 'can_complete_after_timeout', return_value=True):
            turn_machine.complete()
            assert turn_machine.is_completed()
    
    def test_can_complete_after_timeout_dungeon(self, turn_machine, mock_storage):
        """Test can_complete_after_timeout logic for dungeon games."""
        # Setup dungeon game
        mock_storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com', 'player2@example.com'],
            'game_type': 'dungeon'
        }
        
        # Add one response
        turn_machine.metadata['players_responded'] = ['player1@example.com']
        
        assert turn_machine.can_complete_after_timeout() is True
    
    def test_can_complete_after_timeout_intimacy(self, turn_machine, mock_storage):
        """Test can_complete_after_timeout logic for therapy sessions."""
        # Setup therapy session
        mock_storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com', 'player2@example.com'],
            'game_type': 'intimacy'
        }
        
        # Add one response (not enough for therapy)
        turn_machine.metadata['players_responded'] = ['player1@example.com']
        
        assert turn_machine.can_complete_after_timeout() is False
        
        # Add both responses (enough for therapy)
        turn_machine.metadata['players_responded'] = ['player1@example.com', 'player2@example.com']
        
        assert turn_machine.can_complete_after_timeout() is True


class TestStateMachineManager:
    """Test StateMachineManager functionality."""
    
    @pytest.fixture
    def mock_storage(self):
        """Mock storage manager."""
        storage = Mock()
        storage.get_session.return_value = {
            'session_id': 'test-123',
            'players': ['player1@example.com', 'player2@example.com'],
            'turn_count': 5
        }
        return storage
    
    @pytest.fixture
    def manager(self, mock_storage):
        """Create StateMachineManager instance."""
        return StateMachineManager(storage=mock_storage)
    
    def test_get_session_machine(self, manager):
        """Test getting session state machine."""
        machine1 = manager.get_session_machine('test-123')
        machine2 = manager.get_session_machine('test-123')
        
        # Should return the same instance
        assert machine1 is machine2
        assert isinstance(machine1, SessionStateMachine)
    
    def test_get_turn_machine(self, manager):
        """Test getting turn state machine."""
        machine1 = manager.get_turn_machine('test-123', 1)
        machine2 = manager.get_turn_machine('test-123', 1)
        machine3 = manager.get_turn_machine('test-123', 2)
        
        # Same session and turn should return same instance
        assert machine1 is machine2
        # Different turn should return different instance
        assert machine1 is not machine3
        assert isinstance(machine1, TurnStateMachine)
    
    def test_cleanup_completed_turns(self, manager):
        """Test cleanup of completed turn machines."""
        # Create several turn machines
        turn1 = manager.get_turn_machine('test-123', 1)
        turn2 = manager.get_turn_machine('test-123', 2)
        turn3 = manager.get_turn_machine('test-123', 5)  # Current turn
        
        # Mark older turns as completed
        turn1.metadata['completed_at'] = datetime.now().isoformat()
        turn1.state = TurnState.COMPLETED.value
        turn2.metadata['completed_at'] = datetime.now().isoformat()
        turn2.state = TurnState.COMPLETED.value
        
        # Cleanup should remove old completed turns
        manager.cleanup_completed_turns('test-123', keep_recent=1)
        
        # Current turn should still exist
        current_machine = manager.get_turn_machine('test-123', 5)
        assert current_machine is turn3
    
    def test_get_session_state_summary(self, manager):
        """Test getting session state summary."""
        # Create some machines
        session_machine = manager.get_session_machine('test-123')
        turn_machine = manager.get_turn_machine('test-123', 5)
        
        # Set some state
        turn_machine.set_waiting_players(['player1@example.com'])
        turn_machine.add_player_response('player2@example.com')
        
        summary = manager.get_session_state_summary('test-123')
        
        assert summary['session_id'] == 'test-123'
        assert summary['session_state'] == SessionState.INITIALIZING.value
        assert summary['current_turn'] == 5
        assert 5 in summary['turn_states']
        
        turn_summary = summary['turn_states'][5]
        assert 'player1@example.com' in turn_summary['waiting_players']
        assert 'player2@example.com' in turn_summary['responded_players']
    
    def test_get_current_turn(self, manager, mock_storage):
        """Test getting current turn number."""
        assert manager.get_current_turn('test-123') == 5
        
        # Test with no session
        mock_storage.get_session.return_value = None
        assert manager.get_current_turn('nonexistent') == 0


class TestGlobalManager:
    """Test global state machine manager."""
    
    def test_get_state_machine_manager(self):
        """Test getting global manager instance."""
        manager1 = get_state_machine_manager()
        manager2 = get_state_machine_manager()
        
        # Should return the same instance
        assert manager1 is manager2
        assert isinstance(manager1, StateMachineManager)


class TestStateEnums:
    """Test state enumerations."""
    
    def test_session_state_values(self):
        """Test SessionState enum values."""
        assert SessionState.INITIALIZING.value == "initializing"
        assert SessionState.WAITING_FOR_PLAYERS.value == "waiting_for_players"
        assert SessionState.ACTIVE.value == "active"
        assert SessionState.PAUSED.value == "paused"
        assert SessionState.COMPLETED.value == "completed"
        assert SessionState.TIMED_OUT.value == "timed_out"
        assert SessionState.ARCHIVED.value == "archived"
    
    def test_turn_state_values(self):
        """Test TurnState enum values."""
        assert TurnState.WAITING_FOR_PLAYERS.value == "waiting_for_players"
        assert TurnState.PROCESSING.value == "processing"
        assert TurnState.COMPLETED.value == "completed"
        assert TurnState.TIMED_OUT.value == "timed_out"