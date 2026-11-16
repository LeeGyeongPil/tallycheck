"""Number parsing, rounding intervals and rendering."""
from decimal import Decimal as D

import pytest


def n(tc, text):
    return tc.parse_number(text)


def test_plain_integer_interval(tc):
    x = n(tc, "1,240")
    assert x.value == D(1240) and (x.lo, x.hi) == (D("1239.5"), D("1240.5"))
    assert x.commas and x.decimals == 0


def test_decimal_interval_uses_displayed_digits(tc):
    x = n(tc, "41.3%")
    assert x.kind == "pct" and (x.lo, x.hi) == (D("41.25"), D("41.35"))


@pytest.mark.parametrize("text,value", [("(120)", -120), ("−5", -5), ("-5", -5), ("$1,200", 1200),
                                        ("₩3,000", 3000), ("€7.5", D("7.5")), ("12원", 12)])
def test_signs_and_currency(tc, text, value):
    assert n(tc, text).value == D(value)


def test_parenthesized_negative_keeps_style_when_rendered(tc):
    x = n(tc, "(120)")
    assert tc.render_like(D(-130), x) == "(130)"


def test_suffix_k_and_m(tc):
    k = n(tc, "1.4k")
    assert k.value == D(1400) and (k.lo, k.hi) == (D(1350), D(1450))
    m = n(tc, "$2.5M")
    assert m.value == D(2500000) and m.prefix == "$"
    assert tc.render_like(D(2600000), m) == "$2.6M"


def test_korean_units_integer_is_exact(tc):
    x = n(tc, "1억 2,000만")
    assert x.value == D(120_000_000) and x.lo == x.hi == x.value
    y = n(tc, "4,200만 원")
    assert y.value == D(42_000_000) and y.lo == y.hi


def test_korean_units_decimal_has_rounding_width(tc):
    x = n(tc, "1.2억")
    assert x.value == D(120_000_000)
    assert (x.lo, x.hi) == (D(115_000_000), D(125_000_000))
    assert tc.render_like(D(130_000_000), x) == "1.3억"


def test_pp_kinds(tc):
    assert n(tc, "3.5%p").kind == "pp"
    assert n(tc, "4pp").kind == "pp"


@pytest.mark.parametrize("text", ["1.234,56", "12,5", "1,23,456", "1.234.567"])
def test_ambiguous_formats_raise(tc, text):
    with pytest.raises(tc.AmbiguousNumber):
        n(tc, text)


@pytest.mark.parametrize("text", ["", "-", "—", "n/a", "abc", "12 apples", "2026-11-16"])
def test_non_numbers_are_none(tc, text):
    assert n(tc, text) is None


def test_ambiguous_cell_is_skipped_not_judged(check):
    ctx = check("| A | V |\n|---|---:|\n| x | 1.234,56 |\n| y | 2 |\n| Total | 3 |\n")
    assert [f for f in ctx.findings if f["check"] == "total_row"] == []
    assert ctx.skipped and ctx.skipped[0]["reason"] == "ambiguous_number"
    assert ctx.skipped[0]["text"] == "1.234,56"


def test_ambiguous_number_in_prose_is_skipped(check):
    ctx = check("Revenue grew 5% from 1.234,56 to 1.300,00 this year.\n")
    assert ctx.findings == [] and ctx.skipped[0]["reason"] == "ambiguous_number"


def test_interval_edges_are_closed(tc):
    assert tc.overlaps(D(1), D(2), D(2), D(3))
    assert not tc.overlaps(D(1), D(2), D("2.0001"), D(3))


def test_ratio_interval_rejects_zero_denominator(tc):
    assert tc.ratio_interval(D(1), D(2), D(-1), D(1)) is None
    lo, hi = tc.ratio_interval(D(1), D(2), D(2), D(4))
    assert (lo, hi) == (D("0.25"), D(1))


def test_render_rounds_half_up(tc):
    like = n(tc, "0.0%")
    assert tc.render_like(D("0.25"), like) == "0.3%"
    assert tc.render_like(D("12.5"), n(tc, "1")) == "13"
    assert tc.fmt4(D("-0.00001")) == "0.0000"
