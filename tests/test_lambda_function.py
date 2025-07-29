"""Tests for Lambda function handler."""

from unittest.mock import Mock, patch

from src.lambda_function import extract_session_info, lambda_handler, process_ses_email


class TestLambdaHandler:
    """Test cases for the main Lambda handler."""

    def test_lambda_handler_success(self) -> None:
        """Test successful lambda handler execution."""
        event = {
            "Records": [
                {
                    "eventSource": "aws:ses",
                    "ses": {
                        "mail": {
                            "commonHeaders": {
                                "from": ["user@example.com"],
                                "subject": "Test Subject",
                                "to": ["test@dungeon.promptexecution.com"],
                            }
                        },
                        "receipt": {"recipients": ["test@dungeon.promptexecution.com"]},
                    },
                }
            ]
        }

        with patch("src.lambda_function.process_ses_email") as mock_process:
            result = lambda_handler(event, Mock())

            assert result["statusCode"] == 200
            assert "Email processed successfully" in result["body"]
            mock_process.assert_called_once()

    def test_lambda_handler_error(self) -> None:
        """Test lambda handler error handling."""
        event = {
            "Records": [{"eventSource": "aws:ses", "ses": {"mail": {}, "receipt": {}}}]
        }

        with patch(
            "src.lambda_function.process_ses_email", side_effect=Exception("Test error")
        ):
            result = lambda_handler(event, Mock())

            assert result["statusCode"] == 500
            assert "Internal server error" in result["body"]


class TestSessionExtraction:
    """Test cases for session information extraction."""

    def test_extract_session_info_with_session_id(self) -> None:
        """Test extracting valid session info."""
        recipients = ["123@dungeon.promptexecution.com"]

        session_info = extract_session_info(recipients)

        assert session_info is not None
        assert session_info["session_id"] == "123"
        assert session_info["game_type"] == "dungeon"
        assert session_info["domain"] == "dungeon.promptexecution.com"

    def test_extract_session_info_no_session(self) -> None:
        """Test with no session ID in recipients."""
        recipients = ["general@promptexecution.com"]

        session_info = extract_session_info(recipients)

        assert session_info is None

    def test_extract_session_info_multiple_recipients(self) -> None:
        """Test with multiple recipients, one with session ID."""
        recipients = ["general@promptexecution.com", "456@intimacy.promptexecution.com"]

        session_info = extract_session_info(recipients)

        assert session_info is not None
        assert session_info["session_id"] == "456"
        assert session_info["game_type"] == "intimacy"


class TestEmailProcessing:
    """Test cases for email processing logic."""

    @patch("src.lambda_function.send_response_email")
    @patch("src.lambda_function.process_session_turn")
    @patch("src.lambda_function.extract_session_info")
    def test_process_ses_email_existing_session(
        self, mock_extract, mock_process_turn, mock_send
    ) -> None:
        """Test processing email for existing session."""
        record = {
            "ses": {
                "mail": {
                    "commonHeaders": {
                        "from": ["user@example.com"],
                        "subject": "Test Subject",
                        "to": ["123@dungeon.promptexecution.com"],
                    }
                },
                "receipt": {"recipients": ["123@dungeon.promptexecution.com"]},
            }
        }

        mock_extract.return_value = {"session_id": "123", "game_type": "dungeon"}

        process_ses_email(record)

        mock_extract.assert_called_once()
        mock_process_turn.assert_called_once()

    @patch("src.lambda_function.send_response_email")
    @patch("src.lambda_function.initialize_new_session")
    @patch("src.lambda_function.extract_session_info")
    def test_process_ses_email_new_session(
        self, mock_extract, mock_init, mock_send
    ) -> None:
        """Test processing email for new session."""
        record = {
            "ses": {
                "mail": {
                    "commonHeaders": {
                        "from": ["user@example.com"],
                        "subject": "Test Subject",
                        "to": ["dungeon@promptexecution.com"],
                    }
                },
                "receipt": {"recipients": ["dungeon@promptexecution.com"]},
            }
        }

        mock_extract.return_value = None

        process_ses_email(record)

        mock_extract.assert_called_once()
        mock_init.assert_called_once()
