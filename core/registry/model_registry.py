import yaml
from core.implementations.dummy_llm import DummyLLM


class ModelRegistry:

    def __init__(self, config_path):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

    def get_active_model(self):

        model_name = self.config["active_model"]
        model_config = self.config["models"][model_name]

        if model_config["provider"] == "dummy":
            return DummyLLM()

        raise ValueError("Unknown provider")