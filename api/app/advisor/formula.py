"""Formulas, as the user wrote them, turned into an expression tree (SRS 2.6.1, 2.6.2).

There is no stored library of business formulas (SRS 2.1.3). The user supplies the
formula in words or symbols, in English or Arabic; this module rewrites operator words to
symbols, treats every run of other words as a named term, and parses the result with a
small recursive-descent parser that accepts only + - * / ( ), numbers, names and %.
Nothing is evaluated by Python's eval, and the tree is never simplified or rearranged.
"""

import re
from dataclasses import dataclass
from decimal import Decimal

from app.text.arabic import find_original_span, normalize

# Longest phrases first so "multiplied by" wins over "by".
_OPERATOR_WORDS = [
    ("multiplied by", "*"),
    ("divided by", "/"),
    ("times", "*"),
    ("minus", "-"),
    ("plus", "+"),
    ("less", "-"),
    ("over", "/"),
    ("مضروبا في", "*"),
    ("مقسوما علي", "/"),
    ("مقسوم علي", "/"),
    ("ناقص", "-"),
    ("زائد", "+"),
    ("ضرب", "*"),
    ("مطروحا منه", "-"),
    ("علي", "/"),
]
_SYMBOLS = {"−": "-", "–": "-", "×": "*", "÷": "/", "＋": "+", "x": "*"}


class FormulaError(ValueError):
    """The formula cannot be parsed; `part` is the text the user should fix (Output Q)."""

    def __init__(self, message: str, part: str):
        super().__init__(message)
        self.part = part


@dataclass(frozen=True)
class Num:
    value: Decimal
    text: str


@dataclass(frozen=True)
class Var:
    name: str  # snake_case key
    label: str  # the words as the user wrote them


@dataclass(frozen=True)
class BinOp:
    op: str
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Neg:
    operand: "Node"


@dataclass(frozen=True)
class Percent:
    operand: "Node"


@dataclass(frozen=True)
class Group:
    """Brackets the user typed. Kept in the tree so the substituted line shows them too."""

    inner: "Node"


Node = Num | Var | BinOp | Neg | Percent | Group


@dataclass(frozen=True)
class Formula:
    target: Var
    expression: Node
    text: str  # normalised display form, operators as symbols


_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:,\d{3})*(?:\.\d+)?)|(?P<op>[-+*/()%])|(?P<name>[^\s\-+*/()%=\d][^\-+*/()%=]*))"
)


def _label_key(label: str) -> str:
    return re.sub(r"\W+", "_", normalize(label)).strip("_")


def _rewrite_operators(text: str) -> str:
    out = text
    for symbol, replacement in _SYMBOLS.items():
        if symbol == "x":
            out = re.sub(r"(?<=[\d\s)])x(?=[\s\d(])", replacement, out)
        else:
            out = out.replace(symbol, replacement)
    norm = normalize(out)
    for words, symbol in _OPERATOR_WORDS:
        norm = re.sub(rf"(?<!\S){re.escape(words)}(?!\S)", f" {symbol} ", norm)
    return norm


def _tokens(expression: str) -> list[tuple[str, str]]:
    tokens, pos = [], 0
    while pos < len(expression):
        if expression[pos:].strip() == "":
            break
        match = _TOKEN.match(expression, pos)
        if not match or match.end() == pos:
            raise FormulaError("unexpected character", expression[pos : pos + 10].strip())
        kind = match.lastgroup or ""
        tokens.append((kind, match.group(kind).strip()))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]], source: str, original: str):
        self.tokens = tokens
        self.pos = 0
        self.source = source
        self.original = original  # before normalization, so labels keep the user's spelling

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self) -> tuple[str, str]:
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def parse(self) -> Node:
        node = self.expr()
        if self.peek() is not None:
            raise FormulaError("unexpected text after the formula", self.peek()[1])  # type: ignore[index]
        return node

    def expr(self) -> Node:
        node = self.term()
        while (t := self.peek()) and t[1] in "+-":
            self.take()
            node = BinOp(t[1], node, self.term())
        return node

    def term(self) -> Node:
        node = self.factor()
        while (t := self.peek()) and t[1] in "*/":
            self.take()
            node = BinOp(t[1], node, self.factor())
        return node

    def factor(self) -> Node:
        t = self.peek()
        if t is None:
            raise FormulaError("the formula ends where a value is expected", self.source[-20:])
        if t[1] == "-":
            self.take()
            return Neg(self.factor())
        node = self.atom()
        while (n := self.peek()) and n[1] == "%":
            self.take()
            node = Percent(node)
        return node

    def atom(self) -> Node:
        kind, text = self.take()
        if kind == "num":
            return Num(Decimal(text.replace(",", "")), text)
        if kind == "name":
            span = find_original_span(self.original, text)
            label = self.original[span[0] : span[1]].strip() if span else text
            return Var(_label_key(text), label)
        if text == "(":
            node = self.expr()
            closing = self.peek()
            if closing is None or closing[1] != ")":
                raise FormulaError("a bracket is opened but not closed", "(")
            self.take()
            return Group(node)
        raise FormulaError(f"'{text}' cannot start a value", text)


def parse_formula(text: str) -> Formula:
    """Parse 'target = expression'. Raises FormulaError naming the part to fix."""
    if "=" not in text:
        raise FormulaError("the formula needs '=' between the result and the calculation", text)
    left, right = text.split("=", 1)
    if not left.strip():
        raise FormulaError("the formula needs a name for the result", "=")
    rewritten = _rewrite_operators(right)
    expression = _Parser(_tokens(rewritten), rewritten, right).parse()
    # The formula line shown to the user is their own text, not a re-rendering of the tree.
    return Formula(
        Var(_label_key(left), left.strip()), expression, f"{left.strip()} = {right.strip()}"
    )


def display(node: Node, values: dict[str, str] | None = None) -> str:
    """The expression as the user grouped it, optionally with values in place of terms."""
    match node:
        case Num(text=text):
            return text
        case Var(name=name, label=label):
            return values[name] if values and name in values else label
        case Neg(operand=operand):
            return f"-{display(operand, values)}"
        case Percent(operand=operand):
            return f"{display(operand, values)}%"
        case Group(inner=inner):
            return f"({display(inner, values)})"
        case BinOp(op=op, left=left, right=right):
            return f"{display(left, values)} {op.replace('-', '−')} {display(right, values)}"
    raise TypeError(node)


def variables(node: Node) -> list[Var]:
    """Terms in order of first appearance."""
    seen: dict[str, Var] = {}

    def walk(n: Node) -> None:
        match n:
            case Var():
                seen.setdefault(n.name, n)
            case BinOp(left=left, right=right):
                walk(left)
                walk(right)
            case Neg(operand=o) | Percent(operand=o) | Group(inner=o):
                walk(o)

    walk(node)
    return list(seen.values())


_FORMULA_IN_QUERY = re.compile(r"([^.?؟!\n:]*=[^.?؟!\n]+)")


def extract_formula_text(query: str) -> str | None:
    """The 'name = expression' clause of a query, if there is one."""
    match = _FORMULA_IN_QUERY.search(query)
    return match.group(1).strip() if match else None
