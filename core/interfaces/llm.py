from abc import ABC, abstractmethod
from core.config.generation_config import GenerationConfig

class BaseLLM(ABC):
    """
    Contract for all LLM providers.
    """
    @abstractmethod
    def generate(self, prompt: str, config: GenerationConfig = None) -> str:
        pass

    @property
    @abstractmethod
    def context_window(self) -> int:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass