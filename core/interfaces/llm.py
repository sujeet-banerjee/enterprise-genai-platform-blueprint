from abc import ABC, abstractmethod
from typing import List, Optional

from core.config.generation_config import GenerationConfig


class BaseLLM(ABC):
    """
    Contract for all LLM providers.
    """
    @abstractmethod
    def generate(self, prompt: str, config: Optional[GenerationConfig] = None) -> str:
        pass

    def generate_batch(
        self, prompts: List[str], config: Optional[GenerationConfig] = None
    ) -> List[str]:
        """
        Returns generated completions for multiple prompts (issue #27).

        Providers backed by a local HF pipeline override this to run all prompts
        through a single batched inference pass. The default keeps the
        single-item path alive so implementations stay interchangeable:
        ``generate_batch`` output is equivalent to
        ``[self.generate(p, config) for p in prompts]`` (in the same order).
        """
        return [self.generate(prompt, config) for prompt in prompts]

    @property
    @abstractmethod
    def context_window(self) -> int:
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass
