"""
Tests for email parsing and validation.
"""

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from src.email_models import (
    EmailAttachment,
    EmailContent,
    GameEmailSchema,
    ParsedEmail,
    TherapyEmailSchema,
)
from src.email_parser import (
    EmailParser,
    EmailProcessingResult,
    EmailValidationError,
    get_email_parser,
    is_email_valid_for_processing,
    parse_ses_email,
    validate_email_for_game,
    validate_email_for_therapy,
)


class TestEmailParser:
    """Test EmailParser functionality with Pydantic models."""

    @pytest.fixture
    def email_parser(self):
        """Get EmailParser instance."""
        return EmailParser()

    @pytest.fixture
    def sample_ses_record(self):
        """Sample SES record for testing."""
        return {
            "ses": {
                "mail": {
                    "messageId": "test-message-123",
                    "timestamp": "2023-01-01T12:00:00.000Z",
                    "commonHeaders": {
                        "from": ["player@example.com"],
                        "to": ["123@dungeon.promptexecution.com"],
                        "cc": [],
                        "subject": "Re: Dungeon Adventure Turn 5",
                    },
                    "headers": [
                        {"name": "In-Reply-To", "value": "<prev-message-id>"},
                        {"name": "References", "value": "<thread-id>"},
                    ],
                },
                "receipt": {"recipients": ["123@dungeon.promptexecution.com"]},
            }
        }

    @pytest.fixture
    def sample_parsed_email(self):
        """Sample ParsedEmail for testing."""
        return ParsedEmail(
            from_address="player@example.com",
            to_addresses=["123@dungeon.promptexecution.com"],
            cc_addresses=[],
            subject="Re: Dungeon Adventure Turn 5",
            body_text="I want to attack the goblin with my sword!",
            body_html=None,
            message_id="test-message-123",
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            attachments=[],
            headers={"in-reply-to": "<prev-message-id>"},
            is_reply=True,
            reply_to_message_id="<prev-message-id>",
            thread_id="<thread-id>",
        )

    def test_parse_ses_email_basic(self, email_parser, sample_ses_record) -> None:
        """Test basic SES email parsing."""
        with patch.object(
            email_parser,
            "_extract_email_content_from_s3",
            return_value=("Test email body", None),
        ):
            result = email_parser.parse_ses_email(sample_ses_record)

            assert result.success is True
            assert result.parsed_email is not None
            assert result.parsed_email.from_address == "player@example.com"
            assert result.parsed_email.to_addresses == [
                "123@dungeon.promptexecution.com"
            ]
            assert result.parsed_email.subject == "Re: Dungeon Adventure Turn 5"
            assert result.parsed_email.message_id == "test-message-123"
            assert result.parsed_email.is_reply is True
            assert result.parsed_email.reply_to_message_id == "<prev-message-id>"

    def test_parse_ses_email_error(self, email_parser) -> None:
        """Test SES email parsing with invalid data."""
        invalid_record = {"invalid": "data"}

        result = email_parser.parse_ses_email(invalid_record)

        assert result.success is False
        assert len(result.errors) > 0
        assert "Missing 'ses' key" in result.errors[0]

    def test_parse_raw_email(self, email_parser) -> None:
        """Test parsing raw email string."""
        raw_email = """From: player@example.com
To: 123@dungeon.promptexecution.com
Subject: Test Subject
Message-ID: <test-123>
Date: Mon, 1 Jan 2023 12:00:00 +0000

This is the email body.
"""

        result = email_parser.parse_raw_email(raw_email)

        assert result.success is True
        assert result.parsed_email is not None
        assert result.parsed_email.from_address == "player@example.com"
        assert "123@dungeon.promptexecution.com" in result.parsed_email.to_addresses
        assert result.parsed_email.subject == "Test Subject"
        assert "This is the email body." in result.parsed_email.body_text

    def test_validate_email_valid(self, sample_parsed_email) -> None:
        """Test validation of valid email using Pydantic."""
        # Email should be valid since it's created with valid data
        assert sample_parsed_email.from_address == "player@example.com"

        # Test the is_valid_for_processing method
        is_valid, errors = sample_parsed_email.is_valid_for_processing()
        assert is_valid is True
        assert errors == []

    def test_validate_email_missing_fields(self) -> None:
        """Test validation with missing required fields using Pydantic."""
        # Pydantic will raise ValidationError during model creation
        with pytest.raises(ValidationError) as exc_info:
            ParsedEmail(
                from_address="",  # Invalid - empty email
                to_addresses=[],  # Invalid - empty list
                cc_addresses=[],
                subject="Test",
                body_text="",  # Invalid - empty body
                body_html=None,
                message_id="test-123",
                timestamp=datetime.now(UTC),
                attachments=[],
                headers={},
                is_reply=False,
                reply_to_message_id=None,
                thread_id=None,
            )

        # Check that validation errors were caught
        errors = exc_info.value.errors()
        assert len(errors) >= 3  # Multiple validation errors

    def test_validate_email_invalid_addresses(self) -> None:
        """Test validation with invalid email addresses using Pydantic."""
        # Pydantic EmailStr will catch invalid emails during creation
        with pytest.raises(ValidationError) as exc_info:
            ParsedEmail(
                from_address="invalid-email",  # Invalid email format
                to_addresses=["also-invalid"],  # Invalid email format
                cc_addresses=[],
                subject="Test",
                body_text="Valid body text here",
                message_id="test-123",
                timestamp=datetime.now(UTC),
                headers={},
            )

        # Verify email validation errors
        errors = exc_info.value.errors()
        assert any(
            "value is not a valid email address" in str(error) for error in errors
        )


