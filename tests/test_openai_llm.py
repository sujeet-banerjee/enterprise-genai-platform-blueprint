import pytest
from unittest.mock import patch, MagicMock

from core.implementations.openai_llm import OpenAILLM

def test_generate_handles_empty_response():

    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:

        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = []

        mock_client.chat.completions.create.return_value = mock_response

        llm = OpenAILLM(api_key="fake")

        with pytest.raises(Exception):
            llm.generate("Hello")

def test_generate_returns_text():
    '''
    generate()
         → OpenAI() → mock_client
         → mock_client.chat.completions.create()
         → mock_response
         → extract content
    :return:
    '''
    with patch("core.implementations.openai_llm.OpenAI") as mock_openai:
        # Create mock client instance
        mock_client = MagicMock()
        mock_openai.return_value = mock_client

        # Mock API response
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="Mock response")
            )
        ]
        mock_client.chat.completions.create.return_value = mock_response

        # Run test
        llm = OpenAILLM(api_key="fake_key")
        result = llm.generate("Hello")

        assert result == "Mock response"