"""
AWS Lambda handler for GPT Therapy email processing.

This function processes incoming emails from SES and orchestrates
the turn-based AI therapy/storytelling system.
"""

import json
import logging
import os
from typing import Any, Dict, Optional

import boto3
from botocore.exceptions import ClientError

from storage import StorageManager, extract_session_id_from_email
from ai_agent import AIAgent

# Configure logging
logger = logging.getLogger()
logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# AWS clients
s3_client = boto3.client("s3")
ses_client = boto3.client("ses", region_name=os.environ.get('SES_REGION', 'ap-southeast-2'))
bedrock_client = boto3.client("bedrock-runtime")

# Storage manager and AI agent
storage = StorageManager()
ai_agent = AIAgent()


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Main Lambda handler for processing SES email events.
    
    Args:
        event: SES event data containing email information
        context: Lambda execution context
        
    Returns:
        Response dictionary with status and body
    """
    try:
        logger.info(f"Received event: {json.dumps(event, default=str)}")
        
        # Process SES records
        for record in event.get("Records", []):
            if record.get("eventSource") == "aws:ses":
                process_ses_email(record)
        
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Email processed successfully"})
        }
        
    except Exception as e:
        logger.error(f"Error processing email: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error"})
        }


def process_ses_email(record: Dict[str, Any]) -> None:
    """
    Process a single SES email record.
    
    Args:
        record: SES record containing email data
    """
    try:
        # Extract email metadata
        ses_data = record["ses"]
        mail = ses_data["mail"]
        receipt = ses_data["receipt"]
        
        # Log email details
        logger.info(f"Processing email from: {mail['commonHeaders']['from']}")
        logger.info(f"Subject: {mail['commonHeaders']['subject']}")
        logger.info(f"Recipients: {mail['commonHeaders']['to']}")
        
        # Extract session info from recipient
        recipients = receipt["recipients"]
        session_info = extract_session_info(recipients)
        
        if session_info:
            # Process game/therapy session
            process_session_turn(session_info, mail, receipt)
        else:
            # Handle new session initialization
            initialize_new_session(mail, receipt)
            
    except Exception as e:
        logger.error(f"Error processing SES record: {str(e)}", exc_info=True)
        raise


def extract_session_info(recipients: list) -> Optional[Dict[str, Any]]:
    """
    Extract session information from email recipients.
    
    Args:
        recipients: List of recipient email addresses
        
    Returns:
        Session info dictionary or None if no session found
    """
    for recipient in recipients:
        session_id = extract_session_id_from_email(recipient)
        if session_id:
            # Extract game type from domain
            domain = recipient.split("@", 1)[1]
            game_type = domain.split(".")[0]  # Extract game type from subdomain
            
            return {
                "session_id": session_id,
                "game_type": game_type,
                "domain": domain,
                "recipient": recipient
            }
    
    return None


def process_session_turn(session_info: Dict[str, Any], mail: Dict[str, Any], receipt: Dict[str, Any]) -> None:
    """
    Process a turn in an existing game/therapy session.
    
    Args:
        session_info: Session metadata
        mail: Email metadata
        receipt: SES receipt data
    """
    session_id = session_info['session_id']
    player_email = mail["commonHeaders"]["from"][0]
    
    logger.info(f"Processing turn for session {session_id} from {player_email}")
    
    try:
        # 1. Retrieve session state from storage
        session = storage.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            send_error_email(player_email, "Session not found")
            return
        
        # 2. Parse player input from email
        email_content = {
            "from": player_email,
            "subject": mail["commonHeaders"]["subject"],
            "timestamp": mail["timestamp"],
            "message_id": mail["messageId"],
            "body": extract_email_body(mail)  # Extract actual email content
        }
        
        # Archive the email
        storage.archive_email(session_id, email_content)
        
        # 3. Save the turn
        current_turn = session.get('turn_count', 0) + 1
        turn_data = {
            "email_content": email_content,
            "status": "received"
        }
        
        storage.save_turn(session_id, current_turn, player_email, turn_data)
        
        # 4. Get turn history for context
        turn_history = storage.get_session_turns(session_id, limit=10)
        
        # 5. Generate AI response
        session_context = {
            **session,
            "current_player": player_email,
            "current_turn": current_turn
        }
        
        ai_response = ai_agent.generate_response(
            game_type=session["game_type"],
            session_context=session_context,
            player_input=email_content["body"],
            turn_history=turn_history
        )
        
        # 6. Update session status
        storage.update_session(session_id, {
            "status": "active",
            "last_activity": email_content["timestamp"]
        })
        
        # 7. Send AI response email
        response_address = f"{session_id}@{session['game_type']}.promptexecution.com"
        send_response_email(
            to_address=player_email,
            from_address=response_address,
            subject=f"Re: {mail['commonHeaders']['subject']}",
            body=ai_response
        )
        
        logger.info(f"Successfully processed turn {current_turn} for session {session_id}")
        
    except Exception as e:
        logger.error(f"Error processing turn for session {session_id}: {str(e)}")
        send_error_email(player_email, "Error processing your turn. Please try again.")
        raise


def initialize_new_session(mail: Dict[str, Any], receipt: Dict[str, Any]) -> None:
    """
    Initialize a new game/therapy session.
    
    Args:
        mail: Email metadata  
        receipt: SES receipt data
    """
    player_email = mail["commonHeaders"]["from"][0]
    recipients = receipt["recipients"]
    
    logger.info(f"Initializing new session for {player_email}")
    
    try:
        # 1. Determine game type from recipient domain
        game_type = "dungeon"  # Default, will be improved
        for recipient in recipients:
            if "@" in recipient:
                domain = recipient.split("@", 1)[1]
                potential_game_type = domain.split(".")[0]
                if potential_game_type in ["dungeon", "intimacy"]:
                    game_type = potential_game_type
                    break
        
        # 2. Create new session
        session_data = {
            "game_type": game_type,
            "max_players": 4 if game_type == "dungeon" else 2,
            "status": "initializing"
        }
        
        session_id = storage.create_session(game_type, player_email, session_data)
        
        # 3. Create/update player profile
        player_data = {
            "name": player_email.split("@")[0],  # Default name from email
            "last_activity": mail["timestamp"]
        }
        storage.create_or_update_player(player_email, player_data)
        
        # 4. Generate AI initialization response
        ai_response = ai_agent.generate_initialization_response(
            game_type=game_type,
            player_email=player_email,
            session_id=session_id
        )
        
        # 5. Send initialization email
        response_address = f"{session_id}@{game_type}.promptexecution.com"
        
        send_response_email(
            to_address=player_email,
            from_address=response_address,
            subject=f"Welcome to {game_type.title()} Therapy - Session {session_id}",
            body=ai_response
        )
        
        logger.info(f"Successfully initialized session {session_id} for {player_email}")
        
    except Exception as e:
        logger.error(f"Error initializing session for {player_email}: {str(e)}")
        send_error_email(player_email, "Error creating your session. Please try again.")
        raise


def send_response_email(to_address: str, subject: str, body: str, from_address: str = None) -> None:
    """
    Send a response email via SES.
    
    Args:
        to_address: Recipient email address
        subject: Email subject
        body: Email body content
        from_address: Optional sender address (defaults to noreply)
    """
    if not from_address:
        from_address = "noreply@promptexecution.com"
    
    try:
        response = ses_client.send_email(
            Source=from_address,
            Destination={"ToAddresses": [to_address]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": body}}
            }
        )
        logger.info(f"Email sent successfully to {to_address}: {response['MessageId']}")
        
    except ClientError as e:
        logger.error(f"Error sending email to {to_address}: {e.response['Error']['Message']}")
        raise


def extract_email_body(mail: Dict[str, Any]) -> str:
    """
    Extract the email body content from SES mail data.
    
    Args:
        mail: SES mail object
        
    Returns:
        Email body text
    """
    try:
        # Try to get the body from common headers first
        if 'content' in mail:
            return str(mail['content'])
        
        # For SES, we might need to fetch the actual email content from S3
        # This is a simplified version - in practice, you'd fetch from S3
        subject = mail.get('commonHeaders', {}).get('subject', '')
        
        # Return a placeholder that indicates we need to fetch the full content
        return f"[Email content for subject: {subject}]"
        
    except Exception as e:
        logger.error(f"Error extracting email body: {e}")
        return "[Unable to extract email content]"


def send_error_email(to_address: str, error_message: str) -> None:
    """
    Send an error notification email.
    
    Args:
        to_address: Recipient email address
        error_message: Error message to include
    """
    subject = "GPT Therapy - Error Processing Your Request"
    body = f"""
Sorry, we encountered an error processing your request:

{error_message}

Please try again or contact support if the problem persists.

Best regards,
GPT Therapy Team
"""
    
    try:
        send_response_email(to_address, subject, body)
    except Exception as e:
        logger.error(f"Failed to send error email to {to_address}: {str(e)}")
        # Don't re-raise since this is a fallback mechanism