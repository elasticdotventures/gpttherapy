"""
Lambda entry point stub for GPT Therapy.

This file exists at the root level and imports the actual handler
from the src package, avoiding relative import issues.
"""

from src.lambda_function import lambda_handler

# AWS Lambda will call this function
__all__ = ["lambda_handler"]
