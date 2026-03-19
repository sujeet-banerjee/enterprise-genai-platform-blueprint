class EvaluationEngine:

    def __init__(self, metrics):
        self.metrics = metrics

    def evaluate(self, query, docs, response):
        '''
        :param query: 
        :param docs: 
        :param response: 
        :return: 
        '''
        # TODO Calculate the relevant docs

        # temporary assumption
        relevant_docs = docs

        # FIXME: Dummy placeholders for now
        similarity_score = 0.8
        supported_claims = 9
        total_claims = 10

        return {
            "context_precision": self.metrics.context_precision(relevant_docs, docs),
            "answer_relevance": self.metrics.answer_relevance(similarity_score),
            "faithfulness": self.metrics.faithfulness(supported_claims, total_claims)
        }