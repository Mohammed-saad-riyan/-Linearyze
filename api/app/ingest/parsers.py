"""Turn PDF, DOCX and XLSX files into passages that keep their source location.

Each passage carries what a citation needs (SRS 1.9.5 to 1.9.7): page for PDF, heading for
Word, sheet and cell range for Excel.
"""

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import docx
import openpyxl
import pymupdf
from bidi import get_display
from openpyxl.utils import get_column_letter

_ARABIC = re.compile(r"[؀-ۿﭐ-﷿ﹰ-﻿]")

# PDF passages are cut only after a line that ends a sentence, once they hold at least
# MIN_PASSAGE_CHARS, so a quote never straddles two passages because of a line wrap.
MIN_PASSAGE_CHARS = 160
MAX_PASSAGE_CHARS = 1200
_SENTENCE_END = (".", ":", "،", "؛", ";", "!", "?", "؟")


@dataclass
class Passage:
    text: str
    page: int | None = None
    heading: str | None = None
    sheet: str | None = None
    cell_range: str | None = None


def _pdf_line_text(line: dict) -> str:  # type: ignore[type-arg]
    chars = [c for span in line["spans"] for c in span["chars"]]
    if not any(_ARABIC.match(c["c"]) for c in chars):
        return "".join(c["c"] for c in chars)
    # PDF text layers store right-to-left lines in a mix of visual and logical order, and
    # number runs inside Arabic come out reversed ("٦٢٠٢" for "٢٠٢٦"). Rebuild the
    # visual line from glyph x positions, then let the Unicode bidi algorithm put it in
    # reading order. NFKC first folds presentation forms back to base letters.
    chars.sort(key=lambda c: (c["bbox"][0] + c["bbox"][2]) / 2)
    visual = unicodedata.normalize("NFKC", "".join(c["c"] for c in chars))
    return str(get_display(visual, base_dir="R"))


def parse_pdf(path: Path) -> list[Passage]:
    passages: list[Passage] = []
    with pymupdf.open(path) as pdf:
        for page_no, page in enumerate(pdf, start=1):
            pending: list[str] = []
            size = 0
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    text = _pdf_line_text(line).strip()
                    if not text:
                        continue
                    pending.append(text)
                    size += len(text) + 1
                    ends_sentence = text.endswith(_SENTENCE_END)
                    if (size >= MIN_PASSAGE_CHARS and ends_sentence) or size >= MAX_PASSAGE_CHARS:
                        passages.append(Passage("\n".join(pending), page=page_no))
                        pending, size = [], 0
            if pending:
                passages.append(Passage("\n".join(pending), page=page_no))
    return passages


def parse_docx(path: Path) -> list[Passage]:
    passages: list[Passage] = []
    heading: str | None = None
    body: list[str] = []

    def flush() -> None:
        if body:
            passages.append(Passage("\n".join(body), heading=heading))
            body.clear()

    for para in docx.Document(str(path)).paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style = para.style.name if para.style is not None else ""
        if style == "Title":
            passages.append(Passage(text, heading=None))
        elif style.startswith("Heading"):
            flush()
            heading = text
        else:
            body.append(text)
    flush()
    return passages


def _cell_text(cell: openpyxl.cell.cell.Cell) -> str:
    value = cell.value
    if value is None:
        return ""
    if isinstance(value, int | float) and "#,##0" in cell.number_format:
        return f"{value:,.0f}"
    return str(value)


def parse_xlsx(path: Path) -> list[Passage]:
    """One passage per block of consecutive non-empty rows, cited by its cell range.

    Cells in a row are joined with " | " so a quote like "Standard booth / جناح قياسي |
    3 m x 3 m | 12,000" reads as the row it came from.
    """
    passages: list[Passage] = []
    wb = openpyxl.load_workbook(path, data_only=True)
    for ws in wb.worksheets:
        block: list[str] = []
        first_row = last_row = 0
        last_col = 1

        def flush(ws_title: str = ws.title) -> None:
            if block:
                cell_range = f"A{first_row}:{get_column_letter(last_col)}{last_row}"
                passages.append(Passage("\n".join(block), sheet=ws_title, cell_range=cell_range))
                block.clear()

        for row in ws.iter_rows():
            cells = [(c.column, _cell_text(c)) for c in row if _cell_text(c)]
            if not cells:
                flush()
                continue
            if not block:
                first_row = row[0].row
                last_col = 1
            last_row = row[0].row
            last_col = max(last_col, cells[-1][0])
            block.append(" | ".join(text for _, text in cells))
        flush()
    return passages


def parse(path: Path) -> list[Passage]:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return parse_pdf(path)
    if suffix == ".docx":
        return parse_docx(path)
    if suffix == ".xlsx":
        return parse_xlsx(path)
    raise ValueError(f"unsupported file type: {path.name}")
