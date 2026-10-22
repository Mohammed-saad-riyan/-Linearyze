import pytest

from app.text.arabic import detect_language, find_original_span, first_strong_direction, normalize
from app.text.terms import terms


def test_1_4_2_a_diacritics_ignored_both_ways() -> None:
    plain, marked = "تمت الموافقة على الطلب", "تمّت المُوافَقة على الطَّلب"
    assert normalize(plain) == normalize(marked)
    assert find_original_span(marked, plain) == (0, len(marked))
    assert find_original_span(plain, marked) == (0, len(plain))


def test_1_4_3_a_tatweel_ignored() -> None:
    assert normalize("الإلـــكترونية") == normalize("الإلكترونية")


def test_1_4_4_a_arabic_indic_digits_match() -> None:
    assert normalize("٢٠٢٦") == normalize("2026") == "2026"
    assert normalize("۲۰۲۶") == "2026"  # Eastern (Persian) forms
    assert normalize("١٢٬٠٠٠ ريال") == normalize("12,000 ريال")


@pytest.mark.parametrize(
    ("variant", "base"),
    [
        ("أ", "ا"),
        ("إ", "ا"),
        ("آ", "ا"),
        ("ٱ", "ا"),
        ("ى", "ي"),
        ("ة", "ه"),
        ("ؤ", "و"),
        ("ئ", "ي"),
    ],
)
def test_1_4_5_a_letter_variants(variant: str, base: str) -> None:
    assert normalize(variant) == normalize(base)


def test_1_4_5_hamza_spellings_of_one_word_match() -> None:
    assert normalize("إيرادات") == normalize("ايرادات") == normalize("أيرادات")


def test_offset_map_returns_the_original_slice() -> None:
    original = "وتودّ الإحاطة بأن مواعيد تشغيل المعارض"
    start, end = find_original_span(original, "وتود الاحاطه")  # type: ignore[misc]
    assert original[start:end] == "وتودّ الإحاطة"


def test_whitespace_and_line_breaks_collapse() -> None:
    original = "between Linearyze (the Organiser) and Sadu\nFurnishings Co."
    start, end = find_original_span(original, "Sadu Furnishings Co.")  # type: ignore[misc]
    assert original[start:end] == "Sadu\nFurnishings Co."


def test_1_4_1_language_by_majority_script() -> None:
    assert detect_language("ما هي شروط الدفع مع Sadu؟") == "ar"
    assert detect_language("What does المعرض cost?") == "en"


def test_1_11_11_input_direction_follows_first_strong_character() -> None:
    assert first_strong_direction("  2026 معرض") == "rtl"
    assert first_strong_direction("Expo معرض") == "ltr"


def test_article_stripped_for_search() -> None:
    assert terms("المعرض") == terms("معرض")
    assert terms("والإيرادات") == terms("إيرادات")
