from abc import ABC, abstractmethod
from typing import List


class BaseQueryExpander(ABC):
    """Contract for query expansion / multi-query retrieval.

    An expander turns a single user query into one or more query variants that are
    each retrieved against, after which the pipeline merges and de-duplicates the
    results. The original query MUST be included in the output (typically first)
    so behaviour degrades gracefully and the retrieved set always contains the
    verbatim-query results.
    """

    @abstractmethod
    def expand(self, query: str) -> List[str]:
        """Return the original query plus zero or more variants (original first)."""
        pass
