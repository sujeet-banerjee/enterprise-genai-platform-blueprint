import yaml
from core.implementations.dummy_llm import DummyLLM
from core.implementations.openai_llm import OpenAILLM


class ModelRegistry:

    def __init__(self, config_path):
        self.config_path = config_path
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

    def get_active_model(self):
        model_name = self.config["active_model"]
        if model_name not in self.config["models"]:
            raise ValueError(
                f"Invalid model: {model_name}; no such model ",
                f"found in config file: {self.config_path}")

        model_config = self.config["models"][model_name]
        provider = model_config["provider"]

        # TODO Replace if-else with a Registry Map.
        if provider == "dummy":
            return DummyLLM()
        elif provider == "openai":
            return OpenAILLM(api_key="dummy")  # temp

        raise ValueError(f"Unknown provider: {provider}")