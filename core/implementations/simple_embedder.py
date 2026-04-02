from sentence_transformers import SentenceTransformer

from core.interfaces.embedder import BaseEmbedder


class SimpleEmbedder(BaseEmbedder):

    def __init__(self):
        self.model = SentenceTransformer("all-MiniLM-L6-v2")
        # TODO read from configs
        #self.dimension = 384

    def embed(self, text: str):
        return self.model.encode(text).tolist()

    @property
    def dimension(self) -> int:
        return 384