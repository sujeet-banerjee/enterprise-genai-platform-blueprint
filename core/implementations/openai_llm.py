from typing import Any, Dict, List, Optional

from openai import OpenAI

from core.config.generation_config import GenerationConfig
from core.interfaces.llm import BaseLLM


class OpenAILLM(BaseLLM):
    """
    OpenAI chat-completions provider. The model name and context window come
    from configuration (models.yaml via ModelRegistry), and GenerationConfig
    fields (temperature, max_tokens, top_p, stop, system_prompt) are mapped to
    the API request — nothing is hardcoded at call time (issue #13).
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "gpt-4o-mini",
        context_window: int = 128000,
        **_: Any,
    ):
        self.client = OpenAI(api_key=api_key)
        self._model_name = str(model_name)
        self._context_window = int(context_window)

    def generate(self, prompt: str, config: Optional[GenerationConfig] = None) -> str:
        messages: List[Dict[str, str]] = []
        system_prompt = getattr(config, "system_prompt", None)
        if system_prompt:
            messages.append({"role": "system", "content": str(system_prompt)})
            # PromptBuilder inlines {system_prompt} into the template; drop the
            # leading copy so instructions are not sent twice.
            if prompt.startswith(str(system_prompt)):
                prompt = prompt[len(str(system_prompt)):].lstrip()
        messages.append({"role": "user", "content": prompt})

        request: Dict[str, Any] = {"model": self._model_name, "messages": messages}
        if config is not None:
            if config.temperature is not None:
                request["temperature"] = float(config.temperature)
            if config.max_tokens:
                request["max_tokens"] = int(config.max_tokens)
            if config.top_p is not None:
                request["top_p"] = float(config.top_p)
            if config.stop:
                request["stop"] = config.stop

        response = self.client.chat.completions.create(**request)
        return response.choices[0].message.content

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def model_name(self) -> str:
        return self._model_name
