"""
Storage management for GPT Therapy sessions using DynamoDB and S3.
Handles session state, turn history, and player data.
"""

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union
import boto3
from botocore.exceptions import ClientError
import logging

logger = logging.getLogger(__name__)

class StorageManager:
    """Manages DynamoDB and S3 storage for GPT Therapy sessions."""
    
    def __init__(self):
        self.aws_region = os.environ.get('AWS_REGION', 'ap-southeast-4')
        self.is_test = os.environ.get('IS_TEST_ENV', 'false').lower() == 'true'
        
        # Initialize AWS clients
        self.dynamodb = boto3.resource('dynamodb', region_name=self.aws_region)
        self.s3 = boto3.client('s3', region_name=self.aws_region)
        
        # Table names from environment
        self.sessions_table_name = os.environ['SESSIONS_TABLE_NAME']
        self.turns_table_name = os.environ['TURNS_TABLE_NAME']
        self.players_table_name = os.environ['PLAYERS_TABLE_NAME']
        
        # S3 bucket name
        self.gamedata_bucket = os.environ['GAMEDATA_S3_BUCKET']
        
        # Get table references
        self.sessions_table = self.dynamodb.Table(self.sessions_table_name)
        self.turns_table = self.dynamodb.Table(self.turns_table_name)
        self.players_table = self.dynamodb.Table(self.players_table_name)
    
    def _get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()
    
    def _test_prefix(self, key: str) -> str:
        """Add test/ prefix for test records."""
        if self.is_test:
            return f"test/{key}"
        return key

    # Session Management
    
    def create_session(self, game_type: str, initiator_email: str, 
                      session_data: Dict[str, Any]) -> str:
        """Create a new game session."""
        session_id = str(uuid.uuid4())
        timestamp = self._get_timestamp()
        
        session_item = {
            'session_id': session_id,
            'game_type': game_type,
            'status': 'initializing',
            'initiator_email': initiator_email,
            'created_at': timestamp,
            'updated_at': timestamp,
            'turn_count': 0,
            'player_count': 1,
            'players': [initiator_email],
            'is_test': self.is_test,
            **session_data
        }
        
        try:
            self.sessions_table.put_item(Item=session_item)
            logger.info(f"Created session {session_id} for {game_type}")
            return session_id
        except ClientError as e:
            logger.error(f"Failed to create session: {e}")
            raise
    
    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve session data by ID."""
        try:
            response = self.sessions_table.get_item(Key={'session_id': session_id})
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Failed to get session {session_id}: {e}")
            raise
    
    def update_session(self, session_id: str, updates: Dict[str, Any]) -> bool:
        """Update session with new data."""
        updates['updated_at'] = self._get_timestamp()
        
        # Build update expression
        update_expr = "SET "
        expr_values = {}
        expr_names = {}
        
        for key, value in updates.items():
            safe_key = f"#{key}"
            value_key = f":{key}"
            update_expr += f"{safe_key} = {value_key}, "
            expr_names[safe_key] = key
            expr_values[value_key] = value
        
        update_expr = update_expr.rstrip(', ')
        
        try:
            self.sessions_table.update_item(
                Key={'session_id': session_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values
            )
            logger.info(f"Updated session {session_id}")
            return True
        except ClientError as e:
            logger.error(f"Failed to update session {session_id}: {e}")
            raise
    
    def add_player_to_session(self, session_id: str, player_email: str) -> bool:
        """Add a player to an existing session."""
        try:
            self.sessions_table.update_item(
                Key={'session_id': session_id},
                UpdateExpression="ADD players :player SET player_count = player_count + :one, updated_at = :timestamp",
                ExpressionAttributeValues={
                    ':player': {player_email},
                    ':one': 1,
                    ':timestamp': self._get_timestamp()
                }
            )
            logger.info(f"Added player {player_email} to session {session_id}")
            return True
        except ClientError as e:
            logger.error(f"Failed to add player to session {session_id}: {e}")
            raise

    # Turn Management
    
    def save_turn(self, session_id: str, turn_number: int, player_email: str,
                  turn_data: Dict[str, Any]) -> bool:
        """Save a player's turn to the database."""
        timestamp = self._get_timestamp()
        
        turn_item = {
            'session_id': session_id,
            'turn_number': turn_number,
            'player_email': player_email,
            'timestamp': timestamp,
            'is_test': self.is_test,
            **turn_data
        }
        
        try:
            self.turns_table.put_item(Item=turn_item)
            
            # Update session turn count
            self.sessions_table.update_item(
                Key={'session_id': session_id},
                UpdateExpression="SET turn_count = :count, updated_at = :timestamp",
                ExpressionAttributeValues={
                    ':count': turn_number,
                    ':timestamp': timestamp
                }
            )
            
            logger.info(f"Saved turn {turn_number} for session {session_id}")
            return True
        except ClientError as e:
            logger.error(f"Failed to save turn: {e}")
            raise
    
    def get_session_turns(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get all turns for a session, ordered by turn number."""
        try:
            response = self.turns_table.query(
                KeyConditionExpression="session_id = :sid",
                ExpressionAttributeValues={':sid': session_id},
                ScanIndexForward=True,  # Sort ascending by turn_number
                Limit=limit
            )
            return response.get('Items', [])
        except ClientError as e:
            logger.error(f"Failed to get turns for session {session_id}: {e}")
            raise
    
    def get_latest_turn(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent turn for a session."""
        try:
            response = self.turns_table.query(
                KeyConditionExpression="session_id = :sid",
                ExpressionAttributeValues={':sid': session_id},
                ScanIndexForward=False,  # Sort descending by turn_number
                Limit=1
            )
            items = response.get('Items', [])
            return items[0] if items else None
        except ClientError as e:
            logger.error(f"Failed to get latest turn for session {session_id}: {e}")
            raise

    # Player Management
    
    def create_or_update_player(self, email: str, player_data: Dict[str, Any]) -> bool:
        """Create or update player profile."""
        timestamp = self._get_timestamp()
        
        player_item = {
            'email': email,
            'updated_at': timestamp,
            'is_test': self.is_test,
            **player_data
        }
        
        # Add created_at only if this is a new player
        try:
            existing = self.players_table.get_item(Key={'email': email})
            if 'Item' not in existing:
                player_item['created_at'] = timestamp
        except ClientError:
            player_item['created_at'] = timestamp
        
        try:
            self.players_table.put_item(Item=player_item)
            logger.info(f"Updated player profile for {email}")
            return True
        except ClientError as e:
            logger.error(f"Failed to update player {email}: {e}")
            raise
    
    def get_player(self, email: str) -> Optional[Dict[str, Any]]:
        """Get player profile by email."""
        try:
            response = self.players_table.get_item(Key={'email': email})
            return response.get('Item')
        except ClientError as e:
            logger.error(f"Failed to get player {email}: {e}")
            raise

    # S3 Game Data Storage
    
    def save_game_state(self, session_id: str, state_data: Dict[str, Any]) -> bool:
        """Save game state to S3."""
        key = self._test_prefix(f"sessions/{session_id}/state.json")
        
        try:
            self.s3.put_object(
                Bucket=self.gamedata_bucket,
                Key=key,
                Body=json.dumps(state_data, default=str),
                ContentType='application/json'
            )
            logger.info(f"Saved game state for session {session_id}")
            return True
        except ClientError as e:
            logger.error(f"Failed to save game state: {e}")
            raise
    
    def load_game_state(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load game state from S3."""
        key = self._test_prefix(f"sessions/{session_id}/state.json")
        
        try:
            response = self.s3.get_object(Bucket=self.gamedata_bucket, Key=key)
            return json.loads(response['Body'].read().decode('utf-8'))
        except ClientError as e:
            if e.response['Error']['Code'] == 'NoSuchKey':
                logger.info(f"No game state found for session {session_id}")
                return None
            logger.error(f"Failed to load game state: {e}")
            raise
    
    def archive_email(self, session_id: str, email_data: Dict[str, Any]) -> bool:
        """Archive email content to S3."""
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        key = self._test_prefix(f"sessions/{session_id}/emails/{timestamp}.json")
        
        try:
            self.s3.put_object(
                Bucket=self.gamedata_bucket,
                Key=key,
                Body=json.dumps(email_data, default=str),
                ContentType='application/json'
            )
            logger.info(f"Archived email for session {session_id}")
            return True
        except ClientError as e:
            logger.error(f"Failed to archive email: {e}")
            raise

    # Query Methods
    
    def get_active_sessions(self, game_type: str = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get active sessions, optionally filtered by game type."""
        try:
            if game_type:
                # Query by game type
                response = self.sessions_table.query(
                    IndexName='GameTypeIndex',
                    KeyConditionExpression="game_type = :gt",
                    FilterExpression="#status IN (:active, :waiting)",
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':gt': game_type,
                        ':active': 'active',
                        ':waiting': 'waiting_for_players'
                    },
                    Limit=limit
                )
            else:
                # Scan all active sessions
                response = self.sessions_table.scan(
                    FilterExpression="#status IN (:active, :waiting)",
                    ExpressionAttributeNames={'#status': 'status'},
                    ExpressionAttributeValues={
                        ':active': 'active',
                        ':waiting': 'waiting_for_players'
                    },
                    Limit=limit
                )
            
            return response.get('Items', [])
        except ClientError as e:
            logger.error(f"Failed to get active sessions: {e}")
            raise
    
    def get_player_sessions(self, player_email: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Get all sessions for a specific player."""
        try:
            # This requires scanning since players is a set attribute
            response = self.sessions_table.scan(
                FilterExpression="contains(players, :email)",
                ExpressionAttributeValues={':email': player_email},
                Limit=limit
            )
            return response.get('Items', [])
        except ClientError as e:
            logger.error(f"Failed to get sessions for player {player_email}: {e}")
            raise

# Convenience functions for Lambda usage
def get_storage_manager() -> StorageManager:
    """Get a configured StorageManager instance."""
    return StorageManager()

def extract_session_id_from_email(email_address: str) -> Optional[str]:
    """Extract session ID from email address like '123@dungeon.promptexecution.com'."""
    try:
        if not email_address or '@' not in email_address:
            return None
        
        local_part = email_address.split('@')[0]
        
        # Validate that it looks like a reasonable session ID
        # Must be alphanumeric with optional hyphens, and not common words
        invalid_addresses = {'general', 'admin', 'support', 'info', 'contact', 'hello', 'noreply'}
        
        if (local_part and 
            local_part.lower() not in invalid_addresses and
            (local_part.replace('-', '').isalnum()) and
            len(local_part) >= 3):  # Session IDs should be at least 3 characters
            return local_part
        return None
    except (IndexError, AttributeError):
        return None