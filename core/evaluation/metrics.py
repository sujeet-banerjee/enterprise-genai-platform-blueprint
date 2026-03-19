class Metrics:

    @staticmethod
    def context_precision(relevant_docs, retrieved_docs):

        if not retrieved_docs:
            return 0

        intersection = set(relevant_docs) & set(retrieved_docs)

        return len(intersection) / len(retrieved_docs)


    @staticmethod
    def answer_relevance(similarity_score):

        return similarity_score


    @staticmethod
    def faithfulness(supported_claims, total_claims):

        if total_claims == 0:
            return 0

        return supported_claims / total_claims