from core.interfaces.llm import BaseLLM
from openai import OpenAI

class OpenAILLM(BaseLLM):

    def __init__(self, api_key):
        self.client = OpenAI(api_key=api_key)

    def generate(self, prompt, config=None):
        # placeholder for now.
        # TODO Implement this
        response = self.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}]
        )

        return response.choices[0].message.content


    @property
    def context_window(self):
        return 128000


    @property
    def model_name(self):
        return "openai-gpt"