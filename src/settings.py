"""
Centralized configuration management for GPT Therapy.

This module provides a single point of configuration using python-decouple
to manage environment variables with proper defaults and type casting.
"""

from decouple import Csv, config  # type: ignore


class Settings:
    """Centralized application settings."""

    # AWS Configuration
    AWS_REGION: str = config("AWS_REGION", default="ap-southeast-4")
    SES_REGION: str = config("SES_REGION", default="ap-southeast-2")

    # DynamoDB Table Names
    SESSIONS_TABLE_NAME: str = config(
        "SESSIONS_TABLE_NAME", default="gpttherapy-sessions"
    )
    TURNS_TABLE_NAME: str = config("TURNS_TABLE_NAME", default="gpttherapy-turns")
    PLAYERS_TABLE_NAME: str = config("PLAYERS_TABLE_NAME", default="gpttherapy-players")

    # S3 Configuration
    GAMEDATA_S3_BUCKET: str = config(
        "GAMEDATA_S3_BUCKET", default="gpttherapy-gamedata"
    )

    # Logging Configuration
    LOG_LEVEL: str = config("LOG_LEVEL", default="INFO")

    # Environment Detection
    IS_TEST_ENV: bool = config("IS_TEST_ENV", default=False, cast=bool)
    IS_LAMBDA_ENV: bool = config("AWS_LAMBDA_FUNCTION_NAME", default="", cast=bool)

    # Lambda-specific Configuration
    AWS_LAMBDA_FUNCTION_NAME: str = config("AWS_LAMBDA_FUNCTION_NAME", default="")
    AWS_LAMBDA_FUNCTION_VERSION: str = config(
        "AWS_LAMBDA_FUNCTION_VERSION", default="unknown"
    )

    # Email Configuration
    DEFAULT_FROM_EMAIL: str = config(
        "DEFAULT_FROM_EMAIL", default="noreply@gpttherapy.com"
    )
    ADMIN_EMAIL: str = config("ADMIN_EMAIL", default="admin@gpttherapy.com")

    # Game Configuration
    MAX_PLAYERS_PER_SESSION: int = config(
        "MAX_PLAYERS_PER_SESSION", default=8, cast=int
    )
    SESSION_TIMEOUT_HOURS: int = config("SESSION_TIMEOUT_HOURS", default=48, cast=int)
    TURN_TIMEOUT_HOURS: int = config("TURN_TIMEOUT_HOURS", default=24, cast=int)

    # AI Configuration
    AI_MODEL_NAME: str = config(
        "AI_MODEL_NAME", default="anthropic.claude-3-haiku-20240307-v1:0"
    )
    AI_MAX_TOKENS: int = config("AI_MAX_TOKENS", default=2000, cast=int)
    AI_TEMPERATURE: float = config("AI_TEMPERATURE", default=0.7, cast=float)

    # Rate Limiting
    MAX_EMAILS_PER_HOUR: int = config("MAX_EMAILS_PER_HOUR", default=10, cast=int)
    MAX_SESSIONS_PER_USER: int = config("MAX_SESSIONS_PER_USER", default=5, cast=int)

    # Email Processing
    MAX_EMAIL_BODY_LENGTH: int = config(
        "MAX_EMAIL_BODY_LENGTH", default=50000, cast=int
    )
    MAX_ATTACHMENT_SIZE: int = config(
        "MAX_ATTACHMENT_SIZE", default=25 * 1024 * 1024, cast=int
    )  # 25MB
    SPAM_SCORE_THRESHOLD: int = config("SPAM_SCORE_THRESHOLD", default=7, cast=int)

    # Security
    ALLOWED_EMAIL_DOMAINS: list[str] = config(
        "ALLOWED_EMAIL_DOMAINS", default="", cast=Csv()
    )  # Empty list means all domains allowed

    # Monitoring and Observability
    ENABLE_METRICS: bool = config("ENABLE_METRICS", default=True, cast=bool)
    METRICS_NAMESPACE: str = config("METRICS_NAMESPACE", default="GPTTherapy")

    # Debug and Development
    DEBUG: bool = config("DEBUG", default=False, cast=bool)
    ENABLE_PROFILING: bool = config("ENABLE_PROFILING", default=False, cast=bool)

    # Backup and Maintenance
    BACKUP_RETENTION_DAYS: int = config("BACKUP_RETENTION_DAYS", default=30, cast=int)
    ENABLE_AUTO_BACKUP: bool = config("ENABLE_AUTO_BACKUP", default=True, cast=bool)

    @property
    def is_production(self) -> bool:
        """Check if running in production environment."""
        return self.IS_LAMBDA_ENV and not self.IS_TEST_ENV and not self.DEBUG

    @property
    def is_development(self) -> bool:
        """Check if running in development environment."""
        return not self.IS_LAMBDA_ENV and not self.IS_TEST_ENV

    @property
    def log_level_numeric(self) -> int:
        """Get log level as numeric value for logging configuration."""
        levels = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
        return levels.get(self.LOG_LEVEL.upper(), 20)

    def validate(self) -> None:
        """Validate configuration settings and raise errors for invalid values."""
        errors = []

        # Validate required settings in production
        if self.is_production:
            required_settings = [
                ("SESSIONS_TABLE_NAME", self.SESSIONS_TABLE_NAME),
                ("TURNS_TABLE_NAME", self.TURNS_TABLE_NAME),
                ("PLAYERS_TABLE_NAME", self.PLAYERS_TABLE_NAME),
                ("GAMEDATA_S3_BUCKET", self.GAMEDATA_S3_BUCKET),
            ]

            for name, value in required_settings:
                if not value or value.startswith("gpttherapy-"):  # Default values
                    errors.append(f"{name} must be set in production environment")

        # Validate numeric ranges
        if self.MAX_PLAYERS_PER_SESSION < 1 or self.MAX_PLAYERS_PER_SESSION > 20:
            errors.append("MAX_PLAYERS_PER_SESSION must be between 1 and 20")

        if self.SESSION_TIMEOUT_HOURS < 1 or self.SESSION_TIMEOUT_HOURS > 168:  # 1 week
            errors.append("SESSION_TIMEOUT_HOURS must be between 1 and 168 hours")

        if self.AI_TEMPERATURE < 0.0 or self.AI_TEMPERATURE > 2.0:
            errors.append("AI_TEMPERATURE must be between 0.0 and 2.0")

        if self.AI_MAX_TOKENS < 100 or self.AI_MAX_TOKENS > 8192:
            errors.append("AI_MAX_TOKENS must be between 100 and 8192")

        if errors:
            raise ValueError(f"Configuration validation failed: {'; '.join(errors)}")

    def get_aws_config(self) -> dict[str, str | None]:
        """Get AWS-specific configuration as a dictionary."""
        return {
            "region_name": self.AWS_REGION,
            "aws_access_key_id": config("AWS_ACCESS_KEY_ID", default=None),
            "aws_secret_access_key": config("AWS_SECRET_ACCESS_KEY", default=None),
            "aws_session_token": config("AWS_SESSION_TOKEN", default=None),
        }

    def get_dynamodb_config(self) -> dict[str, object]:
        """Get DynamoDB-specific configuration."""
        return {
            "region_name": self.AWS_REGION,
            "table_names": {
                "sessions": self.SESSIONS_TABLE_NAME,
                "turns": self.TURNS_TABLE_NAME,
                "players": self.PLAYERS_TABLE_NAME,
            },
        }

    def get_s3_config(self) -> dict[str, str]:
        """Get S3-specific configuration."""
        return {
            "region_name": self.AWS_REGION,
            "bucket_name": self.GAMEDATA_S3_BUCKET,
        }

    def get_logging_config(self) -> dict[str, object]:
        """Get logging-specific configuration."""
        return {
            "level": self.LOG_LEVEL,
            "json_logs": self.is_production,
            "include_stdlib": True,
            "aws_lambda_function": self.AWS_LAMBDA_FUNCTION_NAME,
            "aws_lambda_version": self.AWS_LAMBDA_FUNCTION_VERSION,
            "aws_region": self.AWS_REGION,
        }

    def __repr__(self) -> str:
        """String representation of settings (safe - no secrets)."""
        safe_attrs = [
            "AWS_REGION",
            "LOG_LEVEL",
            "IS_TEST_ENV",
            "IS_LAMBDA_ENV",
            "MAX_PLAYERS_PER_SESSION",
            "SESSION_TIMEOUT_HOURS",
            "DEBUG",
        ]
        attrs = {attr: getattr(self, attr) for attr in safe_attrs}
        return f"Settings({attrs})"


# Global settings instance
settings = Settings()


# Convenience functions for backward compatibility and ease of use
def get_aws_region() -> str:
    """Get AWS region setting."""
    return settings.AWS_REGION


def get_ses_region() -> str:
    """Get SES region setting."""
    return settings.SES_REGION


def is_test_environment() -> bool:
    """Check if running in test environment."""
    return settings.IS_TEST_ENV


def is_lambda_environment() -> bool:
    """Check if running in Lambda environment."""
    return settings.IS_LAMBDA_ENV


def is_production_environment() -> bool:
    """Check if running in production environment."""
    return settings.is_production


def get_log_level() -> str:
    """Get configured log level."""
    return settings.LOG_LEVEL


def get_table_names() -> dict[str, str]:
    """Get all DynamoDB table names."""
    return {
        "sessions": settings.SESSIONS_TABLE_NAME,
        "turns": settings.TURNS_TABLE_NAME,
        "players": settings.PLAYERS_TABLE_NAME,
    }


def get_s3_bucket() -> str:
    """Get S3 bucket name."""
    return settings.GAMEDATA_S3_BUCKET


# Validate settings on import (in production only)
if settings.is_production:
    try:
        settings.validate()
    except ValueError as e:
        # In production, configuration errors should be fatal
        raise RuntimeError(f"Configuration validation failed: {e}") from e