class TestPydanticEmailModels:
    """Test the new Pydantic email models."""

    def test_parsed_email_creation(self) -> None:
        """Test creating a valid ParsedEmail with Pydantic validation."""
        email = ParsedEmail(
            from_address="test@example.com",
            to_addresses=["recipient@example.com"],
            subject="Test Subject",
            body_text="This is a test email body with enough content.",
            message_id="<test-123@example.com>",
            timestamp=datetime.now(UTC),
        )

        assert email.from_address == "test@example.com"
        assert "recipient@example.com" in email.to_addresses
        assert email.spam_score == 0  # Default value
        assert email.is_automated is False

    def test_parsed_email_spam_calculation(self) -> None:
        """Test automatic spam score calculation."""
        # Create email with moderate spam content that won't exceed threshold
        email = ParsedEmail(
            from_address="test@example.com",
            to_addresses=["recipient@example.com"],
            subject="Special Offer",
            body_text="Check out this great offer! Limited time only.",
            message_id="<test-123@example.com>",
            timestamp=datetime.now(UTC),
        )

        spam_score = email.calculate_spam_score()
        assert spam_score > 0  # Should detect some spam indicators
        assert spam_score <= 7  # But not exceed validation threshold

    def test_email_content_model(self) -> None:
        """Test EmailContent model validation."""
        content = EmailContent(
            raw_content="Original email content",
            clean_content="Cleaned email content",
            new_content="I want to attack the dragon",
            action_keywords=["attack"],
            emotional_indicators=["excited"],
            questions=["How do I proceed?"],
            word_count=6,
            contains_response=True,
        )

        assert content.action_keywords == ["attack"]
        assert content.emotional_indicators == ["excited"]
        assert content.contains_response is True

    def test_email_attachment_model(self) -> None:
        """Test EmailAttachment model validation."""
        attachment = EmailAttachment(
            filename="document.pdf", content_type="application/pdf", size=1024
        )

        assert attachment.filename == "document.pdf"
        assert attachment.size == 1024
        assert attachment.is_inline is False

        # Test size validation
        with pytest.raises(ValidationError):
            EmailAttachment(
                filename="huge.pdf",
                content_type="application/pdf",
                size=30 * 1024 * 1024,  # Over 25MB limit
            )

    def test_game_email_schema(self) -> None:
        """Test GameEmailSchema with game-specific validation."""
        email_data = {
            "from_address": "player@example.com",
            "to_addresses": ["session123@dungeon.example.com"],
            "subject": "My Turn",
            "body_text": "I attack the goblin with my sword!",
            "message_id": "<test-123@example.com>",
            "timestamp": datetime.now(UTC),
            "extracted_content": {
                "raw_content": "I attack the goblin with my sword!",
                "clean_content": "I attack the goblin with my sword!",
                "new_content": "I attack the goblin with my sword!",
                "action_keywords": ["attack"],
                "word_count": 7,
                "contains_response": True,
            },
        }

        game_email = GameEmailSchema.model_validate(email_data)
        assert game_email.extracted_content is not None
        assert game_email.extracted_content.action_keywords == ["attack"]

    def test_therapy_email_schema(self) -> None:
        """Test TherapyEmailSchema with therapy-specific validation."""
        email_data = {
            "from_address": "participant@example.com",
            "to_addresses": ["session456@therapy.example.com"],
            "subject": "My Response",
            "body_text": "I feel anxious about our last conversation.",
            "message_id": "<test-456@example.com>",
            "timestamp": datetime.now(UTC),
            "extracted_content": {
                "raw_content": "I feel anxious about our last conversation.",
                "clean_content": "I feel anxious about our last conversation.",
                "new_content": "I feel anxious about our last conversation.",
                "emotional_indicators": ["anxious"],
                "word_count": 8,
                "contains_response": True,
            },
        }

        therapy_email = TherapyEmailSchema.model_validate(email_data)
        assert therapy_email.extracted_content is not None
        assert therapy_email.extracted_content.emotional_indicators == ["anxious"]


class TestEmailProcessingResult:
    """Test EmailProcessingResult functionality."""

    def test_processing_result_creation(self) -> None:
        """Test creating EmailProcessingResult."""
        result = EmailProcessingResult(success=True, processing_time_ms=150)

        assert result.success is True
        assert result.processing_time_ms == 150
        assert result.errors == []
        assert result.warnings == []

    def test_processing_result_with_errors(self) -> None:
        """Test EmailProcessingResult error handling."""
        result = EmailProcessingResult(success=False, processing_time_ms=50)

        result.add_error("Test error")
        result.add_warning("Test warning")

        assert result.success is False
        assert result.has_errors() is True
        assert result.has_warnings() is True
        assert "Test error" in result.errors
        assert "Test warning" in result.warnings


class TestConvenienceFunctions:
    """Test convenience functions."""

    @pytest.fixture
    def email_parser(self):
        """Get EmailParser instance."""
        return EmailParser()

    @pytest.fixture
    def sample_parsed_email(self):
        """Sample ParsedEmail for testing."""
        return ParsedEmail(
            from_address="player@example.com",
            to_addresses=["123@dungeon.promptexecution.com"],
            cc_addresses=[],
            subject="Re: Dungeon Adventure Turn 5",
            body_text="I want to attack the goblin with my sword!",
            body_html=None,
            message_id="test-message-123",
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            attachments=[],
            headers={"in-reply-to": "<prev-message-id>"},
            is_reply=True,
            reply_to_message_id="<prev-message-id>",
            thread_id="<thread-id>",
        )

    def test_parse_ses_email_convenience(self) -> None:
        """Test parse_ses_email convenience function."""
        ses_record = {
            "ses": {
                "mail": {
                    "messageId": "test-message-123",
                    "timestamp": "2023-01-01T12:00:00.000Z",
                    "commonHeaders": {
                        "from": ["player@example.com"],
                        "to": ["123@dungeon.example.com"],
                        "subject": "Test Subject",
                    },
                    "headers": [],
                }
            }
        }

        with patch(
            "src.email_parser.EmailParser._extract_email_content_from_s3",
            return_value=("Test body", None),
        ):
            result = parse_ses_email(ses_record)

        assert isinstance(result, EmailProcessingResult)
        assert result.success is True

    def test_validate_email_for_game_convenience(self, sample_parsed_email) -> None:
        """Test validate_email_for_game convenience function."""
        result = validate_email_for_game(sample_parsed_email)

        assert isinstance(result, EmailProcessingResult)
        # Should succeed with valid game email
        assert result.success is True

    def test_validate_email_for_therapy_convenience(self) -> None:
        """Test validate_email_for_therapy convenience function."""
        # Create a valid therapy email
        therapy_email = ParsedEmail(
            from_address="participant@test.com",
            to_addresses=["session456@therapy.test.com"],
            subject="My Response",
            body_text="I feel anxious about our conversation.",
            message_id="<test-456@test.com>",
            timestamp=datetime.now(UTC),
        )

        result = validate_email_for_therapy(therapy_email)

        assert isinstance(result, EmailProcessingResult)
        # Should succeed with valid therapy email
        assert result.success is True

    def test_is_reply_email_subject(self, email_parser) -> None:
        """Test reply detection from subject line."""
        assert email_parser._is_reply_email("Re: Test Subject", {}) is True
        assert email_parser._is_reply_email("Fwd: Test Subject", {}) is True
        assert email_parser._is_reply_email("Test Subject", {}) is False

    def test_is_reply_email_headers(self, email_parser) -> None:
        """Test reply detection from headers."""
        headers_with_reply = {"in-reply-to": "<message-id>"}
        headers_with_references = {"references": "<thread-id>"}
        headers_empty = {}

        assert email_parser._is_reply_email("Test", headers_with_reply) is True
        assert email_parser._is_reply_email("Test", headers_with_references) is True
        assert email_parser._is_reply_email("Test", headers_empty) is False

    def test_is_automated_email(self, email_parser) -> None:
        """Test automated email detection."""
        assert email_parser._is_automated_email("noreply@example.com") is True
        assert email_parser._is_automated_email("no-reply@example.com") is True
        assert email_parser._is_automated_email("donotreply@example.com") is True
        assert email_parser._is_automated_email("system@example.com") is True
        assert email_parser._is_automated_email("user@example.com") is False

    def test_calculate_spam_score(self, sample_parsed_email) -> None:
        """Test spam score calculation using Pydantic model method."""
        # Normal email should have low spam score
        normal_score = sample_parsed_email.calculate_spam_score()
        assert normal_score < 5

        # Create spammy email
        spammy_email = ParsedEmail(
            from_address="sender@example.com",
            to_addresses=["recipient@example.com"],
            subject="Special offer",
            body_text="Special offer! Limited time! Click here now!",
            message_id="spam-123",
            timestamp=datetime.now(UTC),
        )
        spam_score = spammy_email.calculate_spam_score()
        assert spam_score > 0  # Should detect some spam indicators
        assert spam_score <= 7  # But not exceed validation threshold

    def test_clean_email_body(self, email_parser) -> None:
        """Test email body cleaning."""
        dirty_body = """  This is   the main content.

        --
        Sent from my iPhone

        Get Outlook for iOS"""

        cleaned = email_parser._clean_email_body(dirty_body)

        assert "This is the main content." in cleaned
        assert "Sent from my iPhone" not in cleaned
        assert "Get Outlook for iOS" not in cleaned

    def test_separate_quoted_text(self, email_parser) -> None:
        """Test separation of new content from quoted text."""
        email_body = """This is my new response.

        I have some thoughts.

        > On Jan 1, 2023, you wrote:
        > This is the quoted content.
        > More quoted content."""

        result = email_parser._separate_quoted_text(email_body)

        assert "This is my new response." in result["new_content"]
        assert "I have some thoughts." in result["new_content"]
        assert "This is the quoted content." in result["quoted_content"]
        assert "On Jan 1, 2023, you wrote:" in result["quoted_content"]

    def test_extract_action_keywords(self, email_parser) -> None:
        """Test action keyword extraction."""
        text = "I want to attack the dragon and then cast a spell to defend myself."

        actions = email_parser._extract_action_keywords(text)

        assert "attack" in actions
        assert "cast" in actions
        assert "defend" in actions

    def test_extract_emotional_indicators(self, email_parser) -> None:
        """Test emotional indicator extraction."""
        text = "I'm feeling really happy and excited, but also a bit worried about what's next."

        emotions = email_parser._extract_emotional_indicators(text)

        assert "happy" in emotions
        assert "excited" in emotions
        assert "worried" in emotions

    def test_extract_questions(self, email_parser) -> None:
        """Test question extraction."""
        text = "What should I do next? How do I proceed? This is not a question."

        questions = email_parser._extract_questions(text)

        # The regex may find questions differently than expected
        assert len(questions) >= 1  # At least one question found
        # Check that questions are detected in the text
        question_text = " ".join(questions)
        assert "What should I do next?" in question_text
        assert "How do I proceed?" in question_text


