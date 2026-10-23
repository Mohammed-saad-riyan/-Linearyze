"""Turn a graded query into concrete database filters (SRS 1.2.7, 1.14.9).

The Ministry example, "the letter from Ministry A that we received on the day we submitted
document X", needs two lookups: find X and read its submitted_date, then find incoming
letters from Ministry A received that day. Both run under the caller's RLS identity, so
if the caller cannot see X the plan fails exactly as if X did not exist.
"""

import datetime as dt
import re
from dataclasses import dataclass, field

from app.assistant.grade_types import DateField, GradeResult
from app.db.session import Conn
from app.text.arabic import normalize
from app.text.terms import coverage, or_tsquery, terms

# A dependent lookup or title match needs this share of the named title's terms.
TITLE_MATCH_COVERAGE = 0.75

# Phrases that name an organisation. If a sender or client phrase contains one of these
# and does not resolve to a known organisation, nothing can match (M1). Otherwise the
# phrase is treated as noise from the grader and ignored.
_ORG_WORDS = r"\b(ministry|authority|company|co|est|cooperative|council|agency)\b|وزاره|هيئه|شركه|مؤسسه|جمعيه"


@dataclass
class Plan:
    sender_org: str | None = None
    recipient_org: str | None = None
    client_org: str | None = None
    doc_type: str | None = None
    direction: str | None = None
    date_field: DateField | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None
    version: int | None = None
    event_id: str | None = None
    topic: str = ""
    # What the reranker scores passages against: the topic in English. A short topic scores
    # far higher than the full question (0.59 vs 0.23 on the Sadu payment terms), and every
    # passage is reranked with its bilingual title, so it also reaches Arabic documents.
    rerank_query: str = ""
    dependency_document: str | None = None
    impossible: bool = False  # a named thing does not exist for this user: the answer is M1
    notes: list[str] = field(default_factory=list)

    @property
    def has_strong_constraints(self) -> bool:
        """Filters precise enough that every matching document is an answer to a DR query."""
        return any(
            (
                self.sender_org,
                self.recipient_org,
                self.client_org,
                self.date_from,
                self.dependency_document,
                self.version is not None,
            )
        )


def _words(text: str) -> str:
    """Normalized, punctuation turned into spaces, padded: ready for ' alias ' lookups."""
    return f" {' '.join(re.sub(r'[^\w\s]', ' ', normalize(text)).split())} "


def resolve_org(conn: Conn, phrase: str) -> str | None:
    """Longest alias that occurs in `phrase` as whole words."""
    text = _words(phrase)
    rows = conn.execute(
        "SELECT org_id, alias_normalized FROM org_aliases ORDER BY length(alias_normalized) DESC"
    ).fetchall()
    for row in rows:
        if f" {row['alias_normalized']} " in text:
            return str(row["org_id"])
    return None


def _org_filter(conn: Conn, plan: Plan, phrase: str | None, name: str) -> str | None:
    if not phrase:
        return None
    org = resolve_org(conn, phrase)
    if org is None and re.search(_ORG_WORDS, normalize(phrase)):
        plan.impossible = True
        plan.notes.append(f"{name} '{phrase}' is not a known organisation")
    elif org is None and normalize(phrase) not in normalize(plan.topic):
        # Not an organisation after all ("the price of a standard booth"): it is topic.
        plan.topic = f"{plan.topic} {phrase}".strip()
    return org


def resolve_event(conn: Conn, text: str) -> str | None:
    """An event named in `text` by its name or a known alias ("Expo 2026", "معرض 2026")."""
    padded = _words(text)
    for row in conn.execute("SELECT id, aliases FROM events ORDER BY id").fetchall():
        if any(f" {alias} " in padded for alias in row["aliases"]):
            return str(row["id"])
    return None


def find_by_title(conn: Conn, title: str) -> dict | None:  # type: ignore[type-arg]
    """Best readable, indexed document whose title covers the named title, or None."""
    tsquery = or_tsquery(title)
    if tsquery is None:
        return None
    rows = conn.execute(
        """
        SELECT id, title_terms, document_date, received_date, submitted_date
        FROM documents
        WHERE indexed_at IS NOT NULL AND is_latest AND title_tsv @@ to_tsquery('simple', %s)
        """,
        (tsquery,),
    ).fetchall()
    wanted = terms(title)
    scored = [(coverage(wanted, set(r["title_terms"].split())), r) for r in rows]
    scored = [s for s in scored if s[0] >= TITLE_MATCH_COVERAGE]
    if not scored:
        return None
    scored.sort(key=lambda s: (-s[0], s[1]["id"]))
    return scored[0][1]


def build_plan(conn: Conn, graded: GradeResult) -> Plan:
    f = graded.filters
    plan = Plan(
        doc_type=f.doc_type,
        direction=f.direction,
        version=f.version,
        date_field=f.date_field,
        date_from=f.date_from,
        date_to=f.date_to,
        topic=graded.topic or graded.query_en,
        rerank_query=graded.topic_en or graded.topic or graded.query_en,
    )
    plan.sender_org = _org_filter(conn, plan, f.sender, "sender")
    plan.recipient_org = _org_filter(conn, plan, f.recipient, "recipient")
    plan.client_org = _org_filter(conn, plan, f.client, "client")
    # Event scope is enforced by RLS; naming an event the user cannot see filters to an
    # empty set, which is the same M1 as an event with no documents.
    plan.event_id = resolve_event(conn, f.event or graded.query_en)

    if graded.depends_on is not None:
        dep = graded.depends_on
        found = find_by_title(conn, dep.find_title)
        value = found[dep.use_field] if found else None
        if found is None or value is None:
            plan.impossible = True
            plan.notes.append("dependent document not found")
        else:
            plan.dependency_document = found["id"]
            plan.date_field = dep.as_field
            plan.date_from = plan.date_to = value
            if dep.as_field == "received_date":
                plan.direction = "incoming"
            plan.notes.append(f"{found['id']}.{dep.use_field} = {value.isoformat()}")
    return plan


def filter_sql(plan: Plan, alias: str = "d") -> tuple[str, dict]:  # type: ignore[type-arg]
    """WHERE conditions for documents under `alias`. Column names come from fixed literals."""
    conds = [f"{alias}.indexed_at IS NOT NULL"]
    params: dict = {}  # type: ignore[type-arg]
    if plan.version is not None:
        conds.append(f"{alias}.version = %(version)s")
        params["version"] = plan.version
    else:
        conds.append(f"{alias}.is_latest")
    for column, value in (
        ("sender_org_id", plan.sender_org),
        ("recipient_org_id", plan.recipient_org),
        ("doc_type", plan.doc_type),
        ("direction", plan.direction),
        ("event_id", plan.event_id),
    ):
        if value is not None:
            conds.append(f"{alias}.{column} = %({column})s")
            params[column] = value
    if plan.client_org is not None:
        conds.append(
            f"(%(client)s IN ({alias}.client_org_id, {alias}.sender_org_id, "
            f"{alias}.recipient_org_id))"
        )
        params["client"] = plan.client_org
    if plan.date_field is not None and (plan.date_from or plan.date_to):
        column = {
            "document_date": "document_date",
            "received_date": "received_date",
            "submitted_date": "submitted_date",
        }[plan.date_field]
        if plan.date_from:
            conds.append(f"{alias}.{column} >= %(date_from)s")
            params["date_from"] = plan.date_from
        if plan.date_to:
            conds.append(f"{alias}.{column} <= %(date_to)s")
            params["date_to"] = plan.date_to
    return " AND ".join(conds), params
