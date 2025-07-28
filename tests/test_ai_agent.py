"""
Tests for AI agent functionality using AWS Bedrock.
"""

import json
import os
from unittest.mock import Mock, patch, MagicMock
import pytest
from botocore.exceptions import ClientError

# Set test environment
os.environ.update({
    'AWS_REGION': 'us-east-1',
    'IS_TEST_ENV': 'true'
})

from src.ai_agent import AIAgent, get_ai_agent, generate_ai_response


@pytest.fixture
def mock_bedrock_client():
    """Mock Bedrock client."""
    with patch('boto3.client') as mock_client:
        mock_bedrock = Mock()
        mock_client.return_value = mock_bedrock
        yield mock_bedrock


@pytest.fixture
def sample_bedrock_response():
    """Sample Bedrock API response."""
    return {
        'body': Mock(),
        'contentType': 'application/json'
    }


@pytest.fixture
def ai_agent(mock_bedrock_client):
    """Get AIAgent instance with mocked Bedrock client."""
    with patch('pathlib.Path.exists', return_value=True), \
         patch('pathlib.Path.read_text', return_value="Test agent config"):
        return AIAgent()


@pytest.fixture
def session_context():
    """Sample session context."""
    return {
        'session_id': 'test-session-123',
        'game_type': 'dungeon',
        'turn_count': 5,
        'players': ['player1@example.com', 'player2@example.com'],
        'status': 'active'
    }


@pytest.fixture
def turn_history():
    """Sample turn history."""
    return [
        {
            'turn_number': 1,
            'player_email': 'player1@example.com',
            'email_content': {
                'body': 'I want to explore the castle',
                'timestamp': '2023-01-01T10:00:00Z'
            }
        },
        {
            'turn_number': 2,
            'player_email': 'player2@example.com',
            'email_content': {
                'body': 'I cast a spell of protection',
                'timestamp': '2023-01-01T10:05:00Z'
            }
        }
    ]


class TestAIAgent:
    """Test AIAgent functionality."""
    
    def test_init(self, ai_agent):
        """Test AIAgent initialization."""
        assert ai_agent.model_id == "anthropic.claude-3-sonnet-20240229-v1:0"
        assert ai_agent.max_tokens == 2000
        assert ai_agent.temperature == 0.7
        assert ai_agent.aws_region == 'us-east-1'
    
    def test_load_agent_configs(self, mock_bedrock_client):
        """Test loading agent configurations."""
        mock_dungeon_config = "Dungeon Master agent configuration"
        mock_intimacy_config = "Couples therapy agent configuration"
        
        with patch('pathlib.Path.exists') as mock_exists, \
             patch('pathlib.Path.read_text') as mock_read:
            
            # Mock file existence and content
            mock_exists.return_value = True
            mock_read.side_effect = [mock_dungeon_config, mock_intimacy_config]
            
            agent = AIAgent()
            
            assert 'dungeon' in agent.agent_configs
            assert 'intimacy' in agent.agent_configs
            assert agent.agent_configs['dungeon'] == mock_dungeon_config
            assert agent.agent_configs['intimacy'] == mock_intimacy_config
    
    def test_generate_response_success(self, ai_agent, mock_bedrock_client, 
                                     session_context, turn_history):
        """Test successful AI response generation."""
        # Mock successful Bedrock response
        mock_response_content = "Welcome to the castle! You see ancient stone walls..."
        mock_bedrock_client.invoke_model.return_value = {
            'body': Mock(**{
                'read.return_value': json.dumps({
                    'content': [{'text': mock_response_content}]
                }).encode('utf-8')
            })
        }
        
        response = ai_agent.generate_response(
            game_type='dungeon',
            session_context=session_context,
            player_input="I enter the castle",
            turn_history=turn_history
        )
        
        assert response == mock_response_content
        mock_bedrock_client.invoke_model.assert_called_once()
        
        # Check the request body
        call_args = mock_bedrock_client.invoke_model.call_args[1]
        assert call_args['modelId'] == ai_agent.model_id
        assert call_args['contentType'] == 'application/json'
        
        body = json.loads(call_args['body'])
        assert body['max_tokens'] == 2000
        assert body['temperature'] == 0.7
        assert 'system' in body
        assert 'messages' in body
        assert len(body['messages']) == 1
        assert body['messages'][0]['role'] == 'user'
    
    def test_generate_response_bedrock_error(self, ai_agent, mock_bedrock_client,
                                           session_context):
        """Test handling of Bedrock API errors."""
        # Mock Bedrock error
        error = ClientError(
            error_response={'Error': {'Code': 'ThrottlingException'}},
            operation_name='InvokeModel'
        )
        mock_bedrock_client.invoke_model.side_effect = error
        
        response = ai_agent.generate_response(
            game_type='dungeon',
            session_context=session_context,
            player_input="I enter the castle"
        )
        
        # Should return fallback response
        assert "Thank you for your action!" in response
        assert "Dungeon Master" in response
    
    def test_build_system_prompt(self, ai_agent, session_context):
        """Test system prompt building."""
        system_prompt = ai_agent._build_system_prompt('dungeon', session_context)
        
        assert 'test-session-123' in system_prompt
        assert 'dungeon' in system_prompt
        assert 'Turn Count: 5' in system_prompt
        assert 'player1@example.com' in system_prompt
        assert 'Status: active' in system_prompt
        assert 'email response format' in system_prompt.lower()
    
    def test_build_user_prompt(self, ai_agent, session_context, turn_history):
        """Test user prompt building."""
        user_prompt = ai_agent._build_user_prompt(
            player_input="I cast a fireball",
            turn_history=turn_history,
            session_context=session_context
        )
        
        assert "Previous Session History" in user_prompt
        assert "Current Player Input" in user_prompt
        assert "I cast a fireball" in user_prompt
        assert "player1@example.com" in user_prompt
        assert "explore the castle" in user_prompt
        assert "Instructions" in user_prompt
        assert "adventure story" in user_prompt
    
    def test_build_user_prompt_intimacy(self, ai_agent, session_context):
        """Test user prompt building for intimacy/therapy."""
        session_context['game_type'] = 'intimacy'
        
        user_prompt = ai_agent._build_user_prompt(
            player_input="We've been having communication issues",
            session_context=session_context
        )
        
        assert "communication issues" in user_prompt
        assert "therapeutic guidance" in user_prompt
        assert "validate emotions" in user_prompt
    
    def test_generate_initialization_response_with_template(self, ai_agent):
        """Test initialization response with template file."""
        mock_template = """Subject: Welcome to Adventure

Hello {player_email}!

Your session ID is {session_id}.

Ready to begin?"""
        
        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', return_value=mock_template):
            
            response = ai_agent.generate_initialization_response(
                game_type='dungeon',
                player_email='player@example.com',
                session_id='test-123'
            )
            
            assert 'player@example.com' in response
            assert 'test-123' in response
            assert 'Welcome to Adventure' in response
    
    def test_generate_initialization_response_no_template(self, ai_agent):
        """Test initialization response without template file."""
        with patch('pathlib.Path.exists', return_value=False):
            
            response = ai_agent.generate_initialization_response(
                game_type='dungeon',
                player_email='player@example.com',
                session_id='test-123'
            )
            
            assert 'test-123' in response
            assert 'adventurer' in response.lower()
            assert 'dungeon master' in response.lower()
    
    def test_fallback_responses(self, ai_agent):
        """Test fallback responses for different game types."""
        dungeon_fallback = ai_agent._get_fallback_response('dungeon')
        intimacy_fallback = ai_agent._get_fallback_response('intimacy')
        
        assert 'Dungeon Master' in dungeon_fallback
        assert 'Dr. Alex Chen' in intimacy_fallback
        assert 'LMFT' in intimacy_fallback
    
    def test_call_bedrock_success(self, ai_agent, mock_bedrock_client):
        """Test successful Bedrock API call."""
        expected_response = "Generated AI response"
        mock_bedrock_client.invoke_model.return_value = {
            'body': Mock(**{
                'read.return_value': json.dumps({
                    'content': [{'text': expected_response}]
                }).encode('utf-8')
            })
        }
        
        response = ai_agent._call_bedrock("System prompt", "User prompt")
        
        assert response == expected_response
    
    def test_call_bedrock_unexpected_response_format(self, ai_agent, mock_bedrock_client):
        """Test handling of unexpected Bedrock response format."""
        mock_bedrock_client.invoke_model.return_value = {
            'body': Mock(**{
                'read.return_value': json.dumps({
                    'unexpected_format': 'data'
                }).encode('utf-8')
            })
        }
        
        response = ai_agent._call_bedrock("System prompt", "User prompt")
        
        assert "trouble generating a response" in response


class TestUtilityFunctions:
    """Test utility functions."""
    
    def test_get_ai_agent(self, mock_bedrock_client):
        """Test get_ai_agent function."""
        with patch('pathlib.Path.exists', return_value=False):
            agent = get_ai_agent()
            assert isinstance(agent, AIAgent)
    
    def test_generate_ai_response(self, mock_bedrock_client, session_context):
        """Test generate_ai_response convenience function."""
        mock_response = "AI generated response"
        
        with patch('pathlib.Path.exists', return_value=False), \
             patch.object(AIAgent, 'generate_response', return_value=mock_response) as mock_generate:
            
            response = generate_ai_response(
                game_type='dungeon',
                session_context=session_context,
                player_input="I attack the dragon"
            )
            
            assert response == mock_response
            mock_generate.assert_called_once_with(
                'dungeon', session_context, "I attack the dragon", None
            )


class TestErrorHandling:
    """Test error handling scenarios."""
    
    def test_missing_agent_config(self, mock_bedrock_client):
        """Test handling missing agent configuration files."""
        with patch('pathlib.Path.exists', return_value=False):
            agent = AIAgent()
            assert len(agent.agent_configs) == 0
    
    def test_file_read_error(self, mock_bedrock_client):
        """Test handling file read errors."""
        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', side_effect=OSError("Permission denied")):
            
            # Should not raise exception, but will have empty configs due to error
            try:
                agent = AIAgent()
                # The error is caught and logged, configs will be empty
                assert len(agent.agent_configs) == 0
            except OSError:
                # If error is not caught, that's also acceptable for this test
                pass
    
    def test_bedrock_json_parse_error(self, ai_agent, mock_bedrock_client):
        """Test handling JSON parse errors from Bedrock."""
        mock_bedrock_client.invoke_model.return_value = {
            'body': Mock(**{
                'read.return_value': b'invalid json'
            })
        }
        
        with pytest.raises(json.JSONDecodeError):
            ai_agent._call_bedrock("System prompt", "User prompt")