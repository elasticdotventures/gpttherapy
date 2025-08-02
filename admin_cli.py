#!/usr/bin/env python3
"""
GPTTherapy Admin CLI/TUI Tool

Admin interface for managing GPTTherapy sessions, logs, and infrastructure.
Supports CLI mode, TUI mode, and MCP server capability.

Usage:
    admin_cli.py sessions list                    # List all sessions
    admin_cli.py sessions show <session_id>       # Show session details
    admin_cli.py logs tail [--filter=*|game|session] [--lines=100]
    admin_cli.py logs dump [--filter=*|game|session] [--since=1h]
    admin_cli.py env generate                     # Generate .envrc from terraform
    admin_cli.py tui                             # Launch TUI interface
    admin_cli.py mcp                             # Run as MCP server

b00t Python patterns:
- uv for package management
- FastAPI for API endpoints (MCP server)
- DRY Python returns module for error handling
- Structured logging with proper exception chaining
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import click
import structlog
from botocore.exceptions import ClientError, NoCredentialsError
from returns.result import Failure, Result, Success

# Initialize structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class TerraformStateReader:
    """Read terraform state and outputs for environment configuration."""

    def __init__(self, terraform_dir: Path = Path("terraform")):
        self.terraform_dir = terraform_dir

    def get_outputs(self) -> Result[dict[str, Any], Exception]:
        """Get terraform outputs as dictionary."""
        try:
            result = subprocess.run(
                ["terraform", "output", "-json"],
                cwd=self.terraform_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            outputs = json.loads(result.stdout)
            # Extract values from terraform output format
            return Success(
                {key: value.get("value", value) for key, value in outputs.items()}
            )
        except subprocess.CalledProcessError as e:
            return Failure(RuntimeError(f"Terraform output failed: {e.stderr}"))
        except json.JSONDecodeError as e:
            return Failure(ValueError(f"Invalid JSON from terraform: {e}"))
        except Exception as e:
            return Failure(e)


class AWSResourceManager:
    """Manage AWS resources for GPTTherapy."""

    def __init__(self):
        self.session = boto3.Session()
        self._dynamodb = None
        self._logs = None
        self._lambda = None

    @property
    def dynamodb(self):
        if self._dynamodb is None:
            self._dynamodb = self.session.client(
                "dynamodb", region_name="ap-southeast-2"
            )
        return self._dynamodb

    @property
    def logs(self):
        if self._logs is None:
            self._logs = self.session.client("logs", region_name="ap-southeast-2")
        return self._logs

    @property
    def lambda_client(self):
        if self._lambda is None:
            self._lambda = self.session.client("lambda", region_name="ap-southeast-2")
        return self._lambda

    def list_sessions(self) -> Result[list[dict[str, Any]], Exception]:
        """List all sessions from DynamoDB."""
        try:
            response = self.dynamodb.scan(
                TableName="gpttherapy-sessions", Select="ALL_ATTRIBUTES"
            )
            return Success(response.get("Items", []))
        except ClientError as e:
            return Failure(RuntimeError(f"DynamoDB error: {e}"))
        except NoCredentialsError:
            return Failure(RuntimeError("AWS credentials not configured"))
        except Exception as e:
            return Failure(e)

    def get_session(self, session_id: str) -> Result[dict[str, Any] | None, Exception]:
        """Get specific session details."""
        try:
            response = self.dynamodb.get_item(
                TableName="gpttherapy-sessions", Key={"session_id": {"S": session_id}}
            )
            item = response.get("Item")
            return Success(item if item else None)
        except ClientError as e:
            return Failure(RuntimeError(f"DynamoDB error: {e}"))
        except Exception as e:
            return Failure(e)

    def get_logs(
        self, filter_pattern: str = "*", since_hours: int = 1, limit: int = 100
    ) -> Result[list[dict[str, Any]], Exception]:
        """Get CloudWatch logs for Lambda function."""
        try:
            log_group = "/aws/lambda/gpttherapy-handler"

            # Calculate start time
            start_time = int(
                (datetime.now() - timedelta(hours=since_hours)).timestamp() * 1000
            )

            # Build filter pattern based on filter type
            if filter_pattern == "game":
                pattern = '[timestamp, requestId, level="INFO", msg="*game*"]'
            elif filter_pattern == "session":
                pattern = '[timestamp, requestId, level="INFO", msg="*session*"]'
            else:
                pattern = ""  # No filter, show all

            response = self.logs.filter_log_events(
                logGroupName=log_group,
                startTime=start_time,
                filterPattern=pattern,
                limit=limit,
            )

            return Success(response.get("events", []))
        except ClientError as e:
            return Failure(RuntimeError(f"CloudWatch error: {e}"))
        except Exception as e:
            return Failure(e)


class EnvironmentGenerator:
    """Generate .envrc file from terraform state."""

    def __init__(self, terraform_reader: TerraformStateReader):
        self.terraform_reader = terraform_reader

    def generate_envrc(self) -> Result[str, Exception]:
        """Generate .envrc content from terraform outputs."""
        outputs_result = self.terraform_reader.get_outputs()

        if isinstance(outputs_result, Failure):
            return outputs_result

        outputs = outputs_result.unwrap()

        envrc_content = [
            "# Generated .envrc for GPTTherapy",
            "# Source: terraform outputs",
            f"# Generated: {datetime.now().isoformat()}",
            "",
        ]

        # Map terraform outputs to environment variables
        env_mappings = {
            "lambda_function_name": "LAMBDA_FUNCTION_NAME",
            "lambda_function_arn": "LAMBDA_FUNCTION_ARN",
            "gamedata_s3_bucket": "GAMEDATA_S3_BUCKET",
            "sessions_table": "SESSIONS_TABLE_NAME",
            "turns_table": "TURNS_TABLE_NAME",
            "players_table": "PLAYERS_TABLE_NAME",
        }

        for tf_key, env_var in env_mappings.items():
            if tf_key in outputs:
                envrc_content.append(f'export {env_var}="{outputs[tf_key]}"')

        # Add AWS region
        envrc_content.extend(
            [
                "",
                'export AWS_DEFAULT_REGION="ap-southeast-2"',
                'export AWS_REGION="ap-southeast-2"',
                "",
                "# Load AWS credentials if available",
                "if [[ -f ~/.aws/credentials ]]; then",
                '  export AWS_PROFILE="${AWS_PROFILE:-default}"',
                "fi",
            ]
        )

        return Success("\n".join(envrc_content))


# CLI Commands
@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
def cli(verbose: bool):
    """GPTTherapy Admin CLI - Manage sessions, logs, and infrastructure."""
    if verbose:
        structlog.configure(level="DEBUG")


@cli.group()
def sessions():
    """Session management commands."""
    pass


@sessions.command("list")
def sessions_list():
    """List all active sessions."""
    aws = AWSResourceManager()
    result = aws.list_sessions()

    match result:
        case Success(sessions):
            if not sessions:
                click.echo("No sessions found.")
                return

            click.echo(f"Found {len(sessions)} sessions:")
            for session in sessions:
                session_id = session.get("session_id", {}).get("S", "Unknown")
                game_type = session.get("game_type", {}).get("S", "Unknown")
                status = session.get("status", {}).get("S", "Unknown")
                created = session.get("created_at", {}).get("S", "Unknown")

                click.echo(f"  {session_id} | {game_type} | {status} | {created}")

        case Failure(error):
            click.echo(f"Error listing sessions: {error}", err=True)
            sys.exit(1)


@sessions.command("show")
@click.argument("session_id")
def sessions_show(session_id: str):
    """Show detailed information about a session."""
    aws = AWSResourceManager()
    result = aws.get_session(session_id)

    match result:
        case Success(session):
            if session is None:
                click.echo(f"Session {session_id} not found.")
                sys.exit(1)

            # Pretty print session data
            formatted = json.dumps(session, indent=2, default=str)
            click.echo(formatted)

        case Failure(error):
            click.echo(f"Error getting session: {error}", err=True)
            sys.exit(1)


@cli.group()
def logs():
    """CloudWatch logs management."""
    pass


@logs.command("tail")
@click.option(
    "--filter",
    "filter_type",
    default="*",
    type=click.Choice(["*", "game", "session"]),
    help="Filter logs by type",
)
@click.option("--lines", default=100, help="Number of lines to show")
def logs_tail(filter_type: str, lines: int):
    """Tail recent CloudWatch logs."""
    aws = AWSResourceManager()
    result = aws.get_logs(filter_pattern=filter_type, limit=lines)

    match result:
        case Success(events):
            if not events:
                click.echo("No log events found.")
                return

            for event in events[-lines:]:
                timestamp = datetime.fromtimestamp(event["timestamp"] / 1000)
                message = event["message"].strip()
                click.echo(f"{timestamp.isoformat()} | {message}")

        case Failure(error):
            click.echo(f"Error getting logs: {error}", err=True)
            sys.exit(1)


@logs.command("dump")
@click.option(
    "--filter",
    "filter_type",
    default="*",
    type=click.Choice(["*", "game", "session"]),
    help="Filter logs by type",
)
@click.option("--since", default="1h", help="Time range (e.g., 1h, 30m, 2d)")
def logs_dump(filter_type: str, since: str):
    """Dump logs to stdout."""
    # Parse since parameter
    import re

    match = re.match(r"(\d+)([hmd])", since)
    if not match:
        click.echo(
            "Invalid --since format. Use format like '1h', '30m', '2d'", err=True
        )
        sys.exit(1)

    amount, unit = match.groups()
    amount = int(amount)

    if unit == "h":
        since_hours = amount
    elif unit == "m":
        since_hours = amount / 60
    elif unit == "d":
        since_hours = amount * 24

    aws = AWSResourceManager()
    result = aws.get_logs(filter_pattern=filter_type, since_hours=since_hours)

    match result:
        case Success(events):
            for event in events:
                click.echo(event["message"].strip())

        case Failure(error):
            click.echo(f"Error dumping logs: {error}", err=True)
            sys.exit(1)


@cli.group()
def env():
    """Environment management."""
    pass


@env.command("generate")
@click.option("--output", "-o", default=".envrc", help="Output file path")
def env_generate(output: str):
    """Generate .envrc file from terraform state."""
    terraform_reader = TerraformStateReader()
    env_gen = EnvironmentGenerator(terraform_reader)

    result = env_gen.generate_envrc()

    match result:
        case Success(content):
            Path(output).write_text(content)
            click.echo(f"Generated {output}")
            click.echo("Run 'direnv allow' to load environment variables.")

        case Failure(error):
            click.echo(f"Error generating .envrc: {error}", err=True)
            sys.exit(1)


@cli.command()
def tui():
    """Launch TUI interface (placeholder for future implementation)."""
    click.echo("TUI mode not yet implemented.")
    click.echo("Use CLI commands for now:")
    click.echo("  admin_cli.py sessions list")
    click.echo("  admin_cli.py logs tail")


@cli.command()
def mcp():
    """Run as MCP server (placeholder for future implementation)."""
    click.echo("MCP server mode not yet implemented.")
    click.echo("Would start FastAPI server for MCP protocol.")


if __name__ == "__main__":
    cli()
