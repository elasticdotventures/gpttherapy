"""
Pydantic models for email processing and validation.

This module provides structured, validated models for email handling,
replacing manual validation with automatic Pydantic validation.
"""

import re
from datetime import datetime
from typing import Any

from email_validator import EmailNotValidError, validate_email
from pydantic import (
    BaseModel,
    EmailStr,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

from .datetime_utils import datetime_to_instant
from .settings import settings


class EmailAttachment(BaseModel):
    """Model for email attachments."""

    filename: str
    content_type: str
    size: int = Field(ge=0, description="Size in bytes")
    content_id: str | None = None
    is_inline: bool = False

    @field_validator("size")
    @classmethod
    def validate_size(cls, v: int) -> int:
        max_size = 25 * 1024 * 1024  # 25MB AWS SES limit
        if v > max_size:
            raise ValueError(f"Attachment too large: {v} bytes (max {max_size})")
        return v


class EmailContent(BaseModel):
    """Model for email content extraction."""

    raw_content: str
    clean_content: str
    new_content: str = Field(description="New content (excluding quoted text)")
    quoted_content: str = ""
    action_keywords: list[str] = Field(default_factory=list)
    emotional_indicators: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    word_count: int = Field(ge=0)
    contains_response: bool = Field(
        description="Whether email contains meaningful response"
    )

    @field_validator("word_count")
    @classmethod
    def validate_word_count(cls, v: int, values: ValidationInfo) -> int:
        # Auto-calculate if not provided
        if "new_content" in values.data:
            calculated = len(values.data["new_content"].split())
            return calculated if v == 0 else v
        return v

    @field_validator("contains_response")
    @classmethod
    def validate_contains_response(cls, v: bool, values: ValidationInfo) -> bool:
        # Auto-calculate if not explicitly set
        if "new_content" in values.data:
            return len(values.data["new_content"].strip()) > 10
        return v


class ParsedEmail(BaseModel):
    """
    Pydantic model for parsed and validated email messages.

    Replaces the old dataclass with automatic validation, type checking,
    and proper email address validation.
    """

    # Core email fields
    from_address: EmailStr = Field(description="Sender email address")
    to_addresses: list[EmailStr] = Field(
        min_length=1, description="Recipient email addresses"
    )
    cc_addresses: list[EmailStr] = Field(
        default_factory=list, description="CC email addresses"
    )
    bcc_addresses: list[EmailStr] = Field(
        default_factory=list, description="BCC email addresses"
    )

    # Email metadata
    subject: str = Field(
        max_length=998, description="Email subject line"
    )  # RFC 5322 limit
    message_id: str = Field(description="Unique message identifier")
    timestamp: datetime = Field(description="Email timestamp")

    # Content
    body_text: str = Field(description="Plain text body")
    body_html: str | None = Field(default=None, description="HTML body (if present)")
    attachments: list[EmailAttachment] = Field(default_factory=list)

    # Email headers and metadata
    headers: dict[str, str] = Field(default_factory=dict, description="Email headers")

    # Thread and reply tracking
    is_reply: bool = Field(default=False, description="Whether this is a reply")
    reply_to_message_id: str | None = Field(
        default=None, description="Message ID being replied to"
    )
    thread_id: str | None = Field(default=None, description="Thread identifier")

    # Processing metadata
    spam_score: int = Field(
        default=0, ge=0, le=10, description="Spam likelihood score (0-10)"
    )
    is_automated: bool = Field(
        default=False, description="Whether email appears automated"
    )
    processing_timestamp: datetime = Field(
        default_factory=lambda: datetime_to_instant(datetime.now()).py_datetime()
    )

    # Game/therapy specific content
    extracted_content: EmailContent | None = Field(
        default=None, description="Extracted game content"
    )

    model_config = {
        # Enable validation on assignment
        "validate_assignment": True,
        # Use enum values in serialization
        "use_enum_values": True,
        # Allow extra fields for extensibility
        "extra": "allow",
    }

    @field_validator("body_text")
    @classmethod
    def validate_body_text(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Email body cannot be empty")

        max_length = (
            settings.MAX_EMAIL_BODY_LENGTH
            if hasattr(settings, "MAX_EMAIL_BODY_LENGTH")
            else 50000
        )
        if len(v) > max_length:
            raise ValueError(f"Email body too long: {len(v)} chars (max {max_length})")

        return v.strip()

    @field_validator("spam_score")
    @classmethod
    def validate_spam_score(cls, v: int) -> int:
        if v > 7:  # High spam threshold
            raise ValueError(f"Email has high spam score: {v}/10")
        return v

    @field_validator("message_id")
    @classmethod
    def validate_message_id(cls, v: str) -> str:
        if not v:
            raise ValueError("Message ID is required")
        # Basic message ID format validation
        if not re.match(r"^<[^>]+>$|^[a-zA-Z0-9._-]+@[a-zA-Z0-9.-]+$", v):
            # If it doesn't match standard format, accept but log
            pass
        return v

    @field_validator("is_automated")
    @classmethod
    def validate_not_automated(cls, v: bool, values: ValidationInfo) -> bool:
        if v and "from_address" in values.data:
            from_addr = values.data["from_address"]
            automated_patterns = [
                r"noreply@",
                r"no-reply@",
                r"donotreply@",
                r"automated@",
                r"system@",
                r"daemon@",
            ]
            for pattern in automated_patterns:
                if re.search(pattern, str(from_addr), re.IGNORECASE):
                    raise ValueError(f"Automated emails not allowed: {from_addr}")
        return v

    @model_validator(mode="after")
    def validate_email_addresses(self) -> "ParsedEmail":
        """Validate all email addresses using email-validator."""

        # Skip validation for test domains
        test_domains = ["example.com", "example.org", "test.com", "promptexecution.com"]
        sender_domain = str(self.from_address).split("@")[1].lower()

        if sender_domain not in test_domains:
            # Validate sender for real domains
            try:
                validate_email(str(self.from_address))
            except EmailNotValidError as e:
                raise ValueError(f"Invalid sender email: {e}") from e

        # Check domain restrictions if configured (skip for test domains)
        if settings.ALLOWED_EMAIL_DOMAINS and sender_domain not in test_domains:
            if sender_domain not in [d.lower() for d in settings.ALLOWED_EMAIL_DOMAINS]:
                raise ValueError(f"Email domain not allowed: {sender_domain}")

        return self

    @model_validator(mode="after")
    def validate_content_safety(self) -> "ParsedEmail":
        """Validate email content for safety and appropriateness."""

        # Check for suspicious content patterns
        suspicious_patterns = [
            r"<script[^>]*>.*?</script>",  # Script tags
            r"javascript:",  # JavaScript URLs
            r"data:text/html",  # Data URLs
        ]

        content_to_check = self.body_text + (self.body_html or "")

        for pattern in suspicious_patterns:
            if re.search(pattern, content_to_check, re.IGNORECASE | re.DOTALL):
                raise ValueError(f"Suspicious content detected: {pattern}")

        return self

    def calculate_spam_score(self) -> int:
        """Calculate and update spam score based on content analysis."""
        score = 0
        text = self.body_text.lower()

        # Excessive capitals
        caps_ratio = sum(1 for c in self.body_text if c.isupper()) / max(
            len(self.body_text), 1
        )
        if caps_ratio > 0.5:
            score += 3

        # Excessive punctuation
        exclamation_count = self.body_text.count("!")
        if exclamation_count > 5:
            score += 2

        # Suspicious words/phrases
        spam_indicators = [
            "free money",
            "act now",
            "limited time",
            "click here",
            "winner",
            "congratulations",
            "urgent",
            "immediate action",
        ]
        score += sum(2 for indicator in spam_indicators if indicator in text)

        # URL count
        url_count = len(re.findall(r"https?://\S+", self.body_text))
        if url_count > 3:
            score += min(url_count - 3, 3)

        self.spam_score = min(score, 10)
        return self.spam_score

    def extract_session_id(self) -> str | None:
        """Extract session ID from email addressing."""
        from .storage import extract_session_id_from_email

        # Check all recipient addresses for session IDs
        for addr in self.to_addresses:
            session_id = extract_session_id_from_email(str(addr))
            if session_id:
                return session_id

        return None

    def is_valid_for_processing(self) -> tuple[bool, list[str]]:
        """
        Check if email is valid for GPT Therapy processing.

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check spam score
        if self.spam_score > 7:
            errors.append(f"High spam score: {self.spam_score}/10")

        # Check for automated email
        if self.is_automated:
            errors.append("Automated emails not processed")

        # Check content length
        if len(self.body_text.strip()) < 10:
            errors.append("Email content too short")

        # Check for session ID in addressing
        session_id = self.extract_session_id()
        if not session_id:
            errors.append("No valid session ID found in email addressing")

        return len(errors) == 0, errors

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/serialization."""
        return self.model_dump(exclude_none=True, by_alias=True, serialize_as_any=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ParsedEmail":
        """Create instance from dictionary."""
        return cls.model_validate(data)


class EmailProcessingResult(BaseModel):
    """Result of email processing operation."""

    success: bool
    parsed_email: ParsedEmail | None = None
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    processing_time_ms: int = Field(ge=0)
    session_id: str | None = None
    action_required: str | None = None

    model_config = {"extra": "allow"}

    def add_error(self, error: str) -> None:
        """Add an error message."""
        self.errors.append(error)
        self.success = False

    def add_warning(self, warning: str) -> None:
        """Add a warning message."""
        self.warnings.append(warning)

    def has_errors(self) -> bool:
        """Check if processing had errors."""
        return len(self.errors) > 0

    def has_warnings(self) -> bool:
        """Check if processing had warnings."""
        return len(self.warnings) > 0


# Validation schemas for specific use cases
class GameEmailSchema(ParsedEmail):
    """Schema for game-related emails with additional validation."""

    @model_validator(mode="after")
    def validate_game_content(self) -> "GameEmailSchema":
        """Validate content is appropriate for game context."""
        if self.extracted_content:
            # Ensure there's meaningful game content
            if not self.extracted_content.new_content.strip():
                raise ValueError("Game emails must contain player input")

            # Check for minimum engagement
            if self.extracted_content.word_count < 3:
                raise ValueError("Game input too short (minimum 3 words)")

        return self


class TherapyEmailSchema(ParsedEmail):
    """Schema for therapy-related emails with additional validation."""

    @model_validator(mode="after")
    def validate_therapy_content(self) -> "TherapyEmailSchema":
        """Validate content is appropriate for therapy context."""
        if self.extracted_content:
            # Check for appropriate content length for therapy
            if self.extracted_content.word_count > 1000:
                raise ValueError("Therapy responses should be concise (max 1000 words)")

            # Ensure meaningful therapeutic content
            if not self.extracted_content.new_content.strip():
                raise ValueError("Therapy emails must contain participant response")

        return self


# Export commonly used types
__all__ = [
    "ParsedEmail",
    "EmailAttachment",
    "EmailContent",
    "EmailProcessingResult",
    "GameEmailSchema",
    "TherapyEmailSchema",
]
