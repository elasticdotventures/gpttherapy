"""
Email parsing and validation utilities for GPT Therapy.

Handles parsing of incoming emails, content extraction, and validation.
"""

import re
import email
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dataclasses import dataclass

try:
    from .error_handler import GPTTherapyError, ErrorType, log_error
except ImportError:
    from error_handler import GPTTherapyError, ErrorType, log_error

logger = logging.getLogger(__name__)


@dataclass
class ParsedEmail:
    """Structured representation of a parsed email."""
    from_address: str
    to_addresses: List[str]
    cc_addresses: List[str]
    subject: str
    body_text: str
    body_html: Optional[str]
    message_id: str
    timestamp: str
    attachments: List[Dict[str, Any]]
    headers: Dict[str, str]
    is_reply: bool
    reply_to_message_id: Optional[str]
    thread_id: Optional[str]


class EmailValidationError(GPTTherapyError):
    """Email validation specific errors."""
    def __init__(self, message: str, email_data: Dict[str, Any] = None):
        super().__init__(message, ErrorType.VALIDATION_ERROR)
        self.email_data = email_data


class EmailParser:
    """Email parsing and validation utility."""
    
    def __init__(self):
        self.reply_indicators = [
            r'^re:\s*',
            r'^fwd?:\s*',
            r'^fw:\s*',
            r'^\[.*\]',  # Common thread indicators
        ]
        
        # Common patterns to identify automated emails
        self.automated_patterns = [
            r'noreply@',
            r'no-reply@',
            r'donotreply@',
            r'automated@',
            r'system@',
            r'daemon@'
        ]
        
        # Session ID validation pattern
        self.session_id_pattern = re.compile(r'^[a-zA-Z0-9\-_]{3,50}$')
    
    def parse_ses_email(self, ses_record: Dict[str, Any]) -> ParsedEmail:
        """
        Parse an email from SES record format.
        
        Args:
            ses_record: SES record containing email data
            
        Returns:
            ParsedEmail object
            
        Raises:
            EmailValidationError: If email cannot be parsed or is invalid
        """
        try:
            if 'ses' not in ses_record:
                raise ValueError("Missing 'ses' key in SES record")
            
            mail_data = ses_record['ses'].get('mail', {})
            receipt_data = ses_record['ses'].get('receipt', {})
            
            if not mail_data:
                raise ValueError("Missing mail data in SES record")
            
            common_headers = mail_data.get('commonHeaders', {})
            
            # Extract basic email information
            from_address = self._extract_single_address(common_headers.get('from', []))
            to_addresses = common_headers.get('to', [])
            cc_addresses = common_headers.get('cc', [])
            subject = common_headers.get('subject', '')
            message_id = mail_data.get('messageId', '')
            timestamp = mail_data.get('timestamp', datetime.now(timezone.utc).isoformat())
            
            # Parse email content (this would need S3 fetch in real implementation)
            body_text, body_html = self._extract_email_content(mail_data)
            
            # Extract headers
            headers = {}
            for header in mail_data.get('headers', []):
                headers[header['name'].lower()] = header['value']
            
            # Determine if this is a reply
            is_reply = self._is_reply_email(subject, headers)
            reply_to_message_id = headers.get('in-reply-to')
            thread_id = headers.get('references', '').split()[-1] if headers.get('references') else None
            
            # Extract attachments (if any)
            attachments = self._extract_attachments(mail_data)
            
            return ParsedEmail(
                from_address=from_address,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                message_id=message_id,
                timestamp=timestamp,
                attachments=attachments,
                headers=headers,
                is_reply=is_reply,
                reply_to_message_id=reply_to_message_id,
                thread_id=thread_id
            )
            
        except Exception as e:
            error_msg = f"Failed to parse SES email: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise EmailValidationError(error_msg, ses_record) from e
    
    def parse_raw_email(self, raw_email: str) -> ParsedEmail:
        """
        Parse a raw email message string.
        
        Args:
            raw_email: Raw email content as string
            
        Returns:
            ParsedEmail object
        """
        try:
            msg = email.message_from_string(raw_email)
            
            # Extract basic information
            from_address = self._extract_single_address([msg.get('From', '')])
            to_addresses = self._parse_address_list(msg.get('To', ''))
            cc_addresses = self._parse_address_list(msg.get('Cc', ''))
            subject = msg.get('Subject', '')
            message_id = msg.get('Message-ID', '')
            timestamp = self._parse_email_date(msg.get('Date', ''))
            
            # Extract body content
            body_text, body_html = self._extract_message_content(msg)
            
            # Extract headers
            headers = {k.lower(): v for k, v in msg.items()}
            
            # Determine reply status
            is_reply = self._is_reply_email(subject, headers)
            reply_to_message_id = headers.get('in-reply-to')
            thread_id = headers.get('references', '').split()[-1] if headers.get('references') else None
            
            # Extract attachments
            attachments = self._extract_message_attachments(msg)
            
            return ParsedEmail(
                from_address=from_address,
                to_addresses=to_addresses,
                cc_addresses=cc_addresses,
                subject=subject,
                body_text=body_text,
                body_html=body_html,
                message_id=message_id,
                timestamp=timestamp,
                attachments=attachments,
                headers=headers,
                is_reply=is_reply,
                reply_to_message_id=reply_to_message_id,
                thread_id=thread_id
            )
            
        except Exception as e:
            error_msg = f"Failed to parse raw email: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise EmailValidationError(error_msg) from e
    
    def validate_email(self, parsed_email: ParsedEmail) -> Tuple[bool, List[str]]:
        """
        Validate parsed email for GPT Therapy processing.
        
        Args:
            parsed_email: ParsedEmail object to validate
            
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []
        
        # Check required fields
        if not parsed_email.from_address:
            errors.append("Missing sender address")
        
        if not parsed_email.to_addresses:
            errors.append("Missing recipient addresses")
        
        if not parsed_email.body_text.strip():
            errors.append("Empty email body")
        
        # Validate email addresses
        if parsed_email.from_address and not self._is_valid_email(parsed_email.from_address):
            errors.append(f"Invalid sender email: {parsed_email.from_address}")
        
        for to_addr in parsed_email.to_addresses:
            if not self._is_valid_email(to_addr):
                errors.append(f"Invalid recipient email: {to_addr}")
        
        # Check for automated email patterns
        if self._is_automated_email(parsed_email.from_address):
            errors.append("Email appears to be automated/system generated")
        
        # Validate body content length
        if len(parsed_email.body_text) > 10000:  # 10KB limit
            errors.append("Email body too long (max 10KB)")
        
        # Check for spam indicators
        spam_score = self._calculate_spam_score(parsed_email)
        if spam_score > 7:  # Threshold for spam
            errors.append(f"Email appears to be spam (score: {spam_score})")
        
        return len(errors) == 0, errors
    
    def extract_game_content(self, parsed_email: ParsedEmail) -> Dict[str, Any]:
        """
        Extract game/therapy relevant content from email.
        
        Args:
            parsed_email: ParsedEmail to extract content from
            
        Returns:
            Dictionary with extracted game content
        """
        # Clean the body text
        clean_body = self._clean_email_body(parsed_email.body_text)
        
        # Extract quoted text (previous conversation)
        body_parts = self._separate_quoted_text(clean_body)
        
        # Extract action keywords for dungeon games
        action_keywords = self._extract_action_keywords(body_parts['new_content'])
        
        # Extract emotional content for therapy sessions
        emotional_indicators = self._extract_emotional_indicators(body_parts['new_content'])
        
        # Extract questions or requests
        questions = self._extract_questions(body_parts['new_content'])
        
        return {
            'raw_content': parsed_email.body_text,
            'clean_content': clean_body,
            'new_content': body_parts['new_content'],
            'quoted_content': body_parts['quoted_content'],
            'action_keywords': action_keywords,
            'emotional_indicators': emotional_indicators,
            'questions': questions,
            'word_count': len(body_parts['new_content'].split()),
            'contains_response': len(body_parts['new_content'].strip()) > 10
        }
    
    def _extract_single_address(self, address_list: List[str]) -> str:
        """Extract single email address from list."""
        if not address_list:
            return ""
        return address_list[0] if isinstance(address_list, list) else str(address_list)
    
    def _parse_address_list(self, address_string: str) -> List[str]:
        """Parse comma-separated address list."""
        if not address_string:
            return []
        return [addr.strip() for addr in address_string.split(',')]
    
    def _parse_email_date(self, date_string: str) -> str:
        """Parse email date to ISO format."""
        try:
            # This would use email.utils.parsedate_to_datetime in real implementation
            return datetime.now(timezone.utc).isoformat()
        except:
            return datetime.now(timezone.utc).isoformat()
    
    def _extract_email_content(self, mail_data: Dict[str, Any]) -> Tuple[str, Optional[str]]:
        """Extract text and HTML content from SES mail data."""
        # In real implementation, this would fetch from S3
        # For now, return placeholder
        return "[Email content would be fetched from S3]", None
    
    def _extract_message_content(self, msg: email.message.Message) -> Tuple[str, Optional[str]]:
        """Extract text and HTML content from email message."""
        body_text = ""
        body_html = None
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain":
                    body_text += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                elif content_type == "text/html":
                    body_html = part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            body_text = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        
        return body_text, body_html
    
    def _extract_attachments(self, mail_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract attachment information."""
        # Placeholder for attachment extraction
        return []
    
    def _extract_message_attachments(self, msg: email.message.Message) -> List[Dict[str, Any]]:
        """Extract attachments from email message."""
        attachments = []
        
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_disposition() == 'attachment':
                    filename = part.get_filename()
                    if filename:
                        attachments.append({
                            'filename': filename,
                            'content_type': part.get_content_type(),
                            'size': len(part.get_payload(decode=True) or b'')
                        })
        
        return attachments
    
    def _is_reply_email(self, subject: str, headers: Dict[str, str]) -> bool:
        """Determine if email is a reply."""
        # Check subject line
        subject_lower = subject.lower()
        for pattern in self.reply_indicators:
            if re.match(pattern, subject_lower):
                return True
        
        # Check headers
        return bool(headers.get('in-reply-to') or headers.get('references'))
    
    def _is_valid_email(self, email_address: str) -> bool:
        """Basic email validation."""
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email_address))
    
    def _is_automated_email(self, email_address: str) -> bool:
        """Check if email appears to be automated."""
        email_lower = email_address.lower()
        return any(pattern in email_lower for pattern in self.automated_patterns)
    
    def _calculate_spam_score(self, parsed_email: ParsedEmail) -> int:
        """Calculate basic spam score."""
        score = 0
        
        # Check for excessive caps
        caps_ratio = sum(1 for c in parsed_email.body_text if c.isupper()) / max(len(parsed_email.body_text), 1)
        if caps_ratio > 0.5:
            score += 3
        
        # Check for excessive exclamation marks
        exclamation_count = parsed_email.body_text.count('!')
        if exclamation_count > 5:
            score += 2
        
        # Check for suspicious patterns
        suspicious_words = ['free', 'money', 'win', 'urgent', 'click here', 'limited time']
        body_lower = parsed_email.body_text.lower()
        score += sum(2 for word in suspicious_words if word in body_lower)
        
        return min(score, 10)  # Cap at 10
    
    def _clean_email_body(self, body_text: str) -> str:
        """Clean email body text."""
        # Remove common email signatures first (before collapsing whitespace)
        signature_patterns = [
            r'--\s*\n.*',
            r'Sent from my \w+',
            r'Get Outlook for \w+',
        ]
        
        cleaned = body_text.strip()
        for pattern in signature_patterns:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE | re.DOTALL)
        
        # Clean up excessive whitespace, but preserve line breaks for quote detection
        # Replace multiple spaces with single space, but keep line breaks
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)  # Multiple spaces/tabs to single space
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)  # Multiple newlines to max 2
        
        return cleaned.strip()
    
    def _separate_quoted_text(self, body_text: str) -> Dict[str, str]:
        """Separate new content from quoted text."""
        # Common quote indicators
        quote_patterns = [
            r'^>.*',
            r'^On .* wrote:',
            r'^From:.*',
            r'-----Original Message-----',
        ]
        
        lines = body_text.split('\n')
        new_lines = []
        quoted_lines = []
        in_quote = False
        
        for line in lines:
            line_stripped = line.strip()
            
            # Check if this line starts a quote
            is_quote_line = any(re.match(pattern, line_stripped, re.IGNORECASE) for pattern in quote_patterns)
            
            if is_quote_line or line.startswith('>'):
                in_quote = True
            
            if in_quote:
                quoted_lines.append(line)
            else:
                new_lines.append(line)
        
        return {
            'new_content': '\n'.join(new_lines).strip(),
            'quoted_content': '\n'.join(quoted_lines).strip()
        }
    
    def _extract_action_keywords(self, text: str) -> List[str]:
        """Extract action keywords for dungeon games."""
        action_words = [
            'attack', 'defend', 'cast', 'spell', 'move', 'go', 'walk', 'run',
            'search', 'examine', 'look', 'inspect', 'take', 'grab', 'pick',
            'use', 'drink', 'eat', 'open', 'close', 'talk', 'speak', 'say',
            'hide', 'sneak', 'climb', 'jump', 'swim', 'fly'
        ]
        
        text_lower = text.lower()
        found_actions = []
        
        for action in action_words:
            if action in text_lower:
                found_actions.append(action)
        
        return found_actions
    
    def _extract_emotional_indicators(self, text: str) -> List[str]:
        """Extract emotional indicators for therapy sessions."""
        emotion_words = [
            'happy', 'sad', 'angry', 'frustrated', 'excited', 'worried',
            'anxious', 'calm', 'peaceful', 'stressed', 'overwhelmed',
            'grateful', 'thankful', 'hurt', 'disappointed', 'hopeful',
            'confused', 'clarity', 'understanding', 'misunderstood'
        ]
        
        text_lower = text.lower()
        found_emotions = []
        
        for emotion in emotion_words:
            if emotion in text_lower:
                found_emotions.append(emotion)
        
        return found_emotions
    
    def _extract_questions(self, text: str) -> List[str]:
        """Extract questions from text."""
        # Find sentences ending with question marks
        questions = re.findall(r'[^.!?]*\?', text)
        return [q.strip() for q in questions if q.strip()]


def get_email_parser() -> EmailParser:
    """Get email parser instance."""
    return EmailParser()


def parse_ses_email(ses_record: Dict[str, Any]) -> ParsedEmail:
    """Convenience function to parse SES email."""
    parser = get_email_parser()
    return parser.parse_ses_email(ses_record)


def validate_email_for_processing(parsed_email: ParsedEmail) -> bool:
    """Convenience function to validate email for processing."""
    parser = get_email_parser()
    is_valid, errors = parser.validate_email(parsed_email)
    
    if not is_valid:
        logger.warning(f"Email validation failed: {errors}")
    
    return is_valid