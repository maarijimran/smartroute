"""Automatic task scores A in [0, 1]. They run locally and need no model.

These are lexical proxies. They are good at ranking answers to extractive
questions and weak on free-form summaries, which is why the reward gives the
blinded human rating 0.7 of the weight whenever one exists.
"""

import re
import string
from collections import Counter

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_PUNCT = str.maketrans("", "", string.punctuation)
_NO_ANSWER = re.compile(
    r"\b(unanswerable|not answerable|cannot be answered|can ?not answer|no answer|not (?:stated|mentioned|"
    r"specified|provided|discussed|given)|does not (?:say|mention|state|specify|contain|provide)|"
    r"do not (?:contain|mention|provide)|insufficient information|not enough information)\b",
    re.I,
)
_YES = re.compile(r"^\W*(yes|yeah|correct|true)\b", re.I)
_NO = re.compile(r"^\W*(no|nope|false|incorrect)\b", re.I)


def normalize(text: str) -> list[str]:
    """SQuAD-style normalisation: lower-case, strip punctuation and articles."""
    text = _ARTICLES.sub(" ", text.lower().translate(_PUNCT))
    return text.split()


def token_f1(prediction: str, gold: str) -> float:
    pred, ref = normalize(prediction), normalize(gold)
    if not pred or not ref:
        return float(pred == ref)
    overlap = sum((Counter(pred) & Counter(ref)).values())
    if overlap == 0:
        return 0.0
    precision, recall = overlap / len(pred), overlap / len(ref)
    return 2 * precision * recall / (precision + recall)


def token_recall(prediction: str, reference: str) -> float:
    pred, ref = Counter(normalize(prediction)), Counter(normalize(reference))
    total = sum(ref.values())
    return sum((pred & ref).values()) / total if total else 0.0


def says_unanswerable(prediction: str) -> bool:
    return bool(_NO_ANSWER.search(prediction))


def score_answer(prediction: str, golds: list[str], unanswerable: bool = False, kind: str = "doc_qa") -> float:
    """
    doc_qa        best token F1 over the gold answers; yes/no golds are matched on the
                  answer's opening word; unanswerable golds score 1 only if the answer
                  says the document does not contain the answer.
    summary/explain   unigram recall of the reference summary, discounted when the
                  answer is far longer than the reference (padding is not coverage).
    """
    prediction = prediction or ""
    if unanswerable:
        return float(says_unanswerable(prediction))
    if not golds:
        return 0.0
    if kind in ("summary", "explain"):
        reference = golds[0]
        recall = token_recall(prediction, reference)
        length_ratio = len(normalize(prediction)) / max(len(normalize(reference)), 1)
        return recall / max(1.0, length_ratio / 2)  # no penalty up to twice the reference length
    best = 0.0
    for gold in golds:
        g = gold.strip().lower()
        if g in ("yes", "no"):
            match = _YES.search(prediction) if g == "yes" else _NO.search(prediction)
            best = max(best, float(bool(match)))
        else:
            best = max(best, token_f1(prediction, gold))
    return best
