class RetrievalPolicyService:
    '''
    Retrieval depth governed by token economics
    '''
    def __init__(
        self,
        context_window,
        system_prompt_tokens,
        reserved_output_tokens,
        safety_margin=200
    ):
        '''

        :param context_window:
        :param system_prompt_tokens:
        :param reserved_output_tokens:
        :param safety_margin:
        '''
        self.context_window = context_window
        self.system_prompt_tokens = system_prompt_tokens
        self.reserved_output_tokens = reserved_output_tokens
        self.safety_margin = safety_margin

    def compute_top_k(self,
                      query_tokens:int,
                      avg_chunk_tokens:int):

        available_tokens = (
            self.context_window
            - self.system_prompt_tokens
            - query_tokens
            - self.reserved_output_tokens
            - self.safety_margin
        )

        if available_tokens <= 0:
            return 1

        return max(1, available_tokens // avg_chunk_tokens)