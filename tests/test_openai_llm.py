import pytest
from unittest.mock import patch

from core.implementations.openai_llm import OpenAILLM


def test_generate_returns_text():

    llm = OpenAILLM(api_key="fake_key")

    mock_response = {
        "choices": [
            {
                "message": {
                    "content": "OpenAI response"
                }
            }
        ]
    }

    with patch("core.implementations.openai_llm.OpenAILLM") as mock_openai:

        mock_client = mock_openai.return_value
        mock_client.chat.completions.create.return_value = mock_response

        result = llm.generate("Hello")

        assert result == "OpenAI response"