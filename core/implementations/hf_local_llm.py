from typing import Any, Dict, List, Optional

from core.config.generation_config import GenerationConfig
from core.implementations._local_models import get_text_generation_pipeline
from core.interfaces.llm import BaseLLM


class LocalHFLLM(BaseLLM):
    """
    Genuine LLM backed by a locally-loaded HuggingFace text-generation model.

    No API key is required: weights are downloaded once from the HuggingFace Hub
    and cached locally, then every call runs real inference on CPU. The pipeline
    is loaded lazily on first use and shared process-wide via ``_local_models``.

    ``max_new_tokens`` bounds generation latency on CPU by capping whatever token
    budget the caller requests.
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-0.5B-Instruct",
        context_window: int = 32768,
        max_new_tokens: int = 128,
        **_: Any,
    ):
        self._model_name = model_name
        self._context_window = int(context_window)
        self._max_new_tokens = int(max_new_tokens)
        self._pipeline: Optional[Any] = None

    def _ensure_pipeline(self) -> Any:
        if self._pipeline is None:
            self._pipeline = get_text_generation_pipeline(self._model_name)
        return self._pipeline

    def generate(self, prompt: str, config: Optional[GenerationConfig] = None) -> str:
        pipe = self._ensure_pipeline()
        gen_kwargs = self._gen_kwargs(config)
        outputs = pipe([{"role": "user", "content": prompt}], **gen_kwargs)
        return self._extract_text(outputs)

    def generate_batch(
        self, prompts: List[str], config: Optional[GenerationConfig] = None
    ) -> List[str]:
        """
        Run all prompts through one batched HF inference pass (issue #27).

        HF's text-generation pipeline accepts a list of message-lists and returns
        one output per input, so ordering matches ``prompts``. An empty input
        short-circuits to avoid a needless model call.
        """
        if not prompts:
            return []
        pipe = self._ensure_pipeline()
        gen_kwargs = self._gen_kwargs(config)
        conversations = [[{"role": "user", "content": prompt}] for prompt in prompts]
        outputs = pipe(conversations, **gen_kwargs)
        # Batched pipelines return one inner list per conversation.
        return [self._extract_text(output) for output in outputs]

    def _gen_kwargs(self, config: Optional[GenerationConfig]) -> Dict[str, Any]:
        requested = int(getattr(config, "max_tokens", 256) or 256)
        max_new_tokens = max(1, min(requested, self._max_new_tokens))
        temperature = float(getattr(config, "temperature", 0.0) or 0.0)
        top_p = float(getattr(config, "top_p", 1.0) or 1.0)

        gen_kwargs: Dict[str, Any] = {"max_new_tokens": max_new_tokens}
        if temperature > 0.0:
            gen_kwargs.update(do_sample=True, temperature=temperature, top_p=top_p)
        else:
            gen_kwargs.update(do_sample=False)
        return gen_kwargs

    @staticmethod
    def _extract_text(outputs: Any) -> str:
        # Tolerate both shapes returned by the HF pipeline: a list of result
        # dicts (single call) or a single result mapping.
        if isinstance(outputs, dict):
            first: Any = outputs
        else:
            if not outputs:
                return ""
            first = outputs[0]
        generated = first.get("generated_text", "")
        if isinstance(generated, list):
            if not generated:
                return ""
            return str(generated[-1].get("content", ""))
        return str(generated)

    @property
    def context_window(self) -> int:
        return self._context_window

    @property
    def model_name(self) -> str:
        return self._model_name
