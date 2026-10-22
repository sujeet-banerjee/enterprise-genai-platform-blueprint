"""PII detectors (Workstream B3, issue #54).

Two implementations ship:

- :class:`RegexPiiDetector` - the default. Pure stdlib, no extra dependency,
  covers email / phone / credit card (Luhn validated) / national id / IP.
- :class:`NerPiiDetector` - optional, wraps an injected entity extractor so
  personal names and postal addresses can be detected. The extractor is
  injected, which keeps the class testable without a model; the optional
  spaCy-backed extractor is built by :func:`build_spacy_ner_detector` and is
  only imported when an operator explicitly enables it.

Neither implementation logs or stores matched values.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional, Sequence

from core.interfaces.pii import (
    DEFAULT_PII_CLASSES,
    NER_PII_CLASSES,
    PII_ADDRESS,
    PII_CREDIT_CARD,
    PII_EMAIL,
    PII_IP_ADDRESS,
    PII_NATIONAL_ID,
    PII_PERSON_NAME,
    PII_PHONE,
    PiiDetector,
    PiiMatch,
    class_priority,
    resolve_overlaps,
)


class PiiDependencyError(RuntimeError):
    """Raised when an optional PII dependency is requested but unavailable."""


def luhn_valid(digits: str) -> bool:
    """Validate a card number with the Luhn checksum."""
    if not digits or not digits.isdigit():
        return False
    numbers = [int(char) for char in digits]
    checksum = 0
    parity = len(numbers) % 2
    for index, number in enumerate(numbers):
        if index % 2 == parity:
            number *= 2
            if number > 9:
                number -= 9
        checksum += number
    return checksum % 10 == 0


class RegexPiiDetector(PiiDetector):
    """Deterministic regex detector for the standard PII classes.

    ``classes`` selects which classes are reported (per-class toggles).
    ``national_id_patterns`` replaces the built-in national-id pattern, so an
    operator can match their own scheme (e.g. a national health number).
    ``extra_patterns`` maps a class name to additional regex strings.

    Overlapping matches are resolved by class priority (see
    :data:`core.interfaces.pii.PII_CLASS_PRIORITY`), so a national id is never
    reported as a phone number and a card number is never split apart.
    """

    _EMAIL = r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
    _CREDIT_CARD = r"(?<![\w\-])\d(?:[ \-]?\d){12,18}(?![\w\-])"
    _NATIONAL_ID = r"\b\d{3}-\d{2}-\d{4}\b"
    _IP_V4 = r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    _IP_V6 = r"\b(?:[A-Fa-f0-9]{0,4}:){2,7}[A-Fa-f0-9]{0,4}\b"
    _PHONE_INTL = (
        r"(?<![\w\-])\+\d{1,3}[\s.\-]?(?:\(\d{1,4}\)[\s.\-]?)?"
        r"\d{2,4}(?:[\s.\-]\d{2,4}){1,4}(?![\d\-])"
    )
    _PHONE_PAREN = r"(?<![\w\-])\(\d{3}\)\s?\d{3}[\s.\-]\d{4}(?![\d\-])"
    _PHONE_GROUPED = r"(?<![\w\-])\d{3}[\s.\-]\d{3}[\s.\-]\d{4}(?![\d\-])"
    _PHONE_PLAIN = r"(?<![\w\-])\d{10}(?![\d\-])"

    _DEFAULT_PATTERNS: Dict[str, Sequence[str]] = {
        PII_EMAIL: (_EMAIL,),
        PII_CREDIT_CARD: (_CREDIT_CARD,),
        PII_NATIONAL_ID: (_NATIONAL_ID,),
        PII_PHONE: (_PHONE_INTL, _PHONE_PAREN, _PHONE_GROUPED, _PHONE_PLAIN),
        PII_IP_ADDRESS: (_IP_V4, _IP_V6),
    }

    def __init__(
        self,
        classes: Optional[Sequence[str]] = None,
        national_id_patterns: Optional[Sequence[str]] = None,
        extra_patterns: Optional[Dict[str, Sequence[str]]] = None,
    ):
        # ``None`` means "the default classes"; an explicit empty list means
        # "detect nothing" (used to disable PII scrubbing deliberately).
        source = DEFAULT_PII_CLASSES if classes is None else classes
        selected = [str(c).strip().lower() for c in source]
        self.classes: Sequence[str] = tuple(c for c in selected if c)
        self._extra_patterns: Dict[str, Sequence[str]] = {
            str(key).strip().lower(): tuple(str(v) for v in (value or []))
            for key, value in (extra_patterns or {}).items()
        }

        self._compiled: Dict[str, List["re.Pattern[str]"]] = {}
        for pii_class in self.classes:
            raw_patterns = list(self._DEFAULT_PATTERNS.get(pii_class, ()))
            if pii_class == PII_NATIONAL_ID and national_id_patterns:
                raw_patterns = [str(p) for p in national_id_patterns]
            raw_patterns.extend(self._extra_patterns.get(pii_class, ()))
            self._compiled[pii_class] = [
                re.compile(pattern) for pattern in raw_patterns if pattern
            ]

    def detect(self, text: str) -> List[PiiMatch]:
        if not text or not isinstance(text, str):
            return []

        found: List[PiiMatch] = []
        for pii_class in sorted(self.classes, key=class_priority):
            for pattern in self._compiled.get(pii_class, []):
                for match in pattern.finditer(text):
                    value = match.group(0)
                    if pii_class == PII_CREDIT_CARD:
                        digits = re.sub(r"[ \-]", "", value)
                        if not (13 <= len(digits) <= 19) or not luhn_valid(digits):
                            continue
                    found.append(
                        PiiMatch(
                            pii_class=pii_class,
                            start=match.start(),
                            end=match.end(),
                            value=value,
                        )
                    )

        accepted = resolve_overlaps(found)
        return accepted


class NerPiiDetector(PiiDetector):
    """Optional NER-backed detector for names and addresses.

    ``entity_extractor`` is any callable returning
    ``(label, start, end, text)`` tuples - spaCy's ``doc.ents`` is the
    canonical example. Injecting it keeps this class dependency free and
    unit-testable; the model itself is an operator choice.
    """

    _LABEL_TO_CLASS = {
        "person": PII_PERSON_NAME,
        "person_name": PII_PERSON_NAME,
        "name": PII_PERSON_NAME,
        "gpe": PII_ADDRESS,
        "loc": PII_ADDRESS,
        "location": PII_ADDRESS,
        "address": PII_ADDRESS,
    }

    def __init__(
        self,
        entity_extractor: Callable[[str], Sequence[Any]],
        classes: Optional[Sequence[str]] = None,
    ):
        if entity_extractor is None:
            raise ValueError("NerPiiDetector requires an entity_extractor callable")
        self._entity_extractor = entity_extractor
        selected = [str(c).strip().lower() for c in (classes or NER_PII_CLASSES)]
        self.classes: Sequence[str] = tuple(c for c in selected if c)

    def detect(self, text: str) -> List[PiiMatch]:
        if not text or not isinstance(text, str):
            return []

        found: List[PiiMatch] = []
        for entity in self._entity_extractor(text) or []:
            label, start, end, value = self._unpack(entity)
            pii_class = self._LABEL_TO_CLASS.get(str(label).strip().lower())
            if pii_class is None or pii_class not in self.classes:
                continue
            found.append(
                PiiMatch(
                    pii_class=pii_class,
                    start=int(start),
                    end=int(end),
                    value=str(value),
                )
            )
        return found

    @staticmethod
    def _unpack(entity: Any) -> tuple:
        """Accept spaCy-like spans, plain tuples or objects with the same shape."""
        if isinstance(entity, (tuple, list)) and len(entity) >= 4:
            return str(entity[0]), int(entity[1]), int(entity[2]), str(entity[3])
        label = getattr(entity, "label_", None) or getattr(entity, "label", None)
        start = getattr(entity, "start_char", None)
        end = getattr(entity, "end_char", None)
        text = getattr(entity, "text", None)
        if label is None or start is None or end is None:
            raise ValueError(f"Unsupported NER entity shape: {entity!r}")
        return str(label), int(start), int(end), str(text or "")


class CompositePiiDetector(PiiDetector):
    """Combine several detectors (e.g. regex + optional NER) into one.

    Matches from all sub-detectors are merged and de-overlapped by class
    priority, so the result is a single ordered list of spans.
    """

    def __init__(self, detectors: Sequence[PiiDetector]):
        self._detectors = [d for d in (detectors or []) if d is not None]
        merged: List[str] = []
        for detector in self._detectors:
            for pii_class in detector.classes:
                if pii_class not in merged:
                    merged.append(str(pii_class))
        self.classes: Sequence[str] = tuple(merged)

    def detect(self, text: str) -> List[PiiMatch]:
        if not text or not isinstance(text, str):
            return []
        found: List[PiiMatch] = []
        for detector in self._detectors:
            found.extend(detector.detect(text))
        return resolve_overlaps(found)


def build_pii_detector(
    classes: Optional[Sequence[str]] = None,
    national_id_patterns: Optional[Sequence[str]] = None,
    extra_patterns: Optional[Dict[str, Sequence[str]]] = None,
    ner: Optional[Dict[str, Any]] = None,
) -> PiiDetector:
    """Build the detector for a PII policy.

    Regex detection is the default and needs no extra dependency. The optional
    NER detector is only built when ``ner`` is explicitly enabled - it is an
    opt-in extra, so an operator who asks for it gets a clear failure when the
    dependency is missing rather than a silent downgrade.
    """
    selected = [str(c).strip().lower() for c in (classes or DEFAULT_PII_CLASSES)]
    selected = [c for c in selected if c]

    ner_options = dict(ner or {})
    ner_enabled = bool(ner_options.get("enabled", False))

    detectors: List[PiiDetector] = []
    if ner_enabled:
        ner_classes = [
            str(c).strip().lower()
            for c in (ner_options.get("classes") or sorted(NER_PII_CLASSES))
        ]
        detectors.append(
            build_spacy_ner_detector(
                model=str(ner_options.get("model", "en_core_web_sm")),
                classes=ner_classes,
            )
        )
        regex_classes = [c for c in selected if c not in NER_PII_CLASSES]
    else:
        regex_classes = list(selected)

    if regex_classes:
        detectors.append(
            RegexPiiDetector(
                classes=regex_classes,
                national_id_patterns=national_id_patterns,
                extra_patterns=extra_patterns,
            )
        )

    if not detectors:
        return RegexPiiDetector(classes=[])
    if len(detectors) == 1:
        return detectors[0]
    return CompositePiiDetector(detectors)


def build_spacy_ner_detector(
    model: str = "en_core_web_sm",
    classes: Optional[Sequence[str]] = None,
) -> NerPiiDetector:
    """Build a spaCy-backed NER detector (optional dependency).

    Raises :class:`PiiDependencyError` with an actionable message when spaCy
    or the requested model is unavailable - the operator explicitly asked for
    NER, so failing fast beats silently degrading to regex-only detection.
    """
    try:
        import spacy  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - depends on optional extra
        raise PiiDependencyError(
            "spaCy is required for the optional NER PII detector. "
            'Install it with: pip install "spacy" && python -m spacy download '
            f"{model}"
        ) from exc

    try:
        nlp = spacy.load(model)
    except Exception as exc:  # pragma: no cover - depends on optional extra
        raise PiiDependencyError(
            f"spaCy model '{model}' is not available. "
            f'Install it with: python -m spacy download {model}'
        ) from exc

    def _extract(text: str) -> List[tuple]:
        doc = nlp(text)
        return [(ent.label_, ent.start_char, ent.end_char, ent.text) for ent in doc.ents]

    return NerPiiDetector(entity_extractor=_extract, classes=classes)
