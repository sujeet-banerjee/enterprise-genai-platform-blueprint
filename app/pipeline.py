import time
from core.services.cost_tracker import CostTracker
from copy import deepcopy

class RAGPipeline:

    def __init__(self, embedder, retriever,
                 llm, prompt_builder, evaluator,
                 token_budget_service, generation_config,
                 cost_tracker):
        self.embedder = embedder
        self.prompt_builder = prompt_builder
        self.retriever = retriever
        self.llm = llm
        self.evaluator = evaluator
        self.cost_tracker = cost_tracker
        self.token_budget_service = token_budget_service
        self.generation_config = generation_config
        self._validate_contracts()


    def _validate_contracts(self):
        if self.embedder.dimension != self.retriever.index_dimension:
            raise ValueError("Embedding dimension mismatch with retriever index.")

    def run(self, query: str) -> dict:
        start_time = time.time()

        embedding = self.embedder.embed(query)
        docs = self.retriever.retrieve(embedding)

        prompt = self.prompt_builder.build(query, docs)
        # 🔥 Token Governance Hook
        budget = self.token_budget_service.compute_budget(
            query=query,
            retrieved_docs=docs,
            system_prompt="You are a helpful assistant.",
            context_window=self.llm.context_window,
            requested_max_tokens=self.generation_config.max_tokens
        )

        # Adjust generation config safely
        gen_config = deepcopy(self.generation_config)
        gen_config.max_tokens = budget["allowed_output_tokens"]
        response = self.llm.generate(prompt, gen_config)

        metrics = self.evaluator.evaluate(query, docs, response)
        cost = self.cost_tracker.compute(self.llm.model_name, start_time)

        return {
            "response": response,
            "retrieved_docs": [doc.content for doc in docs],
            "metrics": metrics,
            "cost": cost,
            "token_budget": budget
        }
