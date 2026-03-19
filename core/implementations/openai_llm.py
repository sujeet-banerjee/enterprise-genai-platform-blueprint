from core.interfaces.llm import BaseLLM


class OpenAILLM(BaseLLM):

    def __init__(self, api_key):
        self.api_key = api_key


    def generate(self, prompt, config=None):
        # placeholder
        return "OpenAI response"


    @property
    def context_window(self):
        return 128000


    @property
    def model_name(self):
        return "openai-gpt"