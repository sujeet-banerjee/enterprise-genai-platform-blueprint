class CostGovernor:

    def __init__(self, max_cost_per_request):

        self.max_cost_per_request = max_cost_per_request


    def check_cost(self, cost):

        if cost > self.max_cost_per_request:
            raise ValueError("Cost threshold exceeded")

        return True