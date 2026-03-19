import pytest
from core.services.cost_governor import CostGovernor


def test_cost_within_limit():
    governor = CostGovernor(max_cost_per_request=5.0)
    assert governor.check_cost(2.0) is True

def test_cost_exceeds_limit():
    governor = CostGovernor(max_cost_per_request=5.0)
    with pytest.raises(ValueError):
        governor.check_cost(10.0)