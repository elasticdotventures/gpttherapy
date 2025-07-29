"""
Storage management for GPT Therapy sessions using DynamoDB and S3.
Handles session state, turn history, and player data.
"""

import json
from typing import Any, cast

import boto3
from botocore.exceptions import ClientError

# Import structured logging configuration and settings
from datetime_utils import timestamps
from logging_config import get_logger
from nanoid import generate
from settings import settings

logger = get_logger(__name__)


class StorageManager:
    """Manages DynamoDB and S3 storage for GPT Therapy sessions."""

    def __init__(self) -> None:
        # Use centralized settings
        self.aws_region = settings.AWS_REGION
        self.is_test = settings.IS_TEST_ENV

        # Initialize AWS clients
        self.dynamodb = boto3.resource("dynamodb", region_name=self.aws_region)
        self.s3 = boto3.client("s3", region_name=self.aws_region)

        # Table names from settings
        self.sessions_table_name = settings.SESSIONS_TABLE_NAME
        self.turns_table_name = settings.TURNS_TABLE_NAME
        self.players_table_name = settings.PLAYERS_TABLE_NAME

        # S3 bucket name from settings
        self.gamedata_bucket = settings.GAMEDATA_S3_BUCKET

        # Get table references
        self.sessions_table = self.dynamodb.Table(self.sessions_table_name)
        self.turns_table = self.dynamodb.Table(self.turns_table_name)
        self.players_table = self.dynamodb.Table(self.players_table_name)

    def _get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format."""
        return timestamps.now()

    def _test_prefix(self, key: str) -> str:
        """Add test/ prefix for test records."""
        if self.is_test:
            return f"test/{key}"
        return key

    # Session Management

    def create_session(
        self, game_type: str, initiator_email: str, session_data: dict[str, Any]
    ) -> str:
        """Create a new game session."""
        # Generate human-readable session ID
        # Use safe alphabet: no 0/O, 1/I/l confusion, email-safe characters
        session_id = generate(
            alphabet="23456789ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz", size=12
        )
        timestamp = self._get_timestamp()

        session_item = {
            "session_id": session_id,
            "game_type": game_type,
            "status": "initializing",
            "initiator_email": initiator_email,
            "created_at": timestamp,
            "updated_at": timestamp,
            "turn_count": 0,
            "player_count": 1,
            "players": [initiator_email],
            "is_test": self.is_test,
            **session_data,
        }

        try:
            self.sessions_table.put_item(Item=session_item)
            logger.info(
                "Session created",
                session_id=session_id,
                game_type=game_type,
                initiator_email=initiator_email,
                is_test=self.is_test,
            )
            return str(session_id)
        except ClientError as e:
            logger.error(
                "Failed to create session",
                error=str(e),
                game_type=game_type,
                initiator_email=initiator_email,
            )
            raise

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Retrieve session data by ID."""
        try:
            response = self.sessions_table.get_item(Key={"session_id": session_id})
            item = response.get("Item")
            return dict(item) if item is not None else None
        except ClientError as e:
            logger.error("Failed to get session", session_id=session_id, error=str(e))
            raise

    def update_session(self, session_id: str, updates: dict[str, Any]) -> bool:
        """Update session with new data."""
        updates["updated_at"] = self._get_timestamp()

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

        update_expr = update_expr.rstrip(", ")

        try:
            self.sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression=update_expr,
                ExpressionAttributeNames=expr_names,
                ExpressionAttributeValues=expr_values,
            )
            logger.info(
                "Session updated",
                session_id=session_id,
                updated_fields=list(updates.keys()),
            )
            return True
        except ClientError as e:
            logger.error(
                "Failed to update session",
                session_id=session_id,
                error=str(e),
                update_fields=list(updates.keys()),
            )
            raise

    def add_player_to_session(self, session_id: str, player_email: str) -> bool:
        """Add a player to an existing session."""
        try:
            self.sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="ADD players :player SET player_count = player_count + :one, updated_at = :timestamp",
                ExpressionAttributeValues={
                    ":player": {player_email},
                    ":one": 1,
                    ":timestamp": self._get_timestamp(),
                },
            )
            logger.info(
                "Player added to session",
                session_id=session_id,
                player_email=player_email,
            )
            return True
        except ClientError as e:
            logger.error(
                "Failed to add player to session",
                session_id=session_id,
                player_email=player_email,
                error=str(e),
            )
            raise

    # Turn Management

    def save_turn(
        self,
        session_id: str,
        turn_number: int,
        player_email: str,
        turn_data: dict[str, Any],
    ) -> bool:
        """Save a player's turn to the database."""
        timestamp = self._get_timestamp()

        turn_item = {
            "session_id": session_id,
            "turn_number": turn_number,
            "player_email": player_email,
            "timestamp": timestamp,
            "is_test": self.is_test,
            **turn_data,
        }

        try:
            self.turns_table.put_item(Item=turn_item)

            # Update session turn count
            self.sessions_table.update_item(
                Key={"session_id": session_id},
                UpdateExpression="SET turn_count = :count, updated_at = :timestamp",
                ExpressionAttributeValues={
                    ":count": turn_number,
                    ":timestamp": timestamp,
                },
            )

            logger.info(
                "Turn saved",
                session_id=session_id,
                turn_number=turn_number,
                player_email=player_email,
            )
            return True
        except ClientError as e:
            logger.error(
                "Failed to save turn",
                session_id=session_id,
                turn_number=turn_number,
                player_email=player_email,
                error=str(e),
            )
            raise

    def get_session_turns(
        self, session_id: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        """Get all turns for a session, ordered by turn number."""
        try:
            response = self.turns_table.query(
                KeyConditionExpression="session_id = :sid",
                ExpressionAttributeValues={":sid": session_id},
                ScanIndexForward=True,  # Sort ascending by turn_number
                Limit=limit,
            )
            items = response.get("Items", [])
            return cast(list[dict[str, Any]], items)
        except ClientError as e:
            logger.error(
                "Failed to get session turns", session_id=session_id, error=str(e)
            )
            raise

    def get_latest_turn(self, session_id: str) -> dict[str, Any] | None:
        """Get the most recent turn for a session."""
        try:
            response = self.turns_table.query(
                KeyConditionExpression="session_id = :sid",
                ExpressionAttributeValues={":sid": session_id},
                ScanIndexForward=False,  # Sort descending by turn_number
                Limit=1,
            )
            items = response.get("Items", [])
            return cast(list[dict[str, Any]], items)[0] if items else None
        except ClientError as e:
            logger.error(
                "Failed to get latest turn", session_id=session_id, error=str(e)
            )
            raise

    # Player Management

    def create_or_update_player(self, email: str, player_data: dict[str, Any]) -> bool:
        """Create or update player profile."""
        timestamp = self._get_timestamp()

        player_item = {
            "email": email,
            "updated_at": timestamp,
            "is_test": self.is_test,
            **player_data,
        }

        # Add created_at only if this is a new player
        try:
            existing = self.players_table.get_item(Key={"email": email})
            if "Item" not in existing:
                player_item["created_at"] = timestamp
        except ClientError:
            player_item["created_at"] = timestamp

        try:
            self.players_table.put_item(Item=player_item)
            logger.info(
                "Player profile updated",
                player_email=email,
                is_new_player="created_at" in player_item,
            )
            return True
        except ClientError as e:
            logger.error("Failed to update player", player_email=email, error=str(e))
            raise

    def get_player(self, email: str) -> dict[str, Any] | None:
        """Get player profile by email."""
        try:
            response = self.players_table.get_item(Key={"email": email})
            item = response.get("Item")
            return cast(dict[str, Any] | None, item)
        except ClientError as e:
            logger.error("Failed to get player", player_email=email, error=str(e))
            raise

    # S3 Game Data Storage

    def save_game_state(self, session_id: str, state_data: dict[str, Any]) -> bool:
        """Save game state to S3."""
        key = self._test_prefix(f"sessions/{session_id}/state.json")

        try:
            self.s3.put_object(
                Bucket=self.gamedata_bucket,
                Key=key,
                Body=json.dumps(state_data, default=str),
                ContentType="application/json",
            )
            logger.info("Game state saved", session_id=session_id, s3_key=key)
            return True
        except ClientError as e:
            logger.error(
                "Failed to save game state",
                session_id=session_id,
                s3_key=key,
                error=str(e),
            )
            raise

    def load_game_state(self, session_id: str) -> dict[str, Any] | None:
        """Load game state from S3."""
        key = self._test_prefix(f"sessions/{session_id}/state.json")

        try:
            response = self.s3.get_object(Bucket=self.gamedata_bucket, Key=key)
            data = json.loads(response["Body"].read().decode("utf-8"))
            return cast(dict[str, Any], data)
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                logger.info("No game state found", session_id=session_id, s3_key=key)
                return None
            logger.error(
                "Failed to load game state",
                session_id=session_id,
                s3_key=key,
                error=str(e),
            )
            raise

    def archive_email(self, session_id: str, email_data: dict[str, Any]) -> bool:
        """Archive email content to S3."""
        timestamp = timestamps.filename_timestamp()
        key = self._test_prefix(f"sessions/{session_id}/emails/{timestamp}.json")

        try:
            self.s3.put_object(
                Bucket=self.gamedata_bucket,
                Key=key,
                Body=json.dumps(email_data, default=str),
                ContentType="application/json",
            )
            logger.info(
                "Email archived",
                session_id=session_id,
                s3_key=key,
                email_from=email_data.get("from"),
            )
            return True
        except ClientError as e:
            logger.error(
                "Failed to archive email",
                session_id=session_id,
                s3_key=key,
                error=str(e),
            )
            raise

    # Query Methods

    def get_active_sessions(
        self, game_type: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """Get active sessions, optionally filtered by game type."""
        try:
            if game_type:
                # Query by game type
                response = self.sessions_table.query(
                    IndexName="GameTypeIndex",
                    KeyConditionExpression="game_type = :gt",
                    FilterExpression="#status IN (:active, :waiting)",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":gt": game_type,
                        ":active": "active",
                        ":waiting": "waiting_for_players",
                    },
                    Limit=limit,
                )
            else:
                # Scan all active sessions
                response = self.sessions_table.scan(
                    FilterExpression="#status IN (:active, :waiting)",
                    ExpressionAttributeNames={"#status": "status"},
                    ExpressionAttributeValues={
                        ":active": "active",
                        ":waiting": "waiting_for_players",
                    },
                    Limit=limit,
                )

            items = response.get("Items", [])
            return cast(list[dict[str, Any]], items)
        except ClientError as e:
            logger.error(
                "Failed to get active sessions", game_type=game_type, error=str(e)
            )
            raise

    def get_player_sessions(
        self, player_email: str, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get all sessions for a specific player."""
        try:
            # This requires scanning since players is a set attribute
            response = self.sessions_table.scan(
                FilterExpression="contains(players, :email)",
                ExpressionAttributeValues={":email": player_email},
                Limit=limit,
            )
            items = response.get("Items", [])
            return cast(list[dict[str, Any]], items)
        except ClientError as e:
            logger.error(
                "Failed to get player sessions", player_email=player_email, error=str(e)
            )
            raise


# Convenience functions for Lambda usage
def get_storage_manager() -> StorageManager:
    """Get a configured StorageManager instance."""
    return StorageManager()


def extract_session_id_from_email(email_address: str) -> str | None:
    """Extract session ID from email address like '123@dungeon.promptexecution.com'."""
    try:
        if not email_address or "@" not in email_address:
            return None

        local_part = email_address.split("@")[0]

        # Validate that it looks like a reasonable session ID
        # Must be alphanumeric with optional hyphens, and not common words
        invalid_addresses = {
            "general",
            "admin",
            "support",
            "info",
            "contact",
            "hello",
            "noreply",
        }

        if (
            local_part
            and local_part.lower() not in invalid_addresses
            and (local_part.replace("-", "").isalnum())
            and len(local_part) >= 3
        ):  # Session IDs should be at least 3 characters
            return local_part
        return None
    except (IndexError, AttributeError):
        return None
