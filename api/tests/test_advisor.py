import re
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.advisor.evaluate import (
    CalculationError,
    MixedCurrencies,
    Quantity,
    evaluate,
    round_result,
    unit_of,
)
from app.advisor.formula import FormulaError, display, extract_formula_text, parse_formula
from app.assistant.messages import message

BREAK_EVEN = (
    "How many booths do we need to sell at Expo 2026 to cover organisation costs? "
    "break-even booths = (total cost − confirmed revenue) / standard booth price"
)
PROFIT_AR = "ربح = إيرادات ناقص تكاليف. ما هو ربح معرض 2026؟"
SAR = unit_of(SAR=1)


def ask(client: TestClient, query: str, history: list[str] | None = None) -> dict:  # type: ignore[type-arg]
    turns = [{"role": "user", "text": t} for t in history or []]
    response = client.post("/api/advisor/query", json={"query": query, "history": turns})
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def test_2_6_break_even_end_to_end(employee: TestClient) -> None:
    body = ask(employee, BREAK_EVEN)
    assert body["output"] == "R"
    assert body["result"] == {
        "value": "44",
        "unit": "booths",
        "rounded_up": True,
        "exact": "43.041666666666666666666666666666666666666666666667",
    }
    assert (
        body["formula"]
        == "break-even booths = (total cost − confirmed revenue) / standard booth price"
    )
    assert body["substituted"] == "(1,284,500 − 768,000) / 12,000"
    sources = {i["term"]: (i["value"], i["document_id"]) for i in body["inputs"]}
    assert sources == {
        "total cost": ("1,284,500", "FIN-EXPO26-COST"),
        "confirmed revenue": ("768,000", "FIN-EXPO26-REV"),
        "standard booth price": ("12,000", "PRC-2026-V2"),
    }
    assert body["disclaimer"] == message("M8", "en")


def test_2_8_bind_figures_from_quotes(employee: TestClient) -> None:
    """Every document figure is the number written in its own verified quote."""
    body = ask(employee, BREAK_EVEN)
    for item in body["inputs"]:
        assert item["value"] in item["citation"]["quote"]


def test_2_6_arabic_formula_in_words(employee: TestClient) -> None:
    body = ask(employee, PROFIT_AR)
    assert body["output"] == "R"
    assert body["lang"] == "ar"
    assert body["result"]["value"] == "-516,500"
    assert body["result"]["unit"] == "ريال"
    assert body["formula"] == "ربح = إيرادات ناقص تكاليف"


def test_2_8_8_user_value_overrides_document_and_both_are_shown(employee: TestClient) -> None:
    body = ask(
        employee,
        "For Expo 2026, assuming a standard booth price of 11,000: " + BREAK_EVEN.split("? ")[1],
    )
    price = next(i for i in body["inputs"] if i["term"] == "standard booth price")
    assert price["value"] == "11,000" and price["source_type"] == "query"
    assert price["overridden_value"] == "12,000"
    assert body["result"]["value"] == "47"
    assert body["estimate"] is True


def test_2_8_value_from_an_earlier_message(employee: TestClient) -> None:
    body = ask(
        employee,
        "profit = confirmed revenue - catering cost",
        history=["For Expo 2026 the catering cost is 95,000"],
    )
    catering = next(i for i in body["inputs"] if i["term"] == "catering cost")
    assert catering["source_type"] == "conversation"
    assert body["result"]["value"] == "673,000"


def test_2_8_missing_terms_are_all_listed(employee: TestClient) -> None:
    body = ask(
        employee, "For Expo 2026: net = confirmed revenue - catering commission - drone show fee"
    )
    assert body["output"] == "Q"
    assert body["missing"] == ["catering commission", "drone show fee"]


def test_2_8_conflicting_documents_give_m7_and_a_choice(management: TestClient) -> None:
    body = ask(management, "profit = confirmed revenue - total cost")
    assert body["output"] == "Q"
    assert body["notice"] == message("M7", "en")
    assert {c["citation"]["document_id"] for c in body["choices"]} == {
        "FIN-EXPO26-COST",
        "HRT-BUDGET",
    }


def test_2_6_malformed_formula_names_the_part(employee: TestClient) -> None:
    body = ask(employee, "x = (total cost + confirmed revenue")
    assert body["output"] == "Q"
    assert "(" in body["question"]


def test_2_1_6_payment_request(employee: TestClient) -> None:
    body = ask(employee, "Transfer SAR 50,000 to Qamar Lighting")
    assert body["message_id"] == "PAYMENT"


def test_2_9_3_missing_figure_is_m9_whether_absent_or_hidden(
    employee: TestClient, management: TestClient
) -> None:
    absent = ask(employee, "What is the catering commission?")
    hidden = ask(employee, "What is the executive bonus pool?")  # only in a confidential memo
    assert (
        absent
        == hidden
        == {"output": "E", "lang": "en", "message_id": "M9", "message": message("M9", "en")}
    )
    assert ask(management, "What is the executive bonus pool?")["output"] == "R"


def test_2_9_1_unit_mismatch_is_m11(employee: TestClient) -> None:
    body = ask(employee, "For Expo 2026: x = total cost - booth size")
    assert body["message_id"] in {"M11", "M12"} or body["output"] == "Q"


