import yaml
from typing import List, Any, Union, Optional
from core.interfaces.retriever import Document


class PromptBuilder:
    """
    Constructs prompts based on external configuration profiles.
    RAGPipeline delegates prompt construction and system prompt retrieval to PromptBuilder.
    """

    def __init__(self, config_or_path: Union[str, dict] = "config/prompt_config.yaml", profile: Optional[str] = None):
        if isinstance(config_or_path, str):
            with open(config_or_path, "r") as f:
                self.config = yaml.safe_load(f) or {}
        else:
            self.config = config_or_path or {}

        self.active_profile = profile or self.config.get("active_prompt_profile", "default")
        self._load_profile(self.active_profile)

    def _load_profile(self, profile_name: str):
        profiles = self.config.get("profiles", {})
        if profile_name not in profiles:
            # Fallback to default or first available profile
            if "default" in profiles:
                profile_name = "default"
            elif profiles:
                profile_name = next(iter(profiles.keys()))
            else:
                self.system_prompt = "You are a helpful assistant."
                self.template = "{system_prompt}\n\nContext:\n{context}\n\nQuestion:\n{query}"
                return

        self.active_profile = profile_name
        profile_data = profiles[profile_name]
        self.system_prompt = profile_data.get("system_prompt", "You are a helpful assistant.")
        self.template = profile_data.get("template", "{system_prompt}\n\nContext:\n{context}\n\nQuestion:\n{query}")

    def set_profile(self, profile_name: str):
        self._load_profile(profile_name)

    def get_system_prompt(self) -> str:
        return self.system_prompt

    def build(self, query: str, docs: List[Any]) -> str:
        context_parts = []
        for doc in docs:
            if isinstance(doc, Document) or hasattr(doc, "content"):
                context_parts.append(doc.content)
            elif isinstance(doc, dict) and "content" in doc:
                context_parts.append(doc["content"])
            else:
                context_parts.append(str(doc))

        context = "\n".join(context_parts)

        return self.template.format(
            system_prompt=self.system_prompt.strip(),
            context=context,
            query=query
        )
