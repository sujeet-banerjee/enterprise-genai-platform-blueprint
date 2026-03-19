from core.services.retrieval_policy_service import RetrievalPolicyService

def test_top_k_calculation():

    policy = RetrievalPolicyService(
        context_window=8000,
        system_prompt_tokens=500,
        # chunk_tokens=600,
        reserved_output_tokens=1000,
        safety_margin=200
    )

    top_k = policy.compute_top_k(
        query_tokens=200,
        avg_chunk_tokens=600)
    print("\nTop K results: ", top_k)
    assert top_k > 0
    assert isinstance(top_k, int)