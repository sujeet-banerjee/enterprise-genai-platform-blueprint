"""PII / DLP contracts (Workstream B3, issue #54).

The B1 guardrail framework (#52) gives the pipeline an ordered input/output
safety seam. This module adds the *vocabulary* the DLP feature needs so the
contract stays in the interface layer and concrete detectors remain swappable:

- :data:`PII_EMAIL` and friends - the detectable PII classes.
- :class:`PiiMatch` - a detected span. ``value`` holds the raw match so a
  caller can rewrite the text; it must **never** be logged, traced or audited.
- :class:`PiiDetector` - the detection contract.
- :func:`apply_pii_masks` - pure helper that rewrites text, used by both the
  guardrail (ingress/egress enforcement) and the trace/log redactor.

Detection order matters: when two classes match overlapping spans the class
with the higher priority (see :data:`PII_CLASS_PRIORITY`) wins, so a national
id is never reported as a phone number.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence

#: Email address.
PII_EMAIL = "email"
#: Telephone number.
PII_PHONE = "phone"
#: Payment card number (Luhn validated).
PII_CREDIT_CARD = "credit_card"
#: Government / national identifier (SSN-like by default, configurable).
PII_NATIONAL_ID = "national_id"
#: IPv4 / IPv6 address.
PII_IP_ADDRESS = "ip_address"
#: Personal name (requires the optional NER detector).
PII_PERSON_NAME = "person_name"
#: Postal address (requires the optional NER detector).
PII_ADDRESS = "address"

#: Classes enabled by default. All are regex based and need no extra
#: dependency; the NER-only classes are opt-in.
DEFAULT_PII_CLASSES: Sequence[str] = (
    PII_EMAIL,
    PII_PHONE,
    PII_CREDIT_CARD,
    PII_NATIONAL_ID,
    PII_IP_ADDRESS,
)

#: Classes that can only be produced by the optional NER detector.
NER_PII_CLASSES = frozenset({PII_PERSON_NAME, PII_ADDRESS})

#: Detection priority - earlier entries win when two matches overlap.
PII_CLASS_PRIORITY: Sequence[str] = (
    PII_EMAIL,
    PII_CREDIT_CARD,
    PII_NATIONAL_ID,
    PII_IP_ADDRESS,
    PII_PHONE,
    PII_PERSON_NAME,
    PII_ADDRESS,
)


def mask_token(pii_class: str) -> str:
    """Default replacement token for a PII class (``[REDACTED_EMAIL]``)."""
    return "[REDACTED_{}]".format(str(pii_class).strip().upper())


def class_priority(pii_class: str) -> int:
    """Sort key for :data:`PII_CLASS_PRIORITY` (unknown classes sort last)."""
    try:
        return PII_CLASS_PRIORITY.index(pii_class)
    except ValueError:
        return len(PII_CLASS_PRIORITY)


@dataclass
class PiiMatch:
    """A detected PII span.

    ``value`` is the raw matched text. It exists so the caller can rewrite the
    source string; issue #54 requires that it is never persisted, logged,
    traced or audited - only the class and a count may leave this object.
    """

    pii_class: str
    start: int
    end: int
    value: str

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


class PiiDetector(ABC):
    """Contract for a PII detector.

    Implementations must be side-effect free and must never raise for
    ordinary text; unexpected failures are handled by the caller.
    """

    #: Classes this detector can report.
    classes: Sequence[str] = DEFAULT_PII_CLASSES

    @abstractmethod
    def detect(self, text: str) -> List[PiiMatch]:
        """Return the PII spans found in ``text`` (possibly empty)."""
        raise NotImplementedError


def apply_pii_masks(
    text: str,
    matches: Sequence[PiiMatch],
    mask: Optional[str] = None,
) -> str:
    """Replace every matched span in ``text`` with a redaction token.

    ``mask`` overrides the per-class default token. Overlapping matches are
    resolved in favour of the higher-priority class so the rewritten text
    stays consistent. The original string is returned unchanged when there is
    nothing to mask.
    """
    if not text or not matches:
        return text

    resolved = resolve_overlaps(matches)
    if not resolved:
        return text

    # Rewrite right-to-left so earlier offsets stay valid.
    rewritten = text
    for match in sorted(resolved, key=lambda m: m.start, reverse=True):
        token = mask if mask else mask_token(match.pii_class)
        rewritten = rewritten[: match.start] + token + rewritten[match.end :]
    return rewritten


def resolve_overlaps(matches: Sequence[PiiMatch]) -> List[PiiMatch]:
    """Drop matches that overlap an already accepted, higher-priority match.

    A national id is therefore never reported as a phone number, and a card
    number is never split into fragments.
    """
    ordered = sorted(
        matches,
        key=lambda m: (class_priority(m.pii_class), m.start, -m.length),
    )
    accepted: List[PiiMatch] = []
    for candidate in ordered:
        if any(
            candidate.start < existing.end and existing.start < candidate.end
            for existing in accepted
        ):
            continue
        accepted.append(candidate)
    return sorted(accepted, key=lambda m: m.start)


def summarize_matches(matches: Sequence[PiiMatch]) -> Dict[str, int]:
    """Counts per PII class - safe to log/trace/audit (no raw values)."""
    counts: Dict[str, int] = {}
    for match in matches:
        counts[match.pii_class] = counts.get(match.pii_class, 0) + 1
    return {key: counts[key] for key in sorted(counts)}