def test_2_7_8_division_by_zero_is_m12(employee: TestClient) -> None:
    body = ask(
        employee,
        "For Expo 2026: per booth = total cost / (standard booth price - standard booth price)",
    )
    assert body["message_id"] == "M12"


# --- pure functions ----------------------------------------------------------------------


def test_2_6_1_formula_kept_exactly_as_written() -> None:
    formula = parse_formula("a = (b - c) - d")
    assert formula.text == "a = (b - c) - d"
    assert display(formula.expression) == "(b − c) − d"  # brackets kept, nothing simplified


def test_2_6_formula_found_inside_a_question() -> None:
    assert (
        extract_formula_text(BREAK_EVEN)
        == "break-even booths = (total cost − confirmed revenue) / standard booth price"
    )
    assert extract_formula_text("What is our profit?") is None


@pytest.mark.parametrize("bad", ["x = (a + b", "y = a + * b", "z = ", "no equals sign here"])
def test_2_6_malformed_formulas_raise(bad: str) -> None:
    with pytest.raises(FormulaError):
        parse_formula(bad)


def test_2_7_1_same_inputs_same_result_20_runs() -> None:
    formula = parse_formula("x = (a - b) / c")
    inputs = {
        "a": Quantity(Decimal("1284500"), SAR),
        "b": Quantity(Decimal("768000"), SAR),
        "c": Quantity(Decimal("12000"), unit_of(SAR=1, booth=-1)),
    }
    results = {evaluate(formula.expression, inputs) for _ in range(20)}
    assert len(results) == 1


def test_2_7_3_full_precision_round_final_only() -> None:
    third = evaluate(parse_formula("x = a / 3 * 3").expression, {"a": Quantity(Decimal(1), SAR)})
    assert round_result(third).value == Decimal("1.00")
    assert third.value == Decimal("0.99999999999999999999999999999999999999999999999999")


def test_2_7_9_booths_round_up_with_note() -> None:
    result = round_result(Quantity(Decimal("41.2"), unit_of(booth=1)))
    assert result.value == 42 and result.note == "rounded_up"
    exact = round_result(Quantity(Decimal("42"), unit_of(booth=1)))
    assert exact.value == 42 and exact.note is None


def test_2_7_5_units_follow_the_arithmetic() -> None:
    q = evaluate(
        parse_formula("x = (a - b) / c").expression,
        {
            "a": Quantity(Decimal(100), SAR),
            "b": Quantity(Decimal(40), SAR),
            "c": Quantity(Decimal(20), unit_of(SAR=1, booth=-1)),
        },
    )
    assert q.unit == unit_of(booth=1)


def test_2_7_6_mixed_currencies_without_rate() -> None:
    with pytest.raises(MixedCurrencies):
        evaluate(
            parse_formula("x = a + b").expression,
            {"a": Quantity(Decimal(1), SAR), "b": Quantity(Decimal(1), unit_of(USD=1))},
        )


def test_2_7_8_negative_quantity() -> None:
    with pytest.raises(CalculationError):
        evaluate(
            parse_formula("x = a * 2").expression, {"a": Quantity(Decimal(-3), unit_of(booth=1))}
        )


def test_2_7_7_money_results_are_labelled_before_tax(employee: TestClient) -> None:
    body = ask(employee, "For Expo 2026: profit = confirmed revenue - total cost")
    assert any("before tax" in n for n in body["notes"])


def test_2_1_3_no_stored_formula_library() -> None:
    """The advisor must not contain business formulas; users supply them (SRS 2.1.3)."""
    advisor = Path(__file__).parents[1] / "app" / "advisor"
    forbidden = re.compile(
        r"break[_ ]?even\s*=|margin\s*=|profit\s*=|roi\s*=|revenue\s*-\s*cost|"
        r"def (break_even|margin|profit|roi)\b",
        re.IGNORECASE,
    )
    for path in advisor.glob("*.py"):
        code = "\n".join(
            line
            for line in path.read_text().splitlines()
            if not line.lstrip().startswith(("#", '"', "'"))
        )
        assert not forbidden.search(code), f"business formula in {path.name}"


def test_2_7_5_whole_number_times_a_per_booth_price_counts_booths() -> None:
    q = evaluate(
        parse_formula("r = confirmed revenue + 10 × standard booth price").expression,
        {
            "confirmed_revenue": Quantity(Decimal(768000), SAR),
            "standard_booth_price": Quantity(Decimal(12000), unit_of(SAR=1, booth=-1)),
        },
    )
    assert q == Quantity(Decimal(888000), SAR)
    markup = evaluate(
        parse_formula("r = standard booth price × 1.15").expression,
        {"standard_booth_price": Quantity(Decimal(12000), unit_of(SAR=1, booth=-1))},
    )
    assert markup.unit == unit_of(SAR=1, booth=-1)  # a fraction stays a multiplier


def test_1_2_13_advisor_binds_a_requested_older_version(employee: TestClient) -> None:
    latest = ask(employee, "For Expo 2026: income = 10 × standard booth price")
    older = ask(employee, "Using version 1 of the price list: income = 10 × standard booth price")
    assert latest["result"]["value"] == "120,000"
    assert older["result"]["value"] == "100,000"
    assert older["inputs"][0]["document_id"] == "PRC-2026-V1"
