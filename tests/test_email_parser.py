"""
Tests for email parsing and validation.
"""

import os
import pytest
from unittest.mock import Mock, patch

# Set test environment
os.environ.update({
    'AWS_REGION': 'us-east-1',
    'IS_TEST_ENV': 'true',
    'SESSIONS_TABLE_NAME': 'test-sessions',
    'TURNS_TABLE_NAME': 'test-turns',
    'PLAYERS_TABLE_NAME': 'test-players',
    'GAMEDATA_S3_BUCKET': 'test-bucket'
})

from src.email_parser import (
    EmailParser, ParsedEmail, EmailValidationError,
    get_email_parser, parse_ses_email, validate_email_for_processing
)


class TestEmailParser:
    """Test EmailParser functionality."""
    
    @pytest.fixture
    def email_parser(self):
        """Get EmailParser instance."""
        return EmailParser()
    
    @pytest.fixture
    def sample_ses_record(self):
        """Sample SES record for testing."""
        return {
            'ses': {
                'mail': {
                    'messageId': 'test-message-123',
                    'timestamp': '2023-01-01T12:00:00.000Z',
                    'commonHeaders': {
                        'from': ['player@example.com'],
                        'to': ['123@dungeon.promptexecution.com'],
                        'cc': [],
                        'subject': 'Re: Dungeon Adventure Turn 5'
                    },
                    'headers': [
                        {'name': 'In-Reply-To', 'value': '<prev-message-id>'},
                        {'name': 'References', 'value': '<thread-id>'}
                    ]
                },
                'receipt': {
                    'recipients': ['123@dungeon.promptexecution.com']
                }
            }
        }
    
    @pytest.fixture
    def sample_parsed_email(self):
        """Sample ParsedEmail for testing."""
        return ParsedEmail(
            from_address='player@example.com',
            to_addresses=['123@dungeon.promptexecution.com'],
            cc_addresses=[],
            subject='Re: Dungeon Adventure Turn 5',
            body_text='I want to attack the goblin with my sword!',
            body_html=None,
            message_id='test-message-123',
            timestamp='2023-01-01T12:00:00.000Z',
            attachments=[],
            headers={'in-reply-to': '<prev-message-id>'},
            is_reply=True,
            reply_to_message_id='<prev-message-id>',
            thread_id='<thread-id>'
        )
    
    def test_parse_ses_email_basic(self, email_parser, sample_ses_record):
        """Test basic SES email parsing."""
        with patch.object(email_parser, '_extract_email_content', 
                          return_value=('Test email body', None)):
            parsed_email = email_parser.parse_ses_email(sample_ses_record)
            
            assert parsed_email.from_address == 'player@example.com'
            assert parsed_email.to_addresses == ['123@dungeon.promptexecution.com']
            assert parsed_email.subject == 'Re: Dungeon Adventure Turn 5'
            assert parsed_email.message_id == 'test-message-123'
            assert parsed_email.is_reply is True
            assert parsed_email.reply_to_message_id == '<prev-message-id>'
    
    def test_parse_ses_email_error(self, email_parser):
        """Test SES email parsing with invalid data."""
        invalid_record = {'invalid': 'data'}
        
        with pytest.raises(EmailValidationError):
            email_parser.parse_ses_email(invalid_record)
    
    def test_parse_raw_email(self, email_parser):
        """Test parsing raw email string."""
        raw_email = """From: player@example.com
To: 123@dungeon.promptexecution.com
Subject: Test Subject
Message-ID: <test-123>
Date: Mon, 1 Jan 2023 12:00:00 +0000

This is the email body.
"""
        
        parsed_email = email_parser.parse_raw_email(raw_email)
        
        assert parsed_email.from_address == 'player@example.com'
        assert '123@dungeon.promptexecution.com' in parsed_email.to_addresses
        assert parsed_email.subject == 'Test Subject'
        assert 'This is the email body.' in parsed_email.body_text
    
    def test_validate_email_valid(self, email_parser, sample_parsed_email):
        """Test validation of valid email."""
        is_valid, errors = email_parser.validate_email(sample_parsed_email)
        
        assert is_valid is True
        assert errors == []
    
    def test_validate_email_missing_fields(self, email_parser):
        """Test validation with missing required fields."""
        email_data = ParsedEmail(
            from_address='',  # Missing
            to_addresses=[],  # Missing
            cc_addresses=[],
            subject='Test',
            body_text='',  # Empty
            body_html=None,
            message_id='test-123',
            timestamp='2023-01-01T12:00:00Z',
            attachments=[],
            headers={},
            is_reply=False,
            reply_to_message_id=None,
            thread_id=None
        )
        
        is_valid, errors = email_parser.validate_email(email_data)
        
        assert is_valid is False
        assert len(errors) >= 3  # Missing sender, recipients, empty body
    
    def test_validate_email_invalid_addresses(self, email_parser, sample_parsed_email):
        """Test validation with invalid email addresses."""
        sample_parsed_email.from_address = 'invalid-email'
        sample_parsed_email.to_addresses = ['also-invalid']
        
        is_valid, errors = email_parser.validate_email(sample_parsed_email)
        
        assert is_valid is False
        assert any('Invalid sender email' in error for error in errors)
        assert any('Invalid recipient email' in error for error in errors)
    
    def test_validate_email_automated(self, email_parser, sample_parsed_email):
        """Test validation rejects automated emails."""
        sample_parsed_email.from_address = 'noreply@example.com'
        
        is_valid, errors = email_parser.validate_email(sample_parsed_email)
        
        assert is_valid is False
        assert any('automated' in error.lower() for error in errors)
    
    def test_validate_email_too_long(self, email_parser, sample_parsed_email):
        """Test validation rejects emails that are too long."""
        sample_parsed_email.body_text = 'x' * 20000  # 20KB
        
        is_valid, errors = email_parser.validate_email(sample_parsed_email)
        
        assert is_valid is False
        assert any('too long' in error for error in errors)
    
    def test_extract_game_content(self, email_parser, sample_parsed_email):
        """Test extracting game-relevant content."""
        sample_parsed_email.body_text = """I want to attack the goblin!
        
I'm feeling excited about this adventure.

What should I do next?

> On previous turn you said:
> You see a goblin ahead."""
        
        content = email_parser.extract_game_content(sample_parsed_email)
        
        assert 'attack' in content['action_keywords']
        assert 'excited' in content['emotional_indicators']
        assert len(content['questions']) > 0
        assert 'What should I do next?' in content['questions'][0]
        assert content['contains_response'] is True
        assert len(content['new_content']) > 0
        assert len(content['quoted_content']) > 0
    
    def test_is_reply_email_subject(self, email_parser):
        """Test reply detection from subject line."""
        assert email_parser._is_reply_email('Re: Test Subject', {}) is True
        assert email_parser._is_reply_email('Fwd: Test Subject', {}) is True
        assert email_parser._is_reply_email('Test Subject', {}) is False
    
    def test_is_reply_email_headers(self, email_parser):
        """Test reply detection from headers."""
        headers_with_reply = {'in-reply-to': '<message-id>'}
        headers_with_references = {'references': '<thread-id>'}
        headers_empty = {}
        
        assert email_parser._is_reply_email('Test', headers_with_reply) is True
        assert email_parser._is_reply_email('Test', headers_with_references) is True
        assert email_parser._is_reply_email('Test', headers_empty) is False
    
    def test_is_valid_email(self, email_parser):
        """Test email address validation."""
        assert email_parser._is_valid_email('user@example.com') is True
        assert email_parser._is_valid_email('user.name+tag@example.co.uk') is True
        assert email_parser._is_valid_email('invalid-email') is False
        assert email_parser._is_valid_email('@example.com') is False
        assert email_parser._is_valid_email('user@') is False
    
    def test_is_automated_email(self, email_parser):
        """Test automated email detection."""
        assert email_parser._is_automated_email('noreply@example.com') is True
        assert email_parser._is_automated_email('no-reply@example.com') is True
        assert email_parser._is_automated_email('donotreply@example.com') is True
        assert email_parser._is_automated_email('system@example.com') is True
        assert email_parser._is_automated_email('user@example.com') is False
    
    def test_calculate_spam_score(self, email_parser, sample_parsed_email):
        """Test spam score calculation."""
        # Normal email
        normal_score = email_parser._calculate_spam_score(sample_parsed_email)
        assert normal_score < 5
        
        # Spammy email
        sample_parsed_email.body_text = 'FREE MONEY!!! WIN NOW!!! CLICK HERE!!! URGENT!!!'
        spam_score = email_parser._calculate_spam_score(sample_parsed_email)
        assert spam_score > 5
    
    def test_clean_email_body(self, email_parser):
        """Test email body cleaning."""
        dirty_body = """  This is   the main content.
        
        --
        Sent from my iPhone
        
        Get Outlook for iOS"""
        
        cleaned = email_parser._clean_email_body(dirty_body)
        
        assert 'This is the main content.' in cleaned
        assert 'Sent from my iPhone' not in cleaned
        assert 'Get Outlook for iOS' not in cleaned
    
    def test_separate_quoted_text(self, email_parser):
        """Test separation of new content from quoted text."""
        email_body = """This is my new response.
        
        I have some thoughts.
        
        > On Jan 1, 2023, you wrote:
        > This is the quoted content.
        > More quoted content."""
        
        result = email_parser._separate_quoted_text(email_body)
        
        assert 'This is my new response.' in result['new_content']
        assert 'I have some thoughts.' in result['new_content']
        assert 'This is the quoted content.' in result['quoted_content']
        assert 'On Jan 1, 2023, you wrote:' in result['quoted_content']
    
    def test_extract_action_keywords(self, email_parser):
        """Test action keyword extraction."""
        text = "I want to attack the dragon and then cast a spell to defend myself."
        
        actions = email_parser._extract_action_keywords(text)
        
        assert 'attack' in actions
        assert 'cast' in actions
        assert 'defend' in actions
    
    def test_extract_emotional_indicators(self, email_parser):
        """Test emotional indicator extraction."""
        text = "I'm feeling really happy and excited, but also a bit worried about what's next."
        
        emotions = email_parser._extract_emotional_indicators(text)
        
        assert 'happy' in emotions
        assert 'excited' in emotions
        assert 'worried' in emotions
    
    def test_extract_questions(self, email_parser):
        """Test question extraction."""
        text = "What should I do next? How do I proceed? This is not a question."
        
        questions = email_parser._extract_questions(text)
        
        assert len(questions) == 2
        assert 'What should I do next?' in questions[0]
        assert 'How do I proceed?' in questions[1]


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_get_email_parser(self):
        """Test get_email_parser function."""
        parser = get_email_parser()
        assert isinstance(parser, EmailParser)
    
    @patch('src.email_parser.get_email_parser')
    def test_parse_ses_email_convenience(self, mock_get_parser):
        """Test parse_ses_email convenience function."""
        mock_parser = Mock()
        mock_parser.parse_ses_email.return_value = Mock()
        mock_get_parser.return_value = mock_parser
        
        test_record = {'test': 'data'}
        result = parse_ses_email(test_record)
        
        mock_parser.parse_ses_email.assert_called_once_with(test_record)
        assert result is not None
    
    @patch('src.email_parser.get_email_parser')
    def test_validate_email_for_processing_convenience(self, mock_get_parser):
        """Test validate_email_for_processing convenience function."""
        mock_parser = Mock()
        mock_parser.validate_email.return_value = (True, [])
        mock_get_parser.return_value = mock_parser
        
        test_email = Mock()
        result = validate_email_for_processing(test_email)
        
        mock_parser.validate_email.assert_called_once_with(test_email)
        assert result is True
    
    @patch('src.email_parser.get_email_parser')
    def test_validate_email_for_processing_with_errors(self, mock_get_parser):
        """Test validate_email_for_processing with validation errors."""
        mock_parser = Mock()
        mock_parser.validate_email.return_value = (False, ['Error 1', 'Error 2'])
        mock_get_parser.return_value = mock_parser
        
        test_email = Mock()
        result = validate_email_for_processing(test_email)
        
        assert result is False


class TestParsedEmail:
    """Test ParsedEmail dataclass."""
    
    def test_parsed_email_creation(self):
        """Test creating ParsedEmail instance."""
        email_data = ParsedEmail(
            from_address='test@example.com',
            to_addresses=['recipient@example.com'],
            cc_addresses=[],
            subject='Test Subject',
            body_text='Test body',
            body_html=None,
            message_id='test-123',
            timestamp='2023-01-01T12:00:00Z',
            attachments=[],
            headers={},
            is_reply=False,
            reply_to_message_id=None,
            thread_id=None
        )
        
        assert email_data.from_address == 'test@example.com'
        assert email_data.subject == 'Test Subject'
        assert email_data.is_reply is False


class TestEmailValidationError:
    """Test EmailValidationError exception."""
    
    def test_email_validation_error_creation(self):
        """Test creating EmailValidationError."""
        email_data = {'test': 'data'}
        error = EmailValidationError('Test error', email_data)
        
        assert str(error) == 'Test error'
        assert error.email_data == email_data
        assert error.error_type.value == 'validation_error'