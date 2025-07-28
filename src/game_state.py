"""
Game state persistence layer for GPT Therapy sessions.
Manages complex game states, character data, and narrative progression.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from .storage import StorageManager
except ImportError:
    from storage import StorageManager

logger = logging.getLogger(__name__)

class GameStateType(Enum):
    """Types of game states that can be persisted."""
    CHARACTER_STATE = "character_state"
    WORLD_STATE = "world_state"
    NARRATIVE_STATE = "narrative_state"
    THERAPY_STATE = "therapy_state"
    MISSION_STATE = "mission_state"

@dataclass
class CharacterState:
    """Character state for dungeon adventures."""
    name: str
    background: str
    health: int = 100
    inventory: List[str] = None
    skills: Dict[str, int] = None
    experience: int = 0
    level: int = 1
    location: str = "starting_area"
    status_effects: List[str] = None
    
    def __post_init__(self):
        if self.inventory is None:
            self.inventory = []
        if self.skills is None:
            self.skills = {}
        if self.status_effects is None:
            self.status_effects = []

@dataclass
class WorldState:
    """World state for dungeon adventures."""
    current_location: str
    discovered_locations: List[str] = None
    world_events: List[Dict[str, Any]] = None
    time_of_day: str = "morning"
    weather: str = "clear"
    active_npcs: Dict[str, Any] = None
    environmental_changes: List[str] = None
    
    def __post_init__(self):
        if self.discovered_locations is None:
            self.discovered_locations = [self.current_location]
        if self.world_events is None:
            self.world_events = []
        if self.active_npcs is None:
            self.active_npcs = {}
        if self.environmental_changes is None:
            self.environmental_changes = []

@dataclass
class NarrativeState:
    """Narrative progression state."""
    main_plot_points: List[str] = None
    completed_events: List[str] = None
    available_paths: List[str] = None
    narrative_flags: Dict[str, bool] = None
    story_beats: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.main_plot_points is None:
            self.main_plot_points = []
        if self.completed_events is None:
            self.completed_events = []
        if self.available_paths is None:
            self.available_paths = []
        if self.narrative_flags is None:
            self.narrative_flags = {}
        if self.story_beats is None:
            self.story_beats = []

@dataclass
class TherapyState:
    """Therapy session state for couples therapy."""
    current_phase: str = "assessment"
    completed_exercises: List[str] = None
    therapy_goals: List[str] = None
    progress_notes: List[Dict[str, Any]] = None
    relationship_metrics: Dict[str, float] = None
    communication_patterns: Dict[str, Any] = None
    homework_assignments: List[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.completed_exercises is None:
            self.completed_exercises = []
        if self.therapy_goals is None:
            self.therapy_goals = []
        if self.progress_notes is None:
            self.progress_notes = []
        if self.relationship_metrics is None:
            self.relationship_metrics = {}
        if self.communication_patterns is None:
            self.communication_patterns = {}
        if self.homework_assignments is None:
            self.homework_assignments = []

@dataclass
class MissionState:
    """Mission/scenario specific state."""
    mission_type: str
    mission_objectives: List[str] = None
    completed_objectives: List[str] = None
    mission_progress: float = 0.0
    mission_data: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.mission_objectives is None:
            self.mission_objectives = []
        if self.completed_objectives is None:
            self.completed_objectives = []
        if self.mission_data is None:
            self.mission_data = {}

class GameStateManager:
    """Manages game state persistence and retrieval."""
    
    def __init__(self, storage_manager: StorageManager = None):
        self.storage = storage_manager or StorageManager()
    
    def save_game_state(self, session_id: str, state_type: GameStateType, 
                       state_data: Union[Dict[str, Any], Any], 
                       player_email: str = None) -> bool:
        """
        Save game state to persistent storage.
        
        Args:
            session_id: Session identifier
            state_type: Type of game state being saved
            state_data: State data (dict or dataclass)
            player_email: Optional player email for player-specific states
            
        Returns:
            Success status
        """
        try:
            # Convert dataclass to dict if needed
            if hasattr(state_data, '__dataclass_fields__'):
                state_dict = asdict(state_data)
            else:
                state_dict = state_data
            
            # Prepare state document
            state_document = {
                'session_id': session_id,
                'state_type': state_type.value,
                'player_email': player_email,
                'state_data': state_dict,
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'version': 1
            }
            
            # Determine storage key
            if player_email:
                key = f"sessions/{session_id}/states/{state_type.value}/{player_email}.json"
            else:
                key = f"sessions/{session_id}/states/{state_type.value}/global.json"
            
            # Save to S3
            success = self.storage.save_game_state(session_id, {
                'key': key,
                'state_document': state_document
            })
            
            if success:
                logger.info(f"Saved {state_type.value} for session {session_id}")
            
            return success
            
        except Exception as e:
            logger.error(f"Error saving game state: {e}")
            return False
    
    def load_game_state(self, session_id: str, state_type: GameStateType, 
                       player_email: str = None) -> Optional[Dict[str, Any]]:
        """
        Load game state from persistent storage.
        
        Args:
            session_id: Session identifier
            state_type: Type of game state to load
            player_email: Optional player email for player-specific states
            
        Returns:
            State data or None if not found
        """
        try:
            # Load from S3
            state_container = self.storage.load_game_state(session_id)
            
            if not state_container:
                return None
            
            # Determine which state to extract
            if player_email:
                key = f"sessions/{session_id}/states/{state_type.value}/{player_email}.json"
            else:
                key = f"sessions/{session_id}/states/{state_type.value}/global.json"
            
            # Extract specific state if stored as container
            if 'key' in state_container and state_container['key'] == key:
                state_document = state_container.get('state_document', {})
                return state_document.get('state_data')
            
            # Fallback: return entire container if it matches our pattern
            if state_container.get('state_type') == state_type.value:
                return state_container.get('state_data')
            
            return None
            
        except Exception as e:
            logger.error(f"Error loading game state: {e}")
            return None
    
    def create_character_state(self, session_id: str, player_email: str, 
                              character_data: Dict[str, Any]) -> CharacterState:
        """Create and save a new character state."""
        try:
            character = CharacterState(
                name=character_data.get('name', 'Unknown'),
                background=character_data.get('background', 'mysterious'),
                health=character_data.get('health', 100),
                inventory=character_data.get('inventory', []),
                skills=character_data.get('skills', {}),
                location=character_data.get('location', 'starting_area')
            )
            
            # Save to storage
            self.save_game_state(
                session_id, 
                GameStateType.CHARACTER_STATE, 
                character, 
                player_email
            )
            
            logger.info(f"Created character '{character.name}' for {player_email}")
            return character
            
        except Exception as e:
            logger.error(f"Error creating character state: {e}")
            raise
    
    def update_character_state(self, session_id: str, player_email: str, 
                              updates: Dict[str, Any]) -> bool:
        """Update existing character state."""
        try:
            # Load current state
            current_state = self.load_game_state(
                session_id, GameStateType.CHARACTER_STATE, player_email
            )
            
            if not current_state:
                logger.warning(f"No character state found for {player_email}")
                return False
            
            # Apply updates
            for key, value in updates.items():
                if key in current_state:
                    current_state[key] = value
            
            # Save updated state
            return self.save_game_state(
                session_id, GameStateType.CHARACTER_STATE, current_state, player_email
            )
            
        except Exception as e:
            logger.error(f"Error updating character state: {e}")
            return False
    
    def create_world_state(self, session_id: str, initial_location: str = "entrance") -> WorldState:
        """Create and save initial world state."""
        try:
            world = WorldState(current_location=initial_location)
            
            # Save to storage
            self.save_game_state(session_id, GameStateType.WORLD_STATE, world)
            
            logger.info(f"Created world state for session {session_id}")
            return world
            
        except Exception as e:
            logger.error(f"Error creating world state: {e}")
            raise
    
    def update_world_state(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update world state."""
        try:
            # Load current state
            current_state = self.load_game_state(session_id, GameStateType.WORLD_STATE)
            
            if not current_state:
                # Create new world state if none exists
                world = WorldState(current_location=updates.get('current_location', 'entrance'))
                current_state = asdict(world)
            
            # Apply updates
            for key, value in updates.items():
                current_state[key] = value
            
            # Save updated state
            return self.save_game_state(session_id, GameStateType.WORLD_STATE, current_state)
            
        except Exception as e:
            logger.error(f"Error updating world state: {e}")
            return False
    
    def create_therapy_state(self, session_id: str, therapy_goals: List[str]) -> TherapyState:
        """Create and save initial therapy state."""
        try:
            therapy = TherapyState(therapy_goals=therapy_goals)
            
            # Save to storage
            self.save_game_state(session_id, GameStateType.THERAPY_STATE, therapy)
            
            logger.info(f"Created therapy state for session {session_id}")
            return therapy
            
        except Exception as e:
            logger.error(f"Error creating therapy state: {e}")
            raise
    
    def update_therapy_progress(self, session_id: str, progress_update: Dict[str, Any]) -> bool:
        """Update therapy session progress."""
        try:
            # Load current state
            current_state = self.load_game_state(session_id, GameStateType.THERAPY_STATE)
            
            if not current_state:
                # Create new therapy state if none exists
                therapy = TherapyState()
                current_state = asdict(therapy)
            
            # Add progress note if provided
            if 'progress_note' in progress_update:
                if 'progress_notes' not in current_state:
                    current_state['progress_notes'] = []
                
                current_state['progress_notes'].append({
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'note': progress_update['progress_note'],
                    'therapist': progress_update.get('therapist', 'Dr. Alex Chen')
                })
            
            # Update other fields
            for key, value in progress_update.items():
                if key != 'progress_note' and key in current_state:
                    current_state[key] = value
            
            # Save updated state
            return self.save_game_state(session_id, GameStateType.THERAPY_STATE, current_state)
            
        except Exception as e:
            logger.error(f"Error updating therapy progress: {e}")
            return False
    
    def get_session_summary(self, session_id: str) -> Dict[str, Any]:
        """Get a comprehensive summary of session state."""
        try:
            summary = {
                'session_id': session_id,
                'character_states': {},
                'world_state': None,
                'narrative_state': None,
                'therapy_state': None,
                'mission_states': {},
                'last_updated': None
            }
            
            # Load different state types
            for state_type in GameStateType:
                try:
                    state_data = self.load_game_state(session_id, state_type)
                    if state_data:
                        if state_type == GameStateType.CHARACTER_STATE:
                            # Character states are player-specific, would need player list
                            pass
                        elif state_type == GameStateType.WORLD_STATE:
                            summary['world_state'] = state_data
                        elif state_type == GameStateType.NARRATIVE_STATE:
                            summary['narrative_state'] = state_data
                        elif state_type == GameStateType.THERAPY_STATE:
                            summary['therapy_state'] = state_data
                        elif state_type == GameStateType.MISSION_STATE:
                            summary['mission_states']['global'] = state_data
                        
                        # Update last_updated timestamp
                        updated_at = state_data.get('updated_at')
                        if updated_at and (not summary['last_updated'] or updated_at > summary['last_updated']):
                            summary['last_updated'] = updated_at
                            
                except Exception as e:
                    logger.debug(f"No {state_type.value} found for session {session_id}: {e}")
            
            return summary
            
        except Exception as e:
            logger.error(f"Error getting session summary: {e}")
            return {'error': str(e)}
    
    def backup_session_state(self, session_id: str) -> bool:
        """Create a backup of all session state."""
        try:
            # Get comprehensive summary
            summary = self.get_session_summary(session_id)
            
            if 'error' in summary:
                return False
            
            # Add timestamp to backup
            summary['backup_created'] = datetime.now(timezone.utc).isoformat()
            
            # Save backup
            backup_key = f"backups/{session_id}/{summary['backup_created']}.json"
            
            return self.storage.save_game_state(session_id, {
                'key': backup_key,
                'backup_data': summary
            })
            
        except Exception as e:
            logger.error(f"Error backing up session state: {e}")
            return False
    
    def restore_session_state(self, session_id: str, backup_timestamp: str) -> bool:
        """Restore session state from backup."""
        try:
            # This would need more sophisticated implementation
            # For now, just log the request
            logger.info(f"Restore requested for session {session_id} from {backup_timestamp}")
            
            # In a full implementation, this would:
            # 1. Load the backup data
            # 2. Restore each state type
            # 3. Update session metadata
            
            return False  # Not implemented yet
            
        except Exception as e:
            logger.error(f"Error restoring session state: {e}")
            return False

# Convenience functions for Lambda usage
def get_game_state_manager() -> GameStateManager:
    """Get a configured GameStateManager instance."""
    return GameStateManager()

def save_character_state(session_id: str, player_email: str, character_data: Dict[str, Any]) -> bool:
    """
    Convenience function to save character state.
    
    Args:
        session_id: Session identifier
        player_email: Player's email address
        character_data: Character information
        
    Returns:
        Success status
    """
    manager = get_game_state_manager()
    character = manager.create_character_state(session_id, player_email, character_data)
    return character is not None

def load_character_state(session_id: str, player_email: str) -> Optional[Dict[str, Any]]:
    """
    Convenience function to load character state.
    
    Args:
        session_id: Session identifier
        player_email: Player's email address
        
    Returns:
        Character state data or None
    """
    manager = get_game_state_manager()
    return manager.load_game_state(session_id, GameStateType.CHARACTER_STATE, player_email)

def update_world_state(session_id: str, world_updates: Dict[str, Any]) -> bool:
    """
    Convenience function to update world state.
    
    Args:
        session_id: Session identifier
        world_updates: World state updates
        
    Returns:
        Success status
    """
    manager = get_game_state_manager()
    return manager.update_world_state(session_id, world_updates)