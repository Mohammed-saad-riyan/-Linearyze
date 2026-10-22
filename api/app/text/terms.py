"""Search terms: normalized tokens, stopwords removed, light stemming.

Postgres' `simple` text search config does no stemming, which hurts Arabic badly: "المعرض"
and "معرض" are different tokens. These light rules (strip the article and common
conjunction/preposition prefixes, a few plural suffixes) follow Larkey's light10 closely
enough for exhibition correspondence. They are applied identically at index time and
query time, which is what matters.
"""

import re

from app.text.arabic import normalize

_TOKEN = re.compile(r"[a-z0-9ء-ي]+(?:[-/][a-z0-9ء-ي]+)*")

_EN_STOP = set(
    "a an and are as at be by did do does for from give had has have how i in is it its "
    "me my of on or our please show tell than that the their them there these this those "
    "to us was we were what when where which who why will with you your can could find "
    "list send get about any all one".split()
)
_AR_STOP = {
    normalize(w)
    for w in (
        "في من إلى على عن مع هل ما ماذا متى كم كيف أين التي الذي الذين هذا هذه ذلك تلك "
        "هو هي هم نحن أنا لنا لي لدينا كان كانت يكون أن إن أو ثم قد لقد عند بعد قبل "
        "أعطني اعرض أرسل ابحث أريد يوم اليوم فيه فيها به بها"
    ).split()
}

_AR_PREFIXES = ("وال", "بال", "كال", "فال", "لل", "ال")
_AR_SUFFIXES = ("ات", "ون", "ين", "ان", "ها", "يه", "ه")


def stem(token: str) -> str:
    if token.isascii():
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            return token[:-1]
        return token
    for prefix in _AR_PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 2:
            token = token[len(prefix) :]
            break
    else:
        if token.startswith("و") and len(token) > 4:
            token = token[1:]
    for suffix in _AR_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            return token[: -len(suffix)]
    return token


def terms(text: str) -> list[str]:
    """Content terms of `text` in order, duplicates kept."""
    out = []
    for token in _TOKEN.findall(normalize(text)):
        if token in _EN_STOP or token in _AR_STOP:
            continue
        out.append(stem(token))
    return out


def search_text(text: str) -> str:
    """What goes into chunks.tsv: the stemmed terms, space separated."""
    return " ".join(terms(text))


def or_tsquery(text: str) -> str | None:
    """A to_tsquery() string matching any term, or None if the text has no terms.

    Terms are restricted to [a-z0-9 Arabic letters - /] by _TOKEN, and '-' and '/' are
    replaced, so nothing here can be parsed as tsquery syntax.
    """
    unique = dict.fromkeys(t.replace("-", " ").replace("/", " ") for t in terms(text))
    parts = [p for t in unique for p in t.split()]
    return " | ".join(parts) if parts else None


def coverage(query_terms: list[str], passage_terms: set[str]) -> float:
    """Fraction of distinct query terms present in the passage."""
    distinct = set(query_terms)
    if not distinct:
        return 0.0
    return len(distinct & passage_terms) / len(distinct)
