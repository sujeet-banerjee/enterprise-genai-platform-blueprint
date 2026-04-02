from core.evaluation.metrics import Metrics


def test_context_precision_query_mode():

    docs = ["AI is intelligence", "ML is learning"]
    query = "What is AI"

    score = Metrics.context_precision(
        retrieved_docs=docs,
        query=query
    )
    print(score)

    assert score >= 0