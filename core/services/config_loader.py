import yaml

class ConfigLoader:

    def __init__(self, path: str):
        with open(path, "r") as f:
            self.config = yaml.safe_load(f)

    def get(self, key: str):
        return self.config.get(key)