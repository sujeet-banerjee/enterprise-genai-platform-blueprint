from core.config.generation_config import GenerationConfig
from core.interfaces.llm import BaseLLM


class DummyLLM(BaseLLM):

    def generate(self, prompt: str, config: GenerationConfig = None) -> str:
        return f"Dummy response for prompt: {prompt}, with config: {config}"

    @property
    def context_window(self) -> int:
        return 4096

    @property
    def model_name(self) -> str:
        return "dummy-llm"