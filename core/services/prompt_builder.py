import yaml


class PromptBuilder:

    def __init__(self, config_path: str):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        self.active_profile = config["active_prompt_profile"]
        profile_data = config["profiles"][self.active_profile]

        self.system_prompt = profile_data["system_prompt"]
        self.template = profile_data["template"]

    def build(self, query: str, docs: list) -> str:
        context = "\n".join([doc.content for doc in docs])

        return self.template.format(
            system_prompt=self.system_prompt,
            context=context,
            query=query
        )