from core.interfaces.embedder import BaseEmbedder

class DummyEmbedder(BaseEmbedder):

    def embed(self, text: str):
        return [0.1] * 10

    @property
    def dimension(self):
        return 10