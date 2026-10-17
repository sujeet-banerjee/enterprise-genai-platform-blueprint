from typing import List

from openai import OpenAI

from core.interfaces.embedder import BaseEmbedder


class OpenAIEmbedder(BaseEmbedder):
    """
    Genuine embedding provider backed by the OpenAI Embeddings API.

    Requires an API key. Dimension is inferred from the model id (or supplied
    explicitly) so it stays consistent with the retriever index.
    """

    _DIMENSIONS = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(
        self,
        api_key: str,
        model_name: str = "text-embedding-3-small",
        dimension: int | None = None,
    ):
        self._client = OpenAI(api_key=api_key)
        self._model_name = model_name
        self._dimension = int(dimension) if dimension else self._DIMENSIONS.get(model_name, 1536)

    def embed(self, text: str) -> List[float]:
        response = self._client.embeddings.create(model=self._model_name, input=text)
        return [float(value) for value in response.data[0].embedding]

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model_name(self) -> str:
        return self._model_name
