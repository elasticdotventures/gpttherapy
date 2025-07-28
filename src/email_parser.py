"""
Improved email parsing using Pydantic models and proper validation.

Replaces manual validation with automatic Pydantic validation and uses
established libraries for email processing.
"""

import email
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

from .datetime_utils import parse_email_date, utc_now_iso, datetime_to_instant

from pydantic import ValidationError
from email_validator import EmailNotValidError

try:
    from .error_handler import ErrorType, GPTTherapyError
    from .email_models import (
        ParsedEmail, EmailAttachment, EmailContent, EmailProcessingResult,
        GameEmailSchema, TherapyEmailSchema
    )
    from .logging_config import get_logger
    from .settings import settings
except ImportError:
    from error_handler import ErrorType, GPTTherapyError
    from email_models import (
        ParsedEmail, EmailAttachment, EmailContent, EmailProcessingResult,
        GameEmailSchema, TherapyEmailSchema
    )
    from logging_config import get_logger
    from settings import settings

logger = get_logger(__name__)


# ParsedEmail model is now imported from email_models.py


class EmailValidationError(GPTTherapyError):
    """Email validation specific errors."""

    def __init__(self, message: str, email_data: Dict[str, Any] = None, validation_errors: List[str] = None):
        super().__init__(message, ErrorType.VALIDATION_ERROR)
        self.email_data = email_data
        self.validation_errors = validation_errors or []


class EmailParser:
    """Improved email parsing using Pydantic models and proper validation."""

    def __init__(self):
        # Reply detection patterns
        self.reply_indicators = [
            r"^re:\s*", r"^fwd?:\s*", r"^fw:\s*", r"^\[.*\]"
        ]

        # Automated email patterns  
        self.automated_patterns = [
            r"noreply@", r"no-reply@", r"donotreply@",
            r"automated@", r"system@", r"daemon@", r"mailer-daemon@"
        ]

        # Content extraction patterns
        self.quote_patterns = [
            r"^>.*", r"^On .* wrote:", r"^From:.*",
            r"-----Original Message-----", r"_{10,}"
        ]
        
        # Game action keywords
        self.action_keywords = {
            'movement': ['go', 'move', 'walk', 'run', 'travel', 'head'],
            'combat': ['attack', 'fight', 'defend', 'block', 'strike'],
            'magic': ['cast', 'spell', 'enchant', 'summon', 'invoke'],
            'interaction': ['talk', 'speak', 'say', 'ask', 'tell'],
            'investigation': ['search', 'examine', 'look', 'inspect', 'investigate'],
            'manipulation': ['take', 'grab', 'pick', 'use', 'open', 'close']
        }
        
        # Emotional indicators for therapy
        self.emotion_keywords = {
            'positive': ['happy', 'excited', 'grateful', 'hopeful', 'calm', 'peaceful'],
            'negative': ['sad', 'angry', 'frustrated', 'worried', 'anxious', 'stressed'],
            'neutral': ['confused', 'curious', 'uncertain', 'thoughtful']
        }

    def parse_ses_email(self, ses_record: Dict[str, Any]) -> EmailProcessingResult:
        """
        Parse an email from SES record format using Pydantic validation.

        Args:
            ses_record: SES record containing email data

        Returns:
            EmailProcessingResult with parsed and validated email
        """
        start_time = time.time() * 1000
        result = EmailProcessingResult(
            success=False,
            processing_time_ms=0
        )
        
        try:
            # Validate SES record structure
            if "ses" not in ses_record:
                result.add_error("Missing 'ses' key in SES record")
                return result

            mail_data = ses_record["ses"].get("mail", {})
            if not mail_data:
                result.add_error("Missing mail data in SES record")
                return result

            # Extract email data with better error handling
            email_data = self._extract_ses_email_data(mail_data)
            
            # Parse timestamp properly
            if 'timestamp' in mail_data:
                try:
                    # Use proper datetime parsing
                    parsed_instant = parse_email_date(mail_data['timestamp'])
                    email_data['timestamp'] = parsed_instant.py_datetime()
                except (ValueError, AttributeError):
                    email_data['timestamp'] = datetime_to_instant(datetime.now()).py_datetime()
            else:
                email_data['timestamp'] = datetime_to_instant(datetime.now()).py_datetime()
            
            # Create and validate ParsedEmail using Pydantic
            try:
                parsed_email = ParsedEmail.model_validate(email_data)
                
                # Calculate spam score and extract content
                parsed_email.calculate_spam_score()
                parsed_email.extracted_content = self._extract_email_content_analysis(parsed_email)
                
                # Check if valid for processing
                is_valid, validation_errors = parsed_email.is_valid_for_processing()
                if not is_valid:
                    for error in validation_errors:
                        result.add_warning(error)
                
                result.parsed_email = parsed_email
                result.session_id = parsed_email.extract_session_id()
                result.success = True
                
            except ValidationError as e:
                result.add_error(f"Email validation failed: {str(e)}")
                for error in e.errors():
                    result.add_error(f"{error['loc']}: {error['msg']}")
                
        except Exception as e:
            result.add_error(f"Failed to parse SES email: {str(e)}")
            logger.error("SES email parsing failed", 
                        error=str(e), 
                        ses_record_keys=list(ses_record.keys()),
                        exc_info=True)
        
        finally:
            result.processing_time_ms = int((time.time() * 1000) - start_time)
            
        return result

    def parse_raw_email(self, raw_email: str) -> EmailProcessingResult:
        """
        Parse a raw email message string using Pydantic validation.

        Args:
            raw_email: Raw email content as string

        Returns:
            EmailProcessingResult with parsed and validated email
        """
        start_time = time.time() * 1000
        result = EmailProcessingResult(success=False, processing_time_ms=0)
        
        try:
            # Parse email using standard library
            msg = email.message_from_string(raw_email)
            
            # Extract email data
            email_data = self._extract_raw_email_data(msg)
            
            # Create and validate ParsedEmail using Pydantic
            try:
                parsed_email = ParsedEmail.model_validate(email_data)
                
                # Enhance with content analysis
                parsed_email.calculate_spam_score()
                parsed_email.extracted_content = self._extract_email_content_analysis(parsed_email)
                
                # Validate for processing
                is_valid, validation_errors = parsed_email.is_valid_for_processing()
                if not is_valid:
                    for error in validation_errors:
                        result.add_warning(error)
                
                result.parsed_email = parsed_email
                result.session_id = parsed_email.extract_session_id()
                result.success = True
                
            except ValidationError as e:
                result.add_error(f"Email validation failed: {str(e)}")
                for error in e.errors():
                    result.add_error(f"{error['loc']}: {error['msg']}")
                
        except Exception as e:
            result.add_error(f"Failed to parse raw email: {str(e)}")
            logger.error("Raw email parsing failed", error=str(e), exc_info=True)
        
        finally:
            result.processing_time_ms = int((time.time() * 1000) - start_time)
            
        return result

    def validate_for_game_processing(self, parsed_email: ParsedEmail) -> EmailProcessingResult:
        """
        Validate email specifically for game processing using GameEmailSchema.
        
        Args:
            parsed_email: ParsedEmail to validate
            
        Returns:
            EmailProcessingResult with game-specific validation
        """
        result = EmailProcessingResult(success=False, processing_time_ms=0)
        start_time = time.time() * 1000
        
        try:
            # Convert to game-specific schema
            game_email = GameEmailSchema.model_validate(parsed_email.model_dump())
            result.parsed_email = game_email
            result.success = True
            
            # Additional game-specific checks
            if game_email.extracted_content:
                if not game_email.extracted_content.action_keywords:
                    result.add_warning("No clear game actions detected")
                    
        except ValidationError as e:
            result.add_error(f"Game validation failed: {str(e)}")
            
        finally:
            result.processing_time_ms = int((time.time() * 1000) - start_time)
            
        return result
        
    def validate_for_therapy_processing(self, parsed_email: ParsedEmail) -> EmailProcessingResult:
        """
        Validate email specifically for therapy processing using TherapyEmailSchema.
        
        Args:
            parsed_email: ParsedEmail to validate
            
        Returns:
            EmailProcessingResult with therapy-specific validation
        """
        result = EmailProcessingResult(success=False, processing_time_ms=0)
        start_time = time.time() * 1000
        
        try:
            # Convert to therapy-specific schema
            therapy_email = TherapyEmailSchema.model_validate(parsed_email.model_dump())
            result.parsed_email = therapy_email
            result.success = True
            
            # Additional therapy-specific checks
            if therapy_email.extracted_content:
                if not therapy_email.extracted_content.emotional_indicators:
                    result.add_warning("No emotional indicators detected")
                    
        except ValidationError as e:
            result.add_error(f"Therapy validation failed: {str(e)}")
            
        finally:
            result.processing_time_ms = int((time.time() * 1000) - start_time)
            
        return result

    # New helper methods for improved parsing
    
    def _extract_ses_email_data(self, mail_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract email data from SES mail data structure."""
        common_headers = mail_data.get("commonHeaders", {})
        
        # Extract addresses
        from_address = self._extract_single_address(common_headers.get("from", []))
        to_addresses = common_headers.get("to", [])
        cc_addresses = common_headers.get("cc", [])
        
        # Extract content (placeholder - would fetch from S3 in real implementation)
        body_text, body_html = self._extract_email_content_from_s3(mail_data)
        
        # Extract headers
        headers = {}
        for header in mail_data.get("headers", []):
            headers[header["name"].lower()] = header["value"]
        
        # Determine reply status
        subject = common_headers.get("subject", "")
        is_reply = self._is_reply_email(subject, headers)
        
        return {
            "from_address": from_address,
            "to_addresses": to_addresses,
            "cc_addresses": cc_addresses,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "message_id": mail_data.get("messageId", ""),
            "headers": headers,
            "is_reply": is_reply,
            "reply_to_message_id": headers.get("in-reply-to"),
            "thread_id": headers.get("references", "").split()[-1] if headers.get("references") else None,
            "attachments": self._extract_attachments_from_ses(mail_data),
            "is_automated": self._is_automated_email(from_address)
        }
    
    def _extract_raw_email_data(self, msg: email.message.Message) -> Dict[str, Any]:
        """Extract email data from raw email message."""
        # Extract addresses
        from_address = self._extract_single_address([msg.get("From", "")])
        to_addresses = self._parse_address_list(msg.get("To", ""))
        cc_addresses = self._parse_address_list(msg.get("Cc", ""))
        
        # Extract content
        body_text, body_html = self._extract_message_content(msg)
        
        # Extract headers
        headers = {k.lower(): v for k, v in msg.items()}
        
        # Parse timestamp
        timestamp = self._parse_email_date(msg.get("Date", ""))
        
        # Determine reply status
        subject = msg.get("Subject", "")
        is_reply = self._is_reply_email(subject, headers)
        
        return {
            "from_address": from_address,
            "to_addresses": to_addresses,
            "cc_addresses": cc_addresses,
            "subject": subject,
            "body_text": body_text,
            "body_html": body_html,
            "message_id": msg.get("Message-ID", ""),
            "timestamp": timestamp,
            "headers": headers,
            "is_reply": is_reply,
            "reply_to_message_id": headers.get("in-reply-to"),
            "thread_id": headers.get("references", "").split()[-1] if headers.get("references") else None,
            "attachments": self._extract_message_attachments(msg),
            "is_automated": self._is_automated_email(from_address)
        }
    
    def _extract_email_content_analysis(self, parsed_email: ParsedEmail) -> EmailContent:
        """Extract and analyze email content for game/therapy processing."""
        # Clean the body text
        clean_body = self._clean_email_body(parsed_email.body_text)
        
        # Separate new content from quoted text
        body_parts = self._separate_quoted_text(clean_body)
        
        # Extract keywords and indicators
        action_keywords = self._extract_action_keywords(body_parts["new_content"])
        emotional_indicators = self._extract_emotional_indicators(body_parts["new_content"])
        questions = self._extract_questions(body_parts["new_content"])
        
        return EmailContent(
            raw_content=parsed_email.body_text,
            clean_content=clean_body,
            new_content=body_parts["new_content"],
            quoted_content=body_parts["quoted_content"],
            action_keywords=action_keywords,
            emotional_indicators=emotional_indicators,
            questions=questions,
            word_count=len(body_parts["new_content"].split()),
            contains_response=len(body_parts["new_content"].strip()) > 10
        )

    def _extract_single_address(self, address_list: Union[List[str], str]) -> str:
        """Extract single email address from list with better parsing."""
        if not address_list:
            return ""
        
        if isinstance(address_list, list):
            if not address_list:
                return ""
            address = address_list[0]
        else:
            address = str(address_list)
        
        # Extract email from "Name <email@domain.com>" format
        email_match = re.search(r'<([^>]+)>', address)
        if email_match:
            return email_match.group(1).strip()
        
        # If no angle brackets, assume the whole string is an email
        return address.strip()

    def _parse_address_list(self, address_string: str) -> List[str]:
        """Parse comma-separated address list with better handling."""
        if not address_string:
            return []
        
        addresses = []
        # Split by comma, but be careful of commas within quoted names
        for addr in re.split(r',(?![^<]*>)', address_string):
            addr = addr.strip()
            if addr:
                # Extract email from "Name <email@domain.com>" format
                email_match = re.search(r'<([^>]+)>', addr)
                if email_match:
                    addresses.append(email_match.group(1).strip())
                else:
                    addresses.append(addr)
        
        return addresses

    def _parse_email_date(self, date_string: str) -> datetime:
        """Parse email date to datetime object."""
        parsed_instant = parse_email_date(date_string)
        return parsed_instant.py_datetime()

    def _extract_email_content_from_s3(
        self, mail_data: Dict[str, Any]
    ) -> Tuple[str, Optional[str]]:
        """Extract text and HTML content from SES mail data (S3 fetch)."""
        # In real implementation, this would fetch the email content from S3
        # using the source key provided in the SES record
        
        # For now, return placeholder content that indicates S3 fetch needed
        return "[Email content would be fetched from S3 using mail source]", None

    def _extract_message_content(
        self, msg: email.message.Message
    ) -> Tuple[str, Optional[str]]:
        """Extract text and HTML content from email message with better encoding handling."""
        body_text = ""
        body_html = None

        if msg.is_multipart():
            for part in msg.walk():
                # Skip container parts
                if part.is_multipart():
                    continue
                    
                content_type = part.get_content_type()
                charset = part.get_content_charset() or 'utf-8'
                
                try:
                    if content_type == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            decoded_text = payload.decode(charset, errors="ignore")
                            body_text += decoded_text
                    elif content_type == "text/html":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_html = payload.decode(charset, errors="ignore")
                except (UnicodeDecodeError, LookupError) as e:
                    logger.warning(f"Failed to decode email part: {e}")
                    # Fallback to utf-8 with error handling
                    payload = part.get_payload(decode=True)
                    if payload:
                        try:
                            decoded_text = payload.decode('utf-8', errors='replace')
                            if content_type == "text/plain":
                                body_text += decoded_text
                            elif content_type == "text/html":
                                body_html = decoded_text
                        except Exception:
                            pass  # Skip malformed content
        else:
            # Single part message
            try:
                charset = msg.get_content_charset() or 'utf-8'
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode(charset, errors="ignore")
            except (UnicodeDecodeError, LookupError):
                # Fallback
                payload = msg.get_payload(decode=True)
                if payload:
                    body_text = payload.decode('utf-8', errors='replace')

        return body_text.strip(), body_html

    def _extract_attachments_from_ses(self, mail_data: Dict[str, Any]) -> List[EmailAttachment]:
        """Extract attachment information from SES data."""
        # In real implementation, would parse attachment metadata from SES
        # and fetch attachment content from S3
        return []

    def _extract_message_attachments(
        self, msg: email.message.Message
    ) -> List[EmailAttachment]:
        """Extract attachments from email message."""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                disposition = part.get_content_disposition()
                if disposition == "attachment":
                    filename = part.get_filename()
                    if filename:
                        payload = part.get_payload(decode=True) or b""
                        attachments.append(
                            EmailAttachment(
                                filename=filename,
                                content_type=part.get_content_type(),
                                size=len(payload),
                                content_id=part.get("Content-ID"),
                                is_inline=False
                            )
                        )
                elif disposition == "inline":
                    filename = part.get_filename()
                    if filename:
                        payload = part.get_payload(decode=True) or b""
                        attachments.append(
                            EmailAttachment(
                                filename=filename,
                                content_type=part.get_content_type(),
                                size=len(payload),
                                content_id=part.get("Content-ID"),
                                is_inline=True
                            )
                        )

        return attachments

    def _is_reply_email(self, subject: str, headers: dict[str, str]) -> bool:
        """Determine if email is a reply."""
        # Check subject line
        subject_lower = subject.lower()
        for pattern in self.reply_indicators:
            if re.match(pattern, subject_lower):
                return True

        # Check headers
        return bool(headers.get("in-reply-to") or headers.get("references"))

    # Email validation is now handled by Pydantic EmailStr and email-validator

    def _is_automated_email(self, email_address: str) -> bool:
        """Check if email appears to be automated."""
        email_lower = email_address.lower()
        return any(pattern in email_lower for pattern in self.automated_patterns)

    # Spam score calculation is now handled by ParsedEmail.calculate_spam_score()

    def _clean_email_body(self, body_text: str) -> str:
        """Clean email body text."""
        # Remove common email signatures first (before collapsing whitespace)
        signature_patterns = [
            r"--\s*\n.*",
            r"Sent from my \w+",
            r"Get Outlook for \w+",
        ]

        cleaned = body_text.strip()
        for pattern in signature_patterns:
            cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

        # Clean up excessive whitespace, but preserve line breaks for quote detection
        # Replace multiple spaces with single space, but keep line breaks
        cleaned = re.sub(
            r"[ \t]+", " ", cleaned
        )  # Multiple spaces/tabs to single space
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)  # Multiple newlines to max 2

        return cleaned.strip()

    def _separate_quoted_text(self, body_text: str) -> Dict[str, str]:
        """Separate new content from quoted text with improved detection."""
        lines = body_text.split("\n")
        new_lines = []
        quoted_lines = []
        in_quote = False

        for line in lines:
            line_stripped = line.strip()

            # Check if this line starts a quote using improved patterns
            is_quote_line = any(
                re.match(pattern, line_stripped, re.IGNORECASE)
                for pattern in self.quote_patterns
            )

            # Also check for lines that start with > (common quote indicator)
            if is_quote_line or line.startswith(">"):
                in_quote = True
            
            # Check for end of quoted section (empty lines can break quotes)
            elif in_quote and not line_stripped:
                # Empty line might end quote, but check next few lines
                pass

            if in_quote:
                quoted_lines.append(line)
            else:
                new_lines.append(line)

        return {
            "new_content": "\n".join(new_lines).strip(),
            "quoted_content": "\n".join(quoted_lines).strip(),
        }

    def _extract_action_keywords(self, text: str) -> List[str]:
        """Extract action keywords for dungeon games using improved categorization."""
        text_lower = text.lower()
        found_actions = []
        
        # Use categorized keywords for better action detection
        for category, keywords in self.action_keywords.items():
            for keyword in keywords:
                # Use word boundaries to avoid partial matches
                if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
                    found_actions.append(keyword)
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(found_actions))

    def _extract_emotional_indicators(self, text: str) -> List[str]:
        """Extract emotional indicators for therapy sessions using improved categorization."""
        text_lower = text.lower()
        found_emotions = []
        
        # Use categorized emotion keywords
        for category, keywords in self.emotion_keywords.items():
            for keyword in keywords:
                # Use word boundaries for better matching
                if re.search(rf'\b{re.escape(keyword)}\b', text_lower):
                    found_emotions.append(keyword)
        
        # Remove duplicates while preserving order
        return list(dict.fromkeys(found_emotions))

    def _extract_questions(self, text: str) -> List[str]:
        """Extract questions from text with improved parsing."""
        # Find sentences ending with question marks, including multiline
        questions = re.findall(r'[^.!\n]*\?', text, re.MULTILINE)
        
        # Clean and filter questions
        cleaned_questions = []
        for q in questions:
            cleaned = q.strip()
            # Filter out very short questions (likely false positives)
            if len(cleaned) > 5 and not cleaned.startswith('?'):
                cleaned_questions.append(cleaned)
        
        return cleaned_questions


# Updated convenience functions using new Pydantic-based parsing

def get_email_parser() -> EmailParser:
    """Get email parser instance."""
    return EmailParser()


def parse_ses_email(ses_record: Dict[str, Any]) -> EmailProcessingResult:
    """Convenience function to parse SES email with validation."""
    parser = get_email_parser()
    return parser.parse_ses_email(ses_record)


def parse_raw_email(raw_email: str) -> EmailProcessingResult:
    """Convenience function to parse raw email with validation."""
    parser = get_email_parser()
    return parser.parse_raw_email(raw_email)


def validate_email_for_game(parsed_email: ParsedEmail) -> EmailProcessingResult:
    """Convenience function to validate email for game processing."""
    parser = get_email_parser()
    return parser.validate_for_game_processing(parsed_email)


def validate_email_for_therapy(parsed_email: ParsedEmail) -> EmailProcessingResult:
    """Convenience function to validate email for therapy processing."""
    parser = get_email_parser()
    return parser.validate_for_therapy_processing(parsed_email)


def is_email_valid_for_processing(parsed_email: ParsedEmail) -> bool:
    """Quick check if email is valid for any type of processing."""
    is_valid, errors = parsed_email.is_valid_for_processing()
    
    if not is_valid:
        logger.warning("Email validation failed", 
                      errors=errors,
                      from_address=str(parsed_email.from_address),
                      subject=parsed_email.subject)
    
    return is_valid
