import datetime as dt
from decimal import Decimal

from app.assistant.conflict import PREFERENCE_WORDS
from app.assistant.validate import check_sentence, find_dates, find_numbers
from app.text.arabic import normalize

PASSAGES = {
    1: "The Exhibitor shall pay each invoice within 30 days of the invoice date.",
    2: "This agreement is made on 20 January 2026 between Linearyze (the Organiser) and Sadu\n"
    "Furnishings Co. (the Exhibitor).",
    3: "ثانياً- يُحدَّد الحد الأقصى للحضور في وقت واحد بـ ٣٥٠٠ زائر، ولا يجوز تجاوزه.",
}
NAMES = ["sadu furnishings", "qamar lighting"]


def test_1_8_2_9_quotes_are_verbatim() -> None:
    check = check_sentence(
        "Sadu Furnishings Co. pays within 30 days.",
        [(1, "within 30 days"), (2, "Sadu Furnishings Co.")],
        PASSAGES,
        NAMES,
    )
    assert check.ok
    # The displayed quote is the source slice, line break included, not the model's string.
    assert check.quotes[1].text == "Sadu\nFurnishings Co."


def test_1_8_2_9_arabic_quote_without_diacritics_maps_to_the_original() -> None:
    check = check_sentence(
        "الحد الأقصى ٣٥٠٠ زائر.",
        [(3, "يحدد الحد الاقصى للحضور في وقت واحد بـ 3500 زائر")],
        PASSAGES,
        NAMES,
    )
    assert check.ok
    assert check.quotes[0].text.startswith("يُحدَّد")


def test_1_8_2_9_invented_quote_is_rejected() -> None:
    check = check_sentence(
        "Payment is due in 30 days.", [(1, "payment is due within 30 days")], PASSAGES, NAMES
    )
    assert not check.ok
    assert "quote not found" in check.errors[0]


def test_1_8_2_12_numbers_dates_names_in_quotes() -> None:
    wrong_number = check_sentence(
        "Sadu pays within 45 days.", [(1, "within 30 days")], PASSAGES, NAMES
    )
    assert "number 45 is not in the quotes" in wrong_number.errors

    wrong_date = check_sentence(
        "It was signed on 21 January 2026.", [(2, "made on 20 January 2026")], PASSAGES, NAMES
    )
    assert any("2026-01-21" in e for e in wrong_date.errors)

    reformatted_date = check_sentence(
        "It was signed on 2026-01-20.", [(2, "made on 20 January 2026")], PASSAGES, NAMES
    )
    assert reformatted_date.ok

    unquoted_name = check_sentence(
        "Qamar Lighting pays within 30 days.", [(1, "within 30 days")], PASSAGES, NAMES
    )
    assert any("qamar" in e for e in unquoted_name.errors)


def test_1_8_2_12_arabic_digits_count_as_the_same_number() -> None:
    assert find_numbers("١٢٬٠٠٠ ريال") == {Decimal(12000)}
    assert find_numbers("2.4 metres") == find_numbers("٢٫٤ متر")


def test_dates_in_english_and_arabic() -> None:
    assert find_dates("17 March 2026")[0] == {dt.date(2026, 3, 17)}
    assert find_dates("١٧ مارس ٢٠٢٦م")[0] == {dt.date(2026, 3, 17)}
    assert find_dates("March 17, 2026")[0] == {dt.date(2026, 3, 17)}


def test_1_8_2_15_preference_words_are_detected() -> None:
    assert PREFERENCE_WORDS.search(normalize("The 45-day term is the correct one."))
    assert PREFERENCE_WORDS.search(normalize("المدة الأحدث هي ٤٥ يوماً"))
    assert not PREFERENCE_WORDS.search(normalize("The Booth Services Order states 45 days."))
