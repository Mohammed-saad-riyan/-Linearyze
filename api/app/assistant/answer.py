"""Output B: write an answer from passages, then hold every sentence to its quotes.

Flow (SRS 1.8.2.9 to 1.8.2.12): draft -> validate each sentence -> one regeneration with
the list of errors -> validate again -> drop any sentence that still fails. If nothing
survives, the caller returns M1.
"""

import re
from dataclasses import dataclass

from pydantic import BaseModel

from app import llm
from app.assistant.retrieve import PassageHit
from app.assistant.validate import VerifiedQuote, check_sentence
from app.config import settings
from app.text.terms import coverage, terms

MAX_PASSAGES_FOR_ANSWER = 8
MAX_OFFLINE_SENTENCES = 3


class DraftQuote(BaseModel):
    passage: int
    quote: str


class DraftSentence(BaseModel):
    text: str
    quotes: list[DraftQuote]


class AnswerDraft(BaseModel):
    sentences: list[DraftSentence]


@dataclass
class AnswerSentence:
    text: str
    quotes: list[VerifiedQuote]


@dataclass
class AnswerResult:
    sentences: list[AnswerSentence]
    dropped: list[str]  # validation errors of sentences that were removed (debug panel)
    regenerated: bool


def _passage_block(passages: list[PassageHit], titles: dict[str, str]) -> str:
    return "\n\n".join(
        f"[{n}] {titles[p.document_id]}\n{p.text}" for n, p in enumerate(passages, start=1)
    )


def _draft_live(question: str, lang: str, block: str, errors: list[str]) -> AnswerDraft:
    content = (
        f"Answer language: {'Arabic' if lang == 'ar' else 'English'}\n\n"
        f"Question:\n{question}\n\nPassages:\n{block}"
    )
    if errors:
        content += "\n\nErrors in your previous attempt:\n" + "\n".join(f"- {e}" for e in errors)
    return llm.structured("answer", content, AnswerDraft, writer=True)


_SENTENCE_END = re.compile(r"(?<=[.!?؟])\s+")


def split_sentences(passage: str) -> list[tuple[str, str]]:
    """(heading, sentence) pairs.

    Sentences end at punctuation; a PDF line wrap inside a sentence is not a boundary. A
    spreadsheet row (cells joined with " | ") is a unit of its own. A short unpunctuated
    line is a heading: it is not a sentence, but it tells us what the next ones are about.
    """
    units: list[tuple[str, str]] = []
    prose: list[str] = []
    heading = ""

    def flush() -> None:
        if prose:
            units.extend((heading, u) for u in _SENTENCE_END.split(" ".join(prose)))
            prose.clear()

    for line in passage.splitlines():
        if " | " in line:
            flush()
            units.append((heading, line))
        elif len(line) < 40 and not line.rstrip().endswith(
            (".", ":", ",", "،", "؛", "!", "?", "؟")
        ):
            flush()
            heading = line
        else:
            prose.append(line)
    flush()
    return [(h, u.strip()) for h, u in units if u.strip()]


def _draft_offline(question: str, passages: list[PassageHit]) -> AnswerDraft:
    """Extractive stand-in: the best-matching source sentence, verbatim, per document."""
    wanted = terms(question)
    sentences: list[DraftSentence] = []
    seen_documents: set[str] = set()
    for n, passage in enumerate(passages, start=1):
        if passage.document_id in seen_documents:
            continue
        scored = [
            (coverage(wanted, set(terms(f"{h} {s}"))), s) for h, s in split_sentences(passage.text)
        ]
        top = max((score for score, _ in scored), default=0.0)
        if top == 0:
            continue
        seen_documents.add(passage.document_id)
        # Every sentence that ties for best is kept: a price list row and its header row
        # often match equally, and showing both beats guessing.
        for _, best in [x for x in scored if x[0] == top][:2]:
            sentences.append(DraftSentence(text=best, quotes=[DraftQuote(passage=n, quote=best)]))
        if len(sentences) >= MAX_OFFLINE_SENTENCES:
            break
    return AnswerDraft(sentences=sentences)


def _check(  # type: ignore[no-untyped-def]
    draft: AnswerDraft, passages: list[PassageHit], known_names: list[str], titles: dict[str, str]
):
    by_number = {n: p.text for n, p in enumerate(passages, start=1)}
    title_by_number = {n: titles[p.document_id] for n, p in enumerate(passages, start=1)}
    checks = []
    for sentence in draft.sentences:
        quotes = [(q.passage, q.quote) for q in sentence.quotes]
        checks.append(
            (
                sentence,
                check_sentence(sentence.text, quotes, by_number, known_names, title_by_number),
            )
        )
    return checks


def write_answer(
    question: str,
    lang: str,
    passages: list[PassageHit],
    titles: dict[str, str],
    known_names: list[str],
) -> AnswerResult:
    passages = passages[:MAX_PASSAGES_FOR_ANSWER]
    live = settings.use_live_llm()
    block = _passage_block(passages, titles)
    draft = _draft_live(question, lang, block, []) if live else _draft_offline(question, passages)
    checks = _check(draft, passages, known_names, titles)

    regenerated = False
    failures = [
        f"sentence {i + 1} ({s.text!r}): {e}" for i, (s, c) in enumerate(checks) for e in c.errors
    ]
    if failures and live:
        regenerated = True
        checks = _check(_draft_live(question, lang, block, failures), passages, known_names, titles)

    kept, dropped = [], []
    for sentence, check in checks:
        if check.ok:
            # Map the draft's passage numbers back to chunk ids for citations.
            quotes = [
                VerifiedQuote(passages[q.passage_id - 1].chunk_id, q.start, q.end, q.text)
                for q in check.quotes
            ]
            kept.append(AnswerSentence(sentence.text, quotes))
        else:
            dropped.extend(check.errors)
    return AnswerResult(kept, dropped, regenerated)