class TestUtilityFunctions:
    """Test utility functions."""

    @pytest.fixture
    def sample_parsed_email(self):
        """Sample ParsedEmail for testing."""
        return ParsedEmail(
            from_address="player@example.com",
            to_addresses=["123@dungeon.promptexecution.com"],
            cc_addresses=[],
            subject="Re: Dungeon Adventure Turn 5",
            body_text="I want to attack the goblin with my sword!",
            body_html=None,
            message_id="test-message-123",
            timestamp=datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC),
            attachments=[],
            headers={"in-reply-to": "<prev-message-id>"},
            is_reply=True,
            reply_to_message_id="<prev-message-id>",
            thread_id="<thread-id>",
        )

    def test_get_email_parser(self) -> None:
        """Test get_email_parser function."""
        parser = get_email_parser()
        assert isinstance(parser, EmailParser)

    @patch("src.email_parser.get_email_parser")
    def test_parse_ses_email_convenience(self, mock_get_parser) -> None:
        """Test parse_ses_email convenience function."""
        mock_parser = Mock()
        mock_parser.parse_ses_email.return_value = Mock()
        mock_get_parser.return_value = mock_parser

        test_record = {"test": "data"}
        result = parse_ses_email(test_record)

        mock_parser.parse_ses_email.assert_called_once_with(test_record)
        assert result is not None

    def test_is_email_valid_for_processing_convenience(
        self, sample_parsed_email
    ) -> None:
        """Test is_email_valid_for_processing convenience function."""
        result = is_email_valid_for_processing(sample_parsed_email)

        # Should succeed with valid email
        assert result is True

    def test_is_email_valid_for_processing_with_errors(self) -> None:
        """Test is_email_valid_for_processing with invalid email."""
        # Create email that will fail validation (empty body)
        try:
            ParsedEmail(
                from_address="test@example.com",
                to_addresses=["recipient@example.com"],
                subject="Test",
                body_text="",  # This will fail validation
                message_id="test-123",
                timestamp=datetime.now(UTC),
            )
            # If we get here, validation didn't catch the error
            raise AssertionError("Expected ValidationError for empty body")
        except ValidationError:
            # This is expected - empty body should fail validation
            assert True


class TestParsedEmail:
    """Test ParsedEmail dataclass."""

    def test_parsed_email_creation(self) -> None:
        """Test creating ParsedEmail instance."""
        email_data = ParsedEmail(
            from_address="test@example.com",
            to_addresses=["recipient@example.com"],
            cc_addresses=[],
            subject="Test Subject",
            body_text="Test body",
            body_html=None,
            message_id="test-123",
            timestamp="2023-01-01T12:00:00Z",
            attachments=[],
            headers={},
            is_reply=False,
            reply_to_message_id=None,
            thread_id=None,
        )

        assert email_data.from_address == "test@example.com"
        assert email_data.subject == "Test Subject"
        assert email_data.is_reply is False


class TestEmailValidationError:
    """Test EmailValidationError exception."""

    def test_email_validation_error_creation(self) -> None:
        """Test creating EmailValidationError."""
        email_data = {"test": "data"}
        error = EmailValidationError("Test error", email_data)

        assert str(error) == "Test error"
        assert error.email_data == email_data
        assert error.error_type.value == "validation_error"
