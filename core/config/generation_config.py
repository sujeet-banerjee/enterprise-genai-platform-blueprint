from dataclasses import dataclass
from typing import Optional


@dataclass
class GenerationConfig:
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 256
    stop: Optional[list[str]] = None
    # Optional chat-system role; set per-request by the pipeline from
    # PromptBuilder so providers can emit a distinct system message.
    system_prompt: Optional[str] = None