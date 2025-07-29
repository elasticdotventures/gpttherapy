"""
Timeout processor for handling session and turn timeouts.
Can be triggered by CloudWatch Events or manually for maintenance.
"""

import json
from datetime import UTC
from typing import Any

import boto3
from botocore.exceptions import ClientError

try:
    from ai_agent import AIAgent
    from game_engine import GameEngine
    from logging_config import get_logger
    from settings import settings
    from storage import StorageManager
except ImportError:
    from ai_agent import AIAgent
    from game_engine import GameEngine
    from logging_config import get_logger
    from settings import settings
    from storage import StorageManager

# Configure structured logging
logger = get_logger(__name__)

# AWS clients using centralized config
ses_client = boto3.client("ses", region_name=settings.SES_REGION)

# Service instances
storage = StorageManager()
game_engine = GameEngine(storage)
ai_agent = AIAgent()


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for processing session timeouts and maintenance.

    This function can be triggered by:
    - EventBridge scheduled events (timeout checks, health checks, backups)
    - Manual invocation
    - API Gateway (for admin functions)

    Args:
        event: Event data (may contain processing options and event source)
        context: Lambda execution context

    Returns:
        Processing results and statistics
    """
    try:
        # Determine event source and type
        event_source = event.get("source", "manual")
        detail_type = event.get("detail-type", "Manual Invocation")
        detail = event.get("detail", {})

        logger.info(f"Starting processing for {detail_type} from {event_source}")

        # Get processing options from event detail or top level
        options = {**event, **detail}

        # Route to appropriate processor based on event type
        if detail.get("health_check"):
            results = process_health_check(options)
        elif detail.get("backup_sessions"):
            results = process_session_backups(options)
        elif detail.get("send_reminders"):
            results = process_reminder_sending(options)
        else:
            # Default to timeout processing
            results = process_session_timeouts(options)

        logger.info(f"Processing completed: {results.get('summary', {})}")

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "message": f"{detail_type} completed successfully",
                    "event_source": event_source,
                    "results": results,
                }
            ),
        }

    except Exception as e:
        logger.error(f"Error in scheduled processing: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps(
                {"error": "Scheduled processing failed", "message": str(e)}
            ),
        }


def process_timeouts(timed_out_sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Process a list of timed out sessions.

    Args:
        timed_out_sessions: List of session timeout information

    Returns:
        Processing results with success/error counts
    """
    results: dict[str, list[Any]] = {
        "processed": [],
        "errors": [],
        "reminders_sent": [],
        "sessions_paused": [],
    }

    for session_info in timed_out_sessions:
        session_id = session_info["session_id"]

        try:
            # Handle the timeout
            timeout_result = game_engine.handle_turn_timeout(session_id)

            if "error" in timeout_result:
                results["errors"].append(
                    {"session_id": session_id, "error": timeout_result["error"]}
                )
                continue

            # Send appropriate notifications
            if timeout_result["action"] == "paused":
                handle_session_pause(session_info, timeout_result)
                results["sessions_paused"].append(session_id)

                if timeout_result.get("reminder_needed"):
                    send_timeout_reminders(session_info)
                    results["reminders_sent"].append(session_id)

            elif timeout_result.get("turn_advancement"):
                # Session continued despite timeout
                send_continuation_notifications(session_info, timeout_result)

            results["processed"].append(
                {
                    "session_id": session_id,
                    "action": timeout_result["action"],
                    "game_type": session_info["game_type"],
                }
            )

        except Exception as e:
            logger.error(f"Error processing timeout for {session_id}: {e}")
            results["errors"].append({"session_id": session_id, "error": str(e)})

    return results


def handle_session_pause(
    session_info: dict[str, Any], timeout_result: dict[str, Any]
) -> None:
    """Handle a session that was paused due to timeout."""
    session_id = session_info["session_id"]
    waiting_for = session_info.get("waiting_for", [])

    logger.info(f"Session {session_id} paused due to timeout")

    # Log the pause for monitoring
    try:
        storage.archive_email(
            session_id,
            {
                "type": "system_event",
                "event": "session_paused",
                "reason": "turn_timeout",
                "waiting_for": waiting_for,
                "timeout_hours": session_info.get("timeout_hours"),
                "timestamp": session_info.get("last_activity"),
            },
        )
    except Exception as e:
        logger.error(f"Failed to archive pause event: {e}")


def send_timeout_reminders(session_info: dict[str, Any]) -> None:
    """Send reminder emails to players who haven't responded."""
    session_id = session_info["session_id"]
    game_type = session_info["game_type"]
    waiting_for = session_info.get("waiting_for", [])

    for player_email in waiting_for:
        try:
            reminder_subject = f"[Reminder] Your {game_type.title()} Session is Waiting"

            if game_type == "intimacy":
                reminder_body = f"""Dear Partner,

Your couples therapy session has been paused because we haven't received your response in the expected timeframe.

**Session Details:**
- Session ID: {session_id}
- Last Activity: {session_info.get("last_activity", "Unknown")}
- Turn: {session_info.get("turn_count", 0)}

**What This Means:**
Your session is safely paused and all progress is preserved. Your partner and therapist are waiting for your input to continue the therapeutic process.

**To Resume:**
Simply reply to this email or your most recent session email with your response. The session will automatically resume once you participate.

**Why This Matters:**
Consistent participation is important for effective couples therapy. Your voice and perspective are essential for the healing process.

If you're experiencing difficulties or need to reschedule, please let us know.

Warmly,
Dr. Alex Chen, LMFT
Session: {session_id}"""

            else:  # dungeon
                reminder_body = f"""Fellow Adventurer,

Your dungeon adventure is paused and your party is waiting for you!

**Adventure Status:**
- Session ID: {session_id}
- Last Action: {session_info.get("last_activity", "Unknown")}
- Turn: {session_info.get("turn_count", 0)}

**What Happened:**
The adventure is paused because we haven't heard from you. Your fellow adventurers are waiting for your next move!

**To Continue:**
Reply to this email or your most recent adventure email with your character's action. The quest will resume immediately.

**Your Party Needs You:**
Adventures are more fun with everyone participating. Your unique skills and perspective make the story better for everyone.

Ready to rejoin the adventure?

Your Dungeon Master
Session: {session_id}"""

            send_email(
                player_email, reminder_subject, reminder_body, session_id, game_type
            )
            logger.info(
                f"Sent timeout reminder to {player_email} for session {session_id}"
            )

        except Exception as e:
            logger.error(f"Failed to send timeout reminder to {player_email}: {e}")


def send_continuation_notifications(
    session_info: dict[str, Any], timeout_result: dict[str, Any]
) -> None:
    """Send notifications when a session continues despite some players timing out."""
    session_id = session_info["session_id"]

    # Get session to find all players
    try:
        session = storage.get_session(session_id)
        if not session:
            return

        all_players = session.get("players", [])
        waiting_for = session_info.get("waiting_for", [])
        active_players = [p for p in all_players if p not in waiting_for]

        # Send continuation notice to active players
        for player_email in active_players:
            subject = (
                f"[Adventure Continues] Turn {timeout_result['current_turn']} Complete"
            )

            body = f"""The adventure continues!

Some party members didn't respond in time, but the quest moves forward with those who are present.

**Current Status:**
- Turn {timeout_result["current_turn"]} completed
- Active players: {len(active_players)}
- Missing players: {len(waiting_for)}

The next turn begins now. What's your next move?

Your Dungeon Master
Session: {session_id}"""

            send_email(
                player_email, subject, body, session_id, session_info["game_type"]
            )

    except Exception as e:
        logger.error(f"Failed to send continuation notifications: {e}")


def send_email(
    to_address: str, subject: str, body: str, session_id: str, game_type: str
) -> None:
    """Send an email via SES."""
    try:
        from_address = f"{session_id}@{game_type}.promptexecution.com"

        response = ses_client.send_email(
            Source=from_address,
            Destination={"ToAddresses": [to_address]},
            Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
        )

        logger.info(f"Email sent to {to_address}: {response['MessageId']}")

    except ClientError as e:
        logger.error(
            f"Error sending email to {to_address}: {e.response['Error']['Message']}"
        )
        raise


# Utility functions for manual testing/administration
def check_session_health(session_id: str) -> dict[str, Any]:
    """Check the health and status of a specific session."""
    try:
        session = storage.get_session(session_id)
        if not session:
            return {"error": "Session not found"}

        # Get recent turns
        recent_turns = storage.get_session_turns(session_id, limit=5)

        # Check if session needs attention
        game_type = session.get("game_type")
        timeout_hours = game_engine.turn_timeout.get(game_type or "default", 24)

        last_activity = session.get("updated_at")
        needs_attention = False

        if last_activity:
            from datetime import datetime, timedelta

            last_time = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
            time_since = datetime.now(UTC) - last_time
            needs_attention = time_since > timedelta(hours=timeout_hours)

        return {
            "session_id": session_id,
            "game_type": game_type,
            "status": session.get("status"),
            "players": session.get("players", []),
            "turn_count": session.get("turn_count", 0),
            "last_activity": last_activity,
            "needs_attention": needs_attention,
            "recent_turns": len(recent_turns),
            "waiting_for": session.get("waiting_for", []),
        }

    except Exception as e:
        logger.error(f"Error checking session health: {e}")
        return {"error": str(e)}


def process_session_timeouts(options: dict[str, Any]) -> dict[str, Any]:
    """Process session timeouts (default processing)."""
    try:
        max_sessions = options.get("max_sessions", 100)
        dry_run = options.get("dry_run", False)

        # Check for timed out sessions
        timed_out_sessions = game_engine.check_turn_timeouts()

        logger.info(f"Found {len(timed_out_sessions)} timed out sessions")

        if dry_run:
            return {
                "summary": {
                    "type": "timeout_check_dry_run",
                    "timed_out_sessions": len(timed_out_sessions),
                    "would_process": min(len(timed_out_sessions), max_sessions),
                },
                "sessions": timed_out_sessions[:max_sessions],
            }

        # Process timeouts
        results = process_timeouts(timed_out_sessions[:max_sessions])

        return {
            "summary": {
                "type": "timeout_processing",
                "processed": len(results["processed"]),
                "errors": len(results["errors"]),
                "reminders_sent": len(results["reminders_sent"]),
                "sessions_paused": len(results["sessions_paused"]),
            },
            "details": results,
        }

    except Exception as e:
        logger.error(f"Error in timeout processing: {e}")
        return {"error": str(e)}


def process_health_check(options: dict[str, Any]) -> dict[str, Any]:
    """Process session health check and maintenance."""
    try:
        max_sessions = options.get("max_sessions", 500)
        cleanup_old = options.get("cleanup_old_sessions", False)
        dry_run = options.get("dry_run", False)

        # Get all active sessions for health check
        active_sessions = storage.get_active_sessions()

        health_results: dict[str, list[Any]] = {
            "healthy_sessions": [],
            "attention_needed": [],
            "cleaned_up": [],
            "errors": [],
        }

        for session in active_sessions[:max_sessions]:
            try:
                session_id = session["session_id"]
                health_info = check_session_health(session_id)

                if "error" in health_info:
                    health_results["errors"].append(health_info)
                elif health_info.get("needs_attention"):
                    health_results["attention_needed"].append(health_info)
                else:
                    health_results["healthy_sessions"].append(health_info)

                # Cleanup old completed sessions if requested
                if cleanup_old and session.get("status") == "completed":
                    from datetime import datetime, timedelta

                    created_at = session.get("created_at")
                    if created_at:
                        created_time = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                        age = datetime.now(UTC) - created_time

                        # Archive sessions older than 30 days
                        if age > timedelta(days=30) and not dry_run:
                            # In production, you might move to cold storage or delete
                            logger.info(
                                f"Session {session_id} marked for archival (age: {age.days} days)"
                            )
                            health_results["cleaned_up"].append(session_id)

            except Exception as e:
                logger.error(
                    f"Error checking health for session {session.get('session_id')}: {e}"
                )
                health_results["errors"].append(
                    {"session_id": session.get("session_id"), "error": str(e)}
                )

        return {
            "summary": {
                "type": "health_check",
                "total_sessions": len(active_sessions),
                "healthy": len(health_results["healthy_sessions"]),
                "need_attention": len(health_results["attention_needed"]),
                "cleaned_up": len(health_results["cleaned_up"]),
                "errors": len(health_results["errors"]),
            },
            "details": health_results,
        }

    except Exception as e:
        logger.error(f"Error in health check: {e}")
        return {"error": str(e)}


def process_session_backups(options: dict[str, Any]) -> dict[str, Any]:
    """Process session state backups."""
    try:
        from game_state import GameStateManager

        max_sessions = options.get("max_sessions", 1000)
        dry_run = options.get("dry_run", False)

        # Get sessions that need backup
        active_sessions = storage.get_active_sessions()

        backup_results: dict[str, list[Any]] = {
            "backed_up": [],
            "skipped": [],
            "errors": [],
        }

        game_state_manager = GameStateManager(storage)

        for session in active_sessions[:max_sessions]:
            try:
                session_id = session["session_id"]

                if dry_run:
                    backup_results["skipped"].append(session_id)
                    continue

                # Create backup
                backup_success = game_state_manager.backup_session_state(session_id)

                if backup_success:
                    backup_results["backed_up"].append(session_id)
                    logger.info(f"Backed up session {session_id}")
                else:
                    backup_results["errors"].append(
                        {"session_id": session_id, "error": "Backup failed"}
                    )

            except Exception as e:
                logger.error(
                    f"Error backing up session {session.get('session_id')}: {e}"
                )
                backup_results["errors"].append(
                    {"session_id": session.get("session_id"), "error": str(e)}
                )

        return {
            "summary": {
                "type": "session_backup",
                "backed_up": len(backup_results["backed_up"]),
                "skipped": len(backup_results["skipped"]),
                "errors": len(backup_results["errors"]),
            },
            "details": backup_results,
        }

    except Exception as e:
        logger.error(f"Error in backup processing: {e}")
        return {"error": str(e)}


def process_reminder_sending(options: dict[str, Any]) -> dict[str, Any]:
    """Send gentle reminders to inactive players."""
    try:
        max_sessions = options.get("max_sessions", 200)
        reminder_threshold = options.get("reminder_threshold_hours", 12)
        dry_run = options.get("dry_run", False)

        from datetime import datetime, timedelta

        # Get sessions that might need reminders
        active_sessions = storage.get_active_sessions()

        reminder_results: dict[str, list[Any]] = {
            "reminders_sent": [],
            "no_reminder_needed": [],
            "errors": [],
        }

        cutoff_time = datetime.now(UTC) - timedelta(hours=reminder_threshold)

        for session in active_sessions[:max_sessions]:
            try:
                session_id = session["session_id"]

                # Check if session needs a reminder
                last_activity = session.get("last_activity") or session.get(
                    "updated_at"
                )
                if not last_activity:
                    continue

                last_activity_time = datetime.fromisoformat(
                    last_activity.replace("Z", "+00:00")
                )

                # Only send reminders for sessions inactive beyond threshold
                if last_activity_time > cutoff_time:
                    reminder_results["no_reminder_needed"].append(session_id)
                    continue

                # Check if session is waiting for players
                if session.get("status") != "waiting_for_players":
                    reminder_results["no_reminder_needed"].append(session_id)
                    continue

                waiting_for = session.get("waiting_for", [])
                if not waiting_for:
                    reminder_results["no_reminder_needed"].append(session_id)
                    continue

                if dry_run:
                    reminder_results["reminders_sent"].append(
                        {
                            "session_id": session_id,
                            "would_remind": waiting_for,
                            "dry_run": True,
                        }
                    )
                    continue

                # Send reminders to inactive players
                session_info = {
                    "session_id": session_id,
                    "game_type": session.get("game_type"),
                    "waiting_for": waiting_for,
                    "turn_count": session.get("turn_count", 0),
                    "last_activity": last_activity,
                }

                send_gentle_reminders(session_info)

                reminder_results["reminders_sent"].append(
                    {"session_id": session_id, "reminded_players": waiting_for}
                )

            except Exception as e:
                logger.error(
                    f"Error processing reminders for session {session.get('session_id')}: {e}"
                )
                reminder_results["errors"].append(
                    {"session_id": session.get("session_id"), "error": str(e)}
                )

        return {
            "summary": {
                "type": "reminder_processing",
                "reminders_sent": len(reminder_results["reminders_sent"]),
                "no_reminder_needed": len(reminder_results["no_reminder_needed"]),
                "errors": len(reminder_results["errors"]),
            },
            "details": reminder_results,
        }

    except Exception as e:
        logger.error(f"Error in reminder processing: {e}")
        return {"error": str(e)}


def send_gentle_reminders(session_info: dict[str, Any]) -> None:
    """Send gentle reminders (different from timeout reminders)."""
    session_id = session_info["session_id"]
    game_type = session_info["game_type"]
    waiting_for = session_info.get("waiting_for", [])

    for player_email in waiting_for:
        try:
            subject = f"[Gentle Reminder] Your {game_type.title()} Adventure Awaits"

            if game_type == "intimacy":
                body = f"""Dear Partner,

This is a gentle reminder that your couples therapy session is ready for your next response.

**Session Details:**
- Session ID: {session_id}
- Current Turn: {session_info.get("turn_count", 0)}
- Your partner and therapist are ready to continue

**No Pressure:**
Take your time - there's no rush. We just wanted to make sure you didn't miss the opportunity to continue your therapeutic journey.

When you're ready, simply reply to your most recent session email.

Warmly,
Dr. Alex Chen, LMFT
Session: {session_id}"""

            else:  # dungeon
                body = f"""Fellow Adventurer,

Your epic adventure is ready for your next move!

**Adventure Status:**
- Session ID: {session_id}
- Current Turn: {session_info.get("turn_count", 0)}
- Your party is ready to continue the quest

**The Adventure Awaits:**
No pressure at all - adventures are meant to be enjoyed at your own pace. We just wanted to let you know that exciting developments await your character's next action.

Ready to continue? Reply to your most recent adventure email.

Your Dungeon Master
Session: {session_id}"""

            send_email(player_email, subject, body, session_id, game_type)
            logger.info(
                f"Sent gentle reminder to {player_email} for session {session_id}"
            )

        except Exception as e:
            logger.error(f"Failed to send gentle reminder to {player_email}: {e}")
