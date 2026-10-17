def test_pipeline_run_with_genuine_components(make_pipeline):
    pipeline = make_pipeline()
    result = pipeline.run("What is AI?")

    assert isinstance(result["response"], str)
    assert result["response"].strip()
    assert isinstance(result["retrieved_docs"], list)
    assert len(result["retrieved_docs"]) > 0
    assert isinstance(result["metrics"], dict)
    assert isinstance(result["cost"], dict)
    assert isinstance(result["token_budget"], dict)


def test_pipeline_retrieves_relevant_document(make_pipeline):
    pipeline = make_pipeline()
    result = pipeline.run("What are neural networks?")

    retrieved = " ".join(result["retrieved_docs"]).lower()
    assert "neural" in retrieved or "brain" in retrieved


def test_pipeline_response_is_grounded_in_context(make_pipeline):
    pipeline = make_pipeline()
    result = pipeline.run("What is machine learning?")

    response = result["response"].lower()
    assert "learning" in response or "data" in response or "ai" in response
