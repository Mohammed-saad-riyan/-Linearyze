"""Rule-based stand-in for the grading model, used when no Anthropic key is configured.

It exists so the pipeline, tests and CI run without network access. It understands the
phrasings in eval/golden_assistant.yaml and little else; the live grader is the product.
Organisation names are resolved later against org_aliases, so this only has to find the
phrase that names the organisation.
"""

import datetime as dt
import re

from app.assistant.grade_types import DependentLookup, Filters, GradeResult, Scores
from app.text.arabic import normalize

_DR_VERBS = (
    r"^(give me|show me|find|open|send me|get me|pull up|i need|list|where is|which letters?)\b"
    r"|^(اعطني|اعرض|ابحث عن|ارسل لي|اريد|افتح|اين|هات)(\s|$)"
)
_IR_START = (
    r"^(what|when|how|who|which|is|are|does|do|did|can|why)\b"
    r"|^(ما|ماذا|متي|كم|كيف|من هو|هل|لماذا|ما هي|ما هو)(\s|$)"
)
_OFF_TOPIC = r"\b(joke|weather|poem|recipe|football|horoscope)\b|نكته|الطقس|قصيده|وصفه طبخ"

_DOC_TYPES = [
    (r"\bletters?\b|خطاب|رساله|تعميم", "letter"),
    (r"\bapplications?\b|طلب تصريح", "application"),
    (r"\b(contracts?|agreements?)\b|عقد|اتفاقيه", "contract"),
    (r"\bprice lists?\b|قائمه اسعار", "price_list"),
    (r"\bcost sheets?\b|كشف تكاليف", "cost_sheet"),
    (r"\bmemos?\b|مذكره", "memo"),
    (r"\bpolic(y|ies)\b|سياسه", "policy"),
]

_INCOMING = r"\b(received|we got|incoming|sent us|sent to us)\b|استلمنا|وصلنا|الوارد|الوارده|ورد"

_DEPENDS = [
    (
        r"(?:on )?the (?:same )?day (?:that )?we (submitted|sent) (?:the )?(.+?)[?.]?$",
        "submitted_date",
    ),
    (r"(?:في )?(?:نفس )?اليوم الذي (?:قدمنا|ارسلنا|سلمنا) فيه (.+?)[?.؟]?$", "submitted_date"),
]

_VERSION = [
    (r"\b(version|v)\s?(\d+)\b", None),
    (r"\b(first|original|earlier|previous|old) version\b", 1),
    (r"(الاصدار|النسخه) (الاول|الاولي|السابق|القديم)", 1),
]


def requested_version(text: str) -> int | None:
    """A document version the text asks for ("version 1", "the original version",
    "النسخة الأولى"), or None for the latest. Shared with the advisor's plan."""
    q = normalize(text)
    for pattern, fixed in _VERSION:
        match = re.search(pattern, q)
        if match:
            return fixed if fixed is not None else int(match.group(2))
    return None


# Cues start at a word boundary: an unanchored "ل" once matched inside "طلب" and cut the
# topic short. A bare "ل" prefix is not a cue at all; too many words begin with it.
_SENDER_CUE = (
    r"(?:^|\s)(?:from|by|sent by|issued by|من|الوارد من|الصادر من|المرسل من)\s+(?:the\s+)?"
)
_CLIENT_CUE = r"(?:^|\s)(?:for|with|of|signed with|with client|مع|الخاص ب|الخاصه ب)\s+|(?:^|\s)لـ"


def _find_after(cue: str, text: str) -> tuple[str, tuple[int, int]] | None:
    match = re.search(f"(?:{cue})" + r"([^,.?؟،]+)", text)
    return (match.group(1).strip(), match.span()) if match else None


def grade_offline(query: str) -> GradeResult:
    q = normalize(query)
    filters = Filters()
    depends_on = None

    for pattern, doc_type in _DOC_TYPES:
        if re.search(pattern, q):
            filters.doc_type = doc_type  # type: ignore[assignment]
            break
    if re.search(_INCOMING, q):
        filters.direction = "incoming"

    for pattern, field in _DEPENDS:
        match = re.search(pattern, q)
        if match:
            title = match.group(match.lastindex or 1)
            depends_on = DependentLookup(
                find_title=title,
                use_field=field,
                as_field="received_date",
            )
            q_head = q[: match.start()]
            break
    else:
        q_head = q

    topic = q_head
    found = _find_after(_SENDER_CUE, q_head)
    if found:
        filters.sender = found[0]
    else:
        found = _find_after(_CLIENT_CUE, q_head)
        if found:
            filters.client = found[0]
    if found:
        # The organisation phrase is a filter, not part of what the user is asking about.
        start, end = found[1]
        topic = (q_head[:start] + q_head[end:]).strip()

    filters.version = requested_version(query)

    for date_match in re.finditer(r"\b(20\d\d)-(\d\d)-(\d\d)\b", q):
        day = dt.date(*map(int, date_match.groups()))
        filters.date_field = "received_date" if filters.direction == "incoming" else "document_date"
        filters.date_from = filters.date_to = day

    scores = Scores()
    if re.search(_OFF_TOPIC, q):
        scores.OT = 1.0
    elif re.search(_DR_VERBS, q) or depends_on is not None:
        scores.DR = 1.0
    elif re.search(_IR_START, q) or q.endswith(("?", "؟")):
        scores.IR = 1.0
    elif filters.doc_type is not None:
        # A bare phrase that names a kind of document ("Exhibitor Agreement with Qamar")
        # is a request for it; this is also how an Output C option comes back (1.6.15).
        scores.DR = 1.0
    else:
        scores.DR, scores.IR = 0.6, 0.5

    requests = [part for part in re.split(r"\s+(?:and also|and then|وايضا|ثم)\s+", query) if part]
    return GradeResult(
        scores=scores,
        requests=requests,
        filters=filters,
        depends_on=depends_on,
        topic=topic or query,
        # No translation offline: both renderings are the topic, so reranking sees it once.
        topic_en=topic or query,
        query_en=topic or query,
        query_ar=topic or query,
    )
