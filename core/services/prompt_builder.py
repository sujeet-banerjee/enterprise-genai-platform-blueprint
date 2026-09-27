from pathlib import Path
from typing import Dict, List, Optional, Union
import yaml

from core.interfaces.retriever import Document


class PromptBuilder:
    """
    Configuration-driven prompt construction service.
    Loads prompt profiles, system prompts, and formatting templates from config/prompt_config.yaml.
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        profile: Optional[str] = None,
    ):
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "prompt_config.yaml"
            config_path = str(default_path)

        self.config_path = config_path
        with open(self.config_path, "r") as f:
            self.config = yaml.safe_load(f) or {}

        self.profiles: Dict[str, dict] = self.config.get("profiles") or {}
        if not self.profiles:
            raise ValueError(f"No prompt profiles found in configuration file: {self.config_path}")

        initial_profile = profile or self.config.get("active_prompt_profile", "default")
        self.set_profile(initial_profile)

    def set_profile(self, profile_name: str) -> None:
        if profile_name not in self.profiles:
            raise ValueError(
                f"Unknown prompt profile '{profile_name}'. Available profiles: {list(self.profiles.keys())}"
            )
        self.active_profile = profile_name
        profile_data = self.profiles[self.active_profile]
        self.system_prompt: str = str(profile_data.get("system_prompt", "")).strip()
        self.template: str = str(profile_data.get("template", "{system_prompt}\n\nContext:\n{context}\n\nQuestion:\n{query}"))
        self.context_separator: str = str(profile_data.get("context_separator", "\n"))
        self.empty_context_message: str = str(profile_data.get("empty_context_message", ""))

    def get_system_prompt(self, profile: Optional[str] = None) -> str:
        if profile is not None:
            if profile not in self.profiles:
                raise ValueError(f"Unknown prompt profile '{profile}'.")
            return str(self.profiles[profile].get("system_prompt", "")).strip()
        return self.system_prompt

    def list_profiles(self) -> List[str]:
        return list(self.profiles.keys())

    @staticmethod
    def _extract_content(doc: Union[Document, dict, str]) -> str:
        if isinstance(doc, Document):
            return doc.content
        if isinstance(doc, dict):
            return str(doc.get("content", ""))
        return str(doc)

    def build(
        self,
        query: str,
        docs: Optional[List[Union[Document, dict, str]]] = None,
        profile: Optional[str] = None,
    ) -> str:
        if profile is not None and profile != self.active_profile:
            if profile not in self.profiles:
                raise ValueError(f"Unknown prompt profile '{profile}'.")
            p_data = self.profiles[profile]
            sys_prompt = str(p_data.get("system_prompt", "")).strip()
            tmpl = str(p_data.get("template", self.template))
            sep = str(p_data.get("context_separator", self.context_separator))
            empty_msg = str(p_data.get("empty_context_message", self.empty_context_message))
        else:
            sys_prompt = self.system_prompt
            tmpl = self.template
            sep = self.context_separator
            empty_msg = self.empty_context_message

        doc_texts = [self._extract_content(doc) for doc in (docs or []) if self._extract_content(doc)]
        context = sep.join(doc_texts) if doc_texts else empty_msg

        return tmpl.format(
            system_prompt=sys_prompt,
            context=context,
            query=query,
        )
