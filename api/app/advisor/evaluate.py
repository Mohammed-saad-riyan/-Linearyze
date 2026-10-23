"""Exact evaluation of a parsed formula (SRS 2.7).

decimal.Decimal at 50 significant digits throughout; only the final result is rounded
(2.7.3). Units travel with the numbers, so (SAR - SAR) / (SAR per booth) comes out in
booths and SAR + USD is refused rather than silently added (2.7.5, 2.7.6).
"""

from dataclasses import dataclass
from decimal import (
    ROUND_CEILING,
    ROUND_HALF_UP,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    localcontext,
)

from app.advisor.formula import BinOp, Group, Neg, Node, Num, Percent, Var
from app.config import DECIMAL_PRECISION

CURRENCIES = {"SAR", "USD", "EUR", "AED"}
# Things that only come in whole numbers. A result in one of these is rounded up (2.7.9):
# 43.04 booths needed means 44 booths.
COUNT_UNITS = {"booth", "visitor", "ticket", "staff", "day"}


Unit = tuple[tuple[str, int], ...]  # sorted (base, exponent) pairs; () is dimensionless


def unit_of(**exponents: int) -> Unit:
    return tuple(sorted((k, v) for k, v in exponents.items() if v))


def _combine(a: Unit, b: Unit, sign: int) -> Unit:
    merged = dict(a)
    for base, exp in b:
        merged[base] = merged.get(base, 0) + sign * exp
    return tuple(sorted((k, v) for k, v in merged.items() if v))


class CalculationError(Exception):
    """The calculation is impossible with these values (shown as M12)."""


class FormulaNotApplicable(Exception):
    """The formula adds or subtracts things of different kinds, e.g. SAR and booths (M11)."""


class MixedCurrencies(Exception):
    """Adding or comparing different currencies without a rate (shown as Output Q)."""

    def __init__(self, currencies: set[str]):
        super().__init__(f"mixed currencies: {sorted(currencies)}")
        self.currencies = currencies


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: Unit | None  # None: a bare number typed in the formula, takes its partner's unit


def _currencies(unit: Unit | None) -> set[str]:
    return {base for base, _ in unit or () if base in CURRENCIES}


def evaluate(node: Node, inputs: dict[str, Quantity]) -> Quantity:
    with localcontext() as ctx:
        ctx.prec = DECIMAL_PRECISION
        ctx.traps[DivisionByZero] = True
        ctx.traps[InvalidOperation] = True
        return _eval(node, inputs)


def _eval(node: Node, inputs: dict[str, Quantity]) -> Quantity:
    match node:
        case Num(value=value):
            return Quantity(value, None)
        case Var(name=name):
            q = inputs[name]
            if q.value < 0 and any(base in COUNT_UNITS for base, _ in q.unit or ()):
                raise CalculationError(f"negative quantity for {name}")
            return q
        case Group(inner=inner):
            return _eval(inner, inputs)
        case Neg(operand=operand):
            q = _eval(operand, inputs)
            return Quantity(-q.value, q.unit)
        case Percent(operand=operand):
            q = _eval(operand, inputs)
            return Quantity(q.value / 100, q.unit or ())
        case BinOp(op=op, left=left, right=right):
            a, b = _eval(left, inputs), _eval(right, inputs)
            if op in "+-":
                if a.unit is not None and b.unit is not None and a.unit != b.unit:
                    currencies = _currencies(a.unit) | _currencies(b.unit)
                    if len(currencies) > 1:
                        raise MixedCurrencies(currencies)
                    raise FormulaNotApplicable(
                        f"cannot {'add' if op == '+' else 'subtract'} {a.unit} and {b.unit}"
                    )
                unit = a.unit if a.unit is not None else b.unit
                return Quantity(a.value + b.value if op == "+" else a.value - b.value, unit)
            if op == "*":
                unit = _combine(a.unit or (), b.unit or (), +1) if (a.unit or b.unit) else None
                return Quantity(a.value * b.value, unit)
            if b.value == 0:
                raise CalculationError("division by zero")
            unit = _combine(a.unit or (), b.unit or (), -1) if (a.unit or b.unit) else None
            return Quantity(a.value / b.value, unit)
    raise TypeError(node)


@dataclass(frozen=True)
class Rounded:
    value: Decimal
    exact: Decimal
    note: str | None  # "rounded_up" when a count was rounded up


def round_result(q: Quantity) -> Rounded:
    """Round once, at the end, by what the unit is."""
    unit = q.unit or ()
    bases = {base for base, _ in unit}
    if len(unit) == 1 and unit[0][1] == 1 and bases & COUNT_UNITS:
        if q.value < 0:
            raise CalculationError("negative quantity in the result")
        whole = q.value.to_integral_value(rounding=ROUND_CEILING)
        return Rounded(whole, q.value, "rounded_up" if whole != q.value else None)
    if bases & CURRENCIES:
        return Rounded(q.value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), q.value, None)
    return Rounded(
        q.value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP).normalize(), q.value, None
    )


def format_number(value: Decimal) -> str:
    """12,000 / 1,284,500.50 / 0.125. Trailing .00 dropped, separators always."""
    if value == value.to_integral_value():
        return f"{value:,.0f}"
    text = f"{value:,.4f}".rstrip("0")
    return text if not text.endswith(".") else text[:-1]
