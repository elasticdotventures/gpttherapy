"""
Email verification system for GPT Therapy.

Provides automated verification of SES email identities and health checks
for the email routing system.
"""

import json
import os
from typing import Any

import boto3
from botocore.exceptions import ClientError
from logging_config import get_logger
from settings import settings

logger = get_logger(__name__)


class EmailVerificationManager:
    """Manages SES email verification and health checks."""

    def __init__(self):
        self.ses_client = boto3.client("ses", region_name=settings.SES_REGION)
        self.lambda_client = boto3.client("lambda", region_name=settings.AWS_REGION)

    def verify_game_emails(self, games: list[str]) -> dict[str, Any]:
        """
        Verify SES email identities for all discovered games.

        Args:
            games: List of game types (e.g., ['dungeon', 'intimacy'])

        Returns:
            Verification status for each game email
        """
        results = {}

        for game in games:
            email = f"{game}@aws.promptexecution.com"
            results[game] = self._verify_single_email(email)

        return results

    def _verify_single_email(self, email: str) -> dict[str, Any]:
        """
        Verify a single SES email identity.

        Args:
            email: Email address to verify

        Returns:
            Verification status and details
        """
        try:
            # Check if email is already verified
            response = self.ses_client.get_identity_verification_attributes(
                Identities=[email]
            )

            verification_attrs = response.get("VerificationAttributes", {})
            email_attrs = verification_attrs.get(email, {})

            if email_attrs.get("VerificationStatus") == "Success":
                logger.info(f"Email {email} is already verified")
                return {
                    "email": email,
                    "status": "verified",
                    "verification_token": email_attrs.get("VerificationToken"),
                    "action": "none_required",
                }

            # Start verification process
            verify_response = self.ses_client.verify_email_identity(EmailAddress=email)

            logger.info(f"Started verification for {email}")
            return {
                "email": email,
                "status": "pending_verification",
                "message_id": verify_response.get("MessageId"),
                "action": "verification_email_sent",
            }

        except ClientError as e:
            error_code = e.response["Error"]["Code"]
            error_message = e.response["Error"]["Message"]

            logger.error(
                f"Failed to verify email {email}: {error_code} - {error_message}"
            )
            return {
                "email": email,
                "status": "error",
                "error_code": error_code,
                "error_message": error_message,
                "action": "manual_intervention_required",
            }

    def health_check_email_routing(self) -> dict[str, Any]:
        """
        Perform comprehensive health check of email routing system.

        Returns:
            Health check results
        """
        results = {
            "timestamp": json.dumps(None, default=str),
            "overall_status": "healthy",
            "checks": {},
        }

        # Check 1: SES service availability
        results["checks"]["ses_service"] = self._check_ses_service()

        # Check 2: Lambda function status
        results["checks"]["lambda_function"] = self._check_lambda_function()

        # Check 3: Domain verification
        results["checks"]["domain_verification"] = self._check_domain_verification()

        # Check 4: Receipt rules
        results["checks"]["receipt_rules"] = self._check_receipt_rules()

        # Determine overall status
        failed_checks = [
            check_name
            for check_name, check_result in results["checks"].items()
            if check_result.get("status") != "healthy"
        ]

        if failed_checks:
            results["overall_status"] = "unhealthy"
            results["failed_checks"] = failed_checks

        return results

    def _check_ses_service(self) -> dict[str, Any]:
        """Check SES service availability."""
        try:
            # Simple API call to verify SES is accessible
            response = self.ses_client.get_send_quota()
            return {
                "status": "healthy",
                "max_24_hour_send": response.get("Max24HourSend"),
                "max_send_rate": response.get("MaxSendRate"),
                "sent_last_24_hours": response.get("SentLast24Hours"),
            }
        except ClientError as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_lambda_function(self) -> dict[str, Any]:
        """Check Lambda function status."""
        try:
            function_name = os.environ.get(
                "AWS_LAMBDA_FUNCTION_NAME", "gpttherapy-handler"
            )
            response = self.lambda_client.get_function(FunctionName=function_name)

            config = response.get("Configuration", {})
            return {
                "status": "healthy",
                "function_name": config.get("FunctionName"),
                "runtime": config.get("Runtime"),
                "state": config.get("State"),
                "last_update_status": config.get("LastUpdateStatus"),
            }
        except ClientError as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_domain_verification(self) -> dict[str, Any]:
        """Check domain verification status."""
        try:
            domain = "aws.promptexecution.com"
            response = self.ses_client.get_identity_verification_attributes(
                Identities=[domain]
            )

            verification_attrs = response.get("VerificationAttributes", {})
            domain_attrs = verification_attrs.get(domain, {})

            return {
                "status": "healthy"
                if domain_attrs.get("VerificationStatus") == "Success"
                else "unhealthy",
                "domain": domain,
                "verification_status": domain_attrs.get("VerificationStatus"),
                "verification_token": domain_attrs.get("VerificationToken"),
            }
        except ClientError as e:
            return {"status": "unhealthy", "error": str(e)}

    def _check_receipt_rules(self) -> dict[str, Any]:
        """Check SES receipt rules configuration."""
        try:
            # List active rule sets
            response = self.ses_client.list_receipt_rule_sets()
            rule_sets = response.get("RuleSets", [])

            active_rule_sets = [rs for rs in rule_sets if rs.get("Name")]

            if not active_rule_sets:
                return {
                    "status": "unhealthy",
                    "error": "No active receipt rule sets found",
                }

            # Check for our specific rules
            rule_details = {}
            for rule_set in active_rule_sets:
                rule_set_name = rule_set["Name"]
                try:
                    rules_response = self.ses_client.describe_receipt_rule_set(
                        RuleSetName=rule_set_name
                    )
                    rules = rules_response.get("Rules", [])
                    rule_details[rule_set_name] = [
                        {
                            "name": rule.get("Name"),
                            "enabled": rule.get("Enabled"),
                            "recipients": rule.get("Recipients", []),
                        }
                        for rule in rules
                    ]
                except ClientError:
                    continue

            return {
                "status": "healthy",
                "active_rule_sets": len(active_rule_sets),
                "rule_details": rule_details,
            }

        except ClientError as e:
            return {"status": "unhealthy", "error": str(e)}

    def send_test_email(
        self, to_address: str, game_type: str = "dungeon"
    ) -> dict[str, Any]:
        """
        Send a test email to verify email routing.

        Args:
            to_address: Email address to send test to
            game_type: Game type for the test

        Returns:
            Test email results
        """
        try:
            from_address = f"{game_type}@aws.promptexecution.com"
            subject = f"GPT Therapy Email Routing Test - {game_type.title()}"

            body = f"""This is a test message to verify email routing for GPT Therapy.

Game Type: {game_type.title()}
From: {from_address}
To: {to_address}
Timestamp: {json.dumps(None, default=str)}

If you receive this email, the routing system is working correctly.

This is an automated test message from the GPT Therapy system.
"""

            response = self.ses_client.send_email(
                Source=from_address,
                Destination={"ToAddresses": [to_address]},
                Message={
                    "Subject": {"Data": subject},
                    "Body": {"Text": {"Data": body}},
                },
            )

            return {
                "status": "success",
                "message_id": response.get("MessageId"),
                "from_address": from_address,
                "to_address": to_address,
                "subject": subject,
            }

        except ClientError as e:
            return {
                "status": "error",
                "error_code": e.response["Error"]["Code"],
                "error_message": e.response["Error"]["Message"],
                "from_address": from_address if "from_address" in locals() else None,
                "to_address": to_address,
            }


def lambda_health_check_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """
    Lambda handler for health check endpoint.

    This can be invoked directly or via API Gateway for monitoring.
    """
    try:
        verifier = EmailVerificationManager()

        # Perform health check
        health_results = verifier.health_check_email_routing()

        # If test email is requested
        if event.get("test_email"):
            test_email_addr = event.get(
                "test_email_address", "admin@aws.promptexecution.com"
            )
            test_game = event.get("test_game_type", "dungeon")
            health_results["test_email"] = verifier.send_test_email(
                test_email_addr, test_game
            )

        return {
            "statusCode": 200 if health_results["overall_status"] == "healthy" else 503,
            "body": json.dumps(health_results, indent=2),
            "headers": {"Content-Type": "application/json"},
        }

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)

        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "overall_status": "error",
                    "error": str(e),
                    "timestamp": json.dumps(None, default=str),
                }
            ),
            "headers": {"Content-Type": "application/json"},
        }
