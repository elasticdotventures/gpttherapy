"""
Pytest configuration and shared fixtures for GPT Therapy tests.

This module provides centralized test configuration, including environment
setup that works with our new centralized settings system.
"""

import os
import pytest
from unittest.mock import patch

# CRITICAL: Set test environment variables IMMEDIATELY before any imports
# This ensures the settings module picks up test values when it's imported
TEST_ENV_VARS = {
    'AWS_REGION': 'us-east-1',
    'IS_TEST_ENV': 'true',
    'SESSIONS_TABLE_NAME': 'test-gpttherapy-sessions',
    'TURNS_TABLE_NAME': 'test-gpttherapy-turns',  
    'PLAYERS_TABLE_NAME': 'test-gpttherapy-players',
    'GAMEDATA_S3_BUCKET': 'test-gpttherapy-gamedata',
    'SES_REGION': 'us-east-1',
    'LOG_LEVEL': 'DEBUG',
    'DEBUG': 'true',
    'AWS_LAMBDA_FUNCTION_NAME': '',  # Not in Lambda during tests
}

# Set environment variables immediately
for key, value in TEST_ENV_VARS.items():
    os.environ[key] = value


@pytest.fixture(scope="session", autouse=True)
def configure_test_environment():
    """Configure test environment variables before any tests run."""
    # Update environment variables
    original_env = {}
    for key, value in TEST_ENV_VARS.items():
        original_env[key] = os.environ.get(key)
        os.environ[key] = value
    
    # Force reload of settings module to pick up test environment
    import importlib
    import sys
    if 'src.settings' in sys.modules:
        importlib.reload(sys.modules['src.settings'])
    
    yield
    
    # Restore original environment
    for key, original_value in original_env.items():
        if original_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original_value


@pytest.fixture(scope="session")
def test_settings():
    """Provide test settings instance with proper configuration."""
    # Import after environment is configured
    from src.settings import Settings
    
    # Create fresh settings instance for tests
    settings = Settings()
    
    # Validate test configuration
    assert settings.IS_TEST_ENV is True
    assert settings.AWS_REGION == 'us-east-1'
    assert settings.SESSIONS_TABLE_NAME == 'test-gpttherapy-sessions'
    assert settings.DEBUG is True
    
    return settings


@pytest.fixture
def mock_settings():
    """Provide a mock settings object that can be modified per test."""
    from src.settings import Settings
    
    with patch('src.settings.settings') as mock_settings_obj:
        # Set up default test values
        mock_settings_obj.AWS_REGION = 'us-east-1'
        mock_settings_obj.SES_REGION = 'us-east-1'
        mock_settings_obj.IS_TEST_ENV = True
        mock_settings_obj.IS_LAMBDA_ENV = False
        mock_settings_obj.DEBUG = True
        mock_settings_obj.LOG_LEVEL = 'DEBUG'
        mock_settings_obj.SESSIONS_TABLE_NAME = 'test-gpttherapy-sessions'
        mock_settings_obj.TURNS_TABLE_NAME = 'test-gpttherapy-turns'
        mock_settings_obj.PLAYERS_TABLE_NAME = 'test-gpttherapy-players'
        mock_settings_obj.GAMEDATA_S3_BUCKET = 'test-gpttherapy-gamedata'
        mock_settings_obj.MAX_PLAYERS_PER_SESSION = 8
        mock_settings_obj.SESSION_TIMEOUT_HOURS = 48
        mock_settings_obj.AI_MODEL_NAME = 'anthropic.claude-3-haiku-20240307-v1:0'
        mock_settings_obj.AI_MAX_TOKENS = 2000
        mock_settings_obj.AI_TEMPERATURE = 0.7
        
        # Add properties
        mock_settings_obj.is_production = False
        mock_settings_obj.is_development = True
        
        yield mock_settings_obj


@pytest.fixture
def reset_settings_cache():
    """Reset any cached settings between tests."""
    # Clear any module-level caches if needed
    yield
    # Cleanup after test


@pytest.fixture(autouse=True)
def isolate_tests():
    """Ensure tests don't interfere with each other."""
    # Clear any global state that might persist between tests
    yield
    # Cleanup after each test


# Add markers for different test categories
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
    config.addinivalue_line(
        "markers", "aws: mark test as requiring AWS services"
    )


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add default markers."""
    for item in items:
        # Add default markers based on test path/name
        if "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
        elif "test_" in item.name and not any(mark.name in ["integration", "slow"] for mark in item.iter_markers()):
            item.add_marker(pytest.mark.unit)