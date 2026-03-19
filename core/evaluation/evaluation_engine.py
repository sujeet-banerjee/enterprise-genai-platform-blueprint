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

        # FIXME stuffed values for now.
        """
        TODO structure around:
        
        results = {}
        ...
        results["context_precision"] = self.metrics.context_precision(...)
        results["answer_relevance"] = self.metrics.answer_relevance(...)
        results["faithfulness"] = self.metrics.faithfulness(...)
        ...
        """

        return {
            "context_precision": 0.75,
            "answer_relevance": 0.8,
            "faithfulness": 0.9
        }