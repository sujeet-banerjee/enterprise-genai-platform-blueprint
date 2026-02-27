from core.interfaces.evaluator import BaseEvaluator


class DummyEvaluator(BaseEvaluator):

    def evaluate(self, query, retrieved_docs, response):
        return {
            "faithfulness": 0.9,
            "retrieval_recall": 0.8
        }