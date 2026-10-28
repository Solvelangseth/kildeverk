"""Score a submitted answer against truth: numbers within tolerance, text by normalised match."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from eval.questions import Question

_NUMBER = re.compile(r"-?\d[\d\s,.]*")


def _norm(text: Any) -> str:
    text = unicodedata.normalize("NFKC", str(text)).casefold()
    return re.sub(r"[\s\-–.,:;!?'\"()]+", " ", text).strip()


def number(value: Any) -> float | None:
    """The first number in `value`, reading '5 594 340', '5,594,340', '11,7456' and '11.7456'."""

    if isinstance(value, int | float):
        return float(value)
    match = _NUMBER.search(str(value).replace(" ", " "))
    if not match:
        return None
    digits = match.group().strip().rstrip(".,").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", digits):
        digits = digits.replace(",", "")  # English thousands separators
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", digits):
        digits = digits.replace(".", "").replace(",", ".")  # Norwegian thousands with dots
    elif "," in digits and "." not in digits:
        digits = digits.replace(",", ".")  # decimal comma
    try:
        return float(digits)
    except ValueError:
        return None


def correct(question: Question, submitted: Any, truth: Any) -> bool:
    if question.kind == "number":
        got, want = number(submitted), float(truth)
        if got is None:
            return False
        if want == 0:
            return got == 0
        return abs(got - want) / abs(want) <= max(question.tolerance, 1e-9)
    got, want = _norm(submitted), _norm(truth)
    return bool(want) and re.search(rf"(^| ){re.escape(want)}( |$)", got) is not None
