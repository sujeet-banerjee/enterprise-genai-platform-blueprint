class Metrics:

    @staticmethod
    def context_precision(query=None, relevant_docs=None, retrieved_docs=None):
        '''
        Calculate context precision

        True precision = (relevant_docs ∩ retrieved_docs) / retrieved_docs
        However, Due to absence of ground truth, we approximate precision
        using query-document overlap. In your pipeline, you do NOT have
        relevant_docs, because:
        - no labeled dataset
        - no benchmark set
        - no human annotations
        👉 So the “correct formula” becomes impossible to compute.

        :param query: May be used for approximation of precision
        in absence of ground truth
        :param relevant_docs:
        :param retrieved_docs:
        :return:
        '''
        if not retrieved_docs:
            return 0

            # --- Mode 1: True IR evaluation (future) ---
        if relevant_docs is not None:
            intersection = set(relevant_docs) & set(retrieved_docs)
            return len(intersection) / len(retrieved_docs)

            # --- Mode 2: Query-based approximation (current) ---
        if query is not None:
            query_words = set(query.lower().split())

            retrieved_words = set()
            for doc in retrieved_docs:
                retrieved_words.update(doc.lower().split())

            if not query_words:
                return 0

            return len(query_words & retrieved_words) / len(query_words)

        raise ValueError("Either relevant_docs or query must be provided")


    @staticmethod
    def answer_relevance(similarity_score):

        return similarity_score


    @staticmethod
    def faithfulness(supported_claims, total_claims):

        if total_claims == 0:
            return 0

        return supported_claims / total_claims