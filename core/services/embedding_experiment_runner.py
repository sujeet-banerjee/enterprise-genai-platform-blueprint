from typing import List, Dict, Any, Optional, Union
from core.interfaces.retriever import Document
from core.implementations.simple_embedder import SimpleEmbedder
from core.implementations.simple_retriever import SimpleRetriever
from core.evaluation.evaluation_engine import EvaluationEngine
from core.evaluation.metrics import Metrics
from core.registry.model_registry import ModelRegistry


class EmbeddingExperimentRunner:
    """
    Runs comparative evaluations across multiple embedding models.
    Captures:
    - embedding model name
    - embedding dimension
    - retrieved documents
    - retrieval scores
    - evaluation metrics
    """

    def __init__(
        self,
        model_registry: Optional[ModelRegistry] = None,
        evaluator: Optional[EvaluationEngine] = None
    ):
        self.model_registry = model_registry or ModelRegistry("config/models.yaml")
        self.evaluator = evaluator or EvaluationEngine(Metrics())

    def compare_models(
        self,
        docs: List[Union[dict, Document]],
        query: str,
        models: Optional[List[str]] = None,
        top_k: int = 3
    ) -> Dict[str, Any]:
        target_models = models or [
            "sentence-transformers/all-MiniLM-L6-v2",
            "sentence-transformers/all-mpnet-base-v2"
        ]

        experiment_results = []

        for model_name in target_models:
            embedder = SimpleEmbedder(model_name=model_name)
            retriever = SimpleRetriever(docs=docs, embedder=embedder)

            query_vector = embedder.embed(query)
            scored_docs = retriever.retrieve_with_scores(query_vector, top_k=top_k)

            retrieved_docs_list = [doc for doc, _ in scored_docs]
            retrieval_scores_list = [score for _, score in scored_docs]

            # Generate dummy response for metric evaluation
            response_text = " ".join([d.content for d in retrieved_docs_list])
            metrics = self.evaluator.evaluate(query, retrieved_docs_list, response_text)

            experiment_results.append({
                "embedding_model": model_name,
                "embedding_dimension": embedder.dimension,
                "retrieved_documents": [doc.content for doc in retrieved_docs_list],
                "retrieval_scores": retrieval_scores_list,
                "metrics": metrics
            })

        return {
            "query": query,
            "top_k": top_k,
            "experiments": experiment_results
        }
