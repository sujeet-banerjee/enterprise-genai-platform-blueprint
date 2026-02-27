import time
from core.services.cost_tracker import CostTracker

class RAGPipeline:

    def __init__(self, embedder, retriever, llm, evaluator, cost_tracker=CostTracker()):
        self.embedder = embedder
        self.retriever = retriever
        self.llm = llm
        self.evaluator = evaluator
        self.cost_tracker = cost_tracker
        self._validate_contracts()

    def _validate_contracts(self):
        if self.embedder.dimension != self.retriever.index_dimension:
            raise ValueError("Embedding dimension mismatch with retriever index.")

    def _build_prompt(self, query, docs):
        context = "\n".join([doc.content for doc in docs])
        return f"Context:\n{context}\n\nQuestion: {query}"

    def run(self, query: str) -> dict:
        start_time = time.time()

        embedding = self.embedder.embed(query)
        docs = self.retriever.retrieve(embedding)

        prompt = self._build_prompt(query, docs)
        response = self.llm.generate(prompt)

        metrics = self.evaluator.evaluate(query, docs, response)
        cost = self.cost_tracker.compute(self.llm.model_name, start_time)

        return {
            "response": response,
            "retrieved_docs": [doc.content for doc in docs],
            "metrics": metrics,
            "cost": cost
        }
