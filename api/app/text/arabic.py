"""Arabic and Latin text normalization (SRS 1.4.2 to 1.4.5).

The single source of truth for matching. It is applied to chunk text, metadata search
columns, organisation aliases and every query, and never to the stored original text.

`normalize_with_map` also returns, for every character of the normalized string, the
index of the original character it came from. A match found in normalized text can then
be mapped back to the exact original span, which is how quotes stay verbatim
(SRS 1.8.2.9) and how the viewer highlights the right characters.
"""

import re
import unicodedata

_DIACRITICS = {chr(c) for c in range(0x064B, 0x0653)} | {"ٰ"}
_TATWEEL = "ـ"

_LETTER_MAP = {
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ٱ": "ا",
    "ى": "ي",
    "ة": "ه",
    "ؤ": "و",
    "ئ": "ي",
}

_DIGIT_MAP = {chr(0x0660 + i): str(i) for i in range(10)} | {
    chr(0x06F0 + i): str(i) for i in range(10)
}

# Arabic comma, semicolon, question mark and decimal/thousands separators.
_PUNCT_MAP = {"،": ",", "؛": ";", "؟": "?", "٫": ".", "٬": ","}

_ARABIC_LETTER = re.compile(r"[ء-يٱ-ۓۺ-ۿ]")
_LATIN_LETTER = re.compile(r"[A-Za-z]")


def _normalize_char(ch: str) -> str:
    if ch in _DIACRITICS or ch == _TATWEEL:
        return ""
    if ch in _DIGIT_MAP:
        return _DIGIT_MAP[ch]
    # NFKC folds presentation forms (U+FB50..U+FEFF) that PDF extraction sometimes
    # produces back to base letters, and full-width Latin to ASCII.
    folded = unicodedata.normalize("NFKC", ch)
    out = []
    for c in folded:
        if c in _DIACRITICS or c == _TATWEEL:
            continue
        c = _LETTER_MAP.get(c, c)
        c = _PUNCT_MAP.get(c, c)
        out.append(c.lower())
    return "".join(out)


def normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Return (normalized, offsets) where offsets[i] is the original index of normalized[i].

    Whitespace runs collapse to one space; leading and trailing whitespace is dropped.
    """
    chars: list[str] = []
    offsets: list[int] = []
    pending_space_at: int | None = None
    for i, ch in enumerate(text):
        if ch.isspace():
            if chars and pending_space_at is None:
                pending_space_at = i
            continue
        piece = _normalize_char(ch)
        if not piece:
            continue
        if pending_space_at is not None:
            chars.append(" ")
            offsets.append(pending_space_at)
            pending_space_at = None
        for c in piece:
            chars.append(c)
            offsets.append(i)
    return "".join(chars), offsets


def normalize(text: str) -> str:
    return normalize_with_map(text)[0]


def find_original_span(original: str, needle: str) -> tuple[int, int] | None:
    """Locate `needle` in `original`, tolerating diacritics, hamza forms, digits and spacing.

    Returns (start, end) indices into `original` such that original[start:end] is the
    verbatim source text, or None if there is no match. Exact match is tried first so a
    quote copied correctly keeps its exact boundaries.
    """
    exact = original.find(needle)
    if exact >= 0:
        return exact, exact + len(needle)
    norm_original, offsets = normalize_with_map(original)
    norm_needle = normalize(needle)
    if not norm_needle:
        return None
    pos = norm_original.find(norm_needle)
    if pos < 0:
        return None
    start = offsets[pos]
    last = offsets[pos + len(norm_needle) - 1]
    end = last + 1
    # Extend over trailing marks (diacritics, tatweel) that belong to the last letter.
    while end < len(original) and (original[end] in _DIACRITICS or original[end] == _TATWEEL):
        end += 1
    return start, end


def detect_language(text: str) -> str:
    """'ar' when Arabic-script letters outnumber Latin letters (SRS 1.4.1), else 'en'."""
    arabic = len(_ARABIC_LETTER.findall(text))
    latin = len(_LATIN_LETTER.findall(text))
    return "ar" if arabic > latin else "en"


def first_strong_direction(text: str) -> str:
    """'rtl' or 'ltr' from the first strong character (SRS 1.11.11, input box direction)."""
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("R", "AL"):
            return "rtl"
        if bidi == "L":
            return "ltr"
    return "ltr"
