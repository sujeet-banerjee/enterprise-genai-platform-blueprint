from core.interfaces.embedder import BaseEmbedder


class DummyEmbedder(BaseEmbedder):

    def __init__(self, model_name: str = "dummy-embedder", dimension: int = 10):
        self._model_name = model_name
        self._dimension = int(dimension)

    def embed(self, text: str):
        return [0.1] * self._dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name
