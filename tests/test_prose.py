"""Sentence claims: growth rates, percentage points, direction, units, approximations."""
from conftest import findings_by_line


def one(check, text, lang="en"):
    ctx = check(text, lang)
    assert len(ctx.findings) == 1, ctx.findings
    return ctx.findings[0]


def test_growth_rate_mismatch_gives_rounded_expected(check):
    f = one(check, "Revenue grew 18.2% from 2,620 to 3,101 compared with Q2.\n")
    assert (f["check"], f["status"], f["stated"], f["expected"], f["exact"]) == \
        ("growth_rate", "mismatch", "18.2%", "18.4%", "18.3588")


def test_growth_rate_ok(check):
    assert one(check, "Revenue grew 18.4% from 2,620 to 3,101.\n")["status"] == "ok"


def test_from_to_then_claim(check):
    f = one(check, "Sales went from 200 to 250, up 20%.\n")
    assert (f["status"], f["expected"]) == ("mismatch", "25%")
    assert one(check, "Sales went from 200 to 250, an increase of 25%.\n")["status"] == "ok"


def test_claim_in_parentheses(check):
    assert one(check, "Cost rose from 80 to 100 (25%).\n")["status"] == "ok"
    assert one(check, "Cost rose from 80 to 100 (20%).\n")["status"] == "mismatch"


def test_decline_direction(check):
    assert one(check, "Revenue fell 20% from 100 to 80.\n")["status"] == "ok"
    wrong = one(check, "Revenue grew 20% from 100 to 80.\n")
    assert (wrong["status"], wrong["expected"]) == ("mismatch", "-20%")


def test_neutral_claim_compares_magnitude(check):
    assert one(check, "A 20% change from 100 to 80 was seen.\n")["status"] == "ok"


def test_unit_confusion_percent_vs_pp(check):
    f = one(check, "Web share rose from 44% to 48%, up 4%.\n")
    assert (f["check"], f["status"], f["expected"], f["stated"]) == ("unit_confusion", "mismatch", "9%", "4%")
    assert "4%p" in f["message"]


def test_percent_points_ok_in_every_spelling(check):
    for unit in ("4%p", "4pp", "4 percentage points", "4 pp"):
        f = one(check, f"Web share rose from 44% to 48%, up {unit}.\n")
        assert (f["check"], f["status"]) == ("pp_change", "ok"), unit


def test_pp_claim_that_is_really_relative(check):
    f = one(check, "Web share rose from 44% to 48%, up 9.1%p.\n")
    assert (f["check"], f["status"], f["expected"]) == ("unit_confusion", "mismatch", "4.0%p")


def test_relative_claim_on_percent_values_is_fine(check):
    f = one(check, "Web share rose from 44% to 48%, up 9.1%.\n")
    assert (f["check"], f["status"]) == ("growth_rate", "ok")


def test_pp_mismatch(check):
    f = one(check, "Share rose from 31.5% to 35.0%, up 4.5%p.\n")
    assert (f["check"], f["status"], f["expected"]) == ("pp_change", "mismatch", "3.5%p")


def test_approximation_widens_the_claim(check):
    assert one(check, "Orders grew about 20% from 1,000 to 1,190.\n")["status"] == "ok"
    strict = one(check, "Orders grew 20% from 1,000 to 1,190.\n")
    assert strict["status"] == "mismatch"


def test_approximation_is_not_unlimited(check):
    assert one(check, "Orders grew about 30% from 1,000 to 1,190.\n")["status"] == "mismatch"


def test_korean_growth_with_units(check):
    f = one(check, "3분기 매출은 1억 2,000만 원으로 전 분기 1억 원 대비 25% 증가했다.\n", "ko")
    assert (f["check"], f["status"], f["expected"]) == ("growth_rate", "mismatch", "20%")
    f2 = one(check, "영업이익은 4,200만 원에서 5,000만 원으로 15% 늘었다.\n", "ko")
    assert (f2["status"], f2["expected"], f2["exact"]) == ("mismatch", "19%", "19.0476")


def test_korean_direction_down(check):
    f = one(check, "비용은 5,000만 원에서 4,000만 원으로 20% 감소했다.\n", "ko")
    assert f["status"] == "ok"
    wrong = one(check, "비용은 5,000만 원에서 4,000만 원으로 20% 증가했다.\n", "ko")
    assert (wrong["status"], wrong["expected"]) == ("mismatch", "-20%")


def test_korean_percent_point(check):
    f = one(check, "온라인 비중은 31.5%에서 35.0%로 3.5%p 올랐다.\n", "ko")
    assert (f["check"], f["status"]) == ("pp_change", "ok")
    f2 = one(check, "온라인 비중은 31.5%에서 35.0%로 3.5% 올랐다.\n", "ko")
    assert (f2["check"], f2["expected"]) == ("unit_confusion", "11.1%")


def test_integer_with_unit_word_is_exact(check):
    # 1억 -> 1억 2,000만 is +20%, not 25% (an interval of 0.5억 would hide the error)
    assert one(check, "매출은 1억 2,000만 원으로 전 분기 1억 원 대비 20% 증가했다.\n", "ko")["status"] == "ok"
    assert one(check, "매출은 1억 2,000만 원으로 전 분기 1억 원 대비 25% 증가했다.\n", "ko")["status"] == "mismatch"


def test_unrelated_sentences_are_not_judged(check):
    assert check("Share was 5% and revenue went from 1 to 2 last year.\n").findings == []
    assert check("Margins are 12% in 2024.\n").findings == []
    assert check("전년 대비 25% 증가했다.\n", "ko").findings == []


def test_zero_base_is_not_judged(check):
    assert check("Users grew 5% from 0 to 10.\n").findings == []


def test_k_and_m_suffix_in_claims(check):
    assert one(check, "Revenue grew 25% from $2M to $2.5M.\n")["status"] == "ok"


def test_findings_are_sorted_by_line(check):
    ctx = check("Up 50% from 10 to 15.\nUp 10% from 10 to 12.\n")
    assert list(findings_by_line(ctx)) == [1, 2]


def test_year_ranges_are_not_measurements(check):
    assert check("Growth continued from 2021 to 2023, up 5%.\n").findings == []


def test_wrong_direction_word_is_reported_with_signed_expected_en(check):
    f = one(check, "Revenue fell 10% from 100 to 110.\n")
    assert (f["check"], f["status"], f["stated"], f["expected"]) == ("growth_rate", "mismatch", "10%", "+10%")
    assert "direction" in f["message"] and "increase" in f["message"]
    f = one(check, "Revenue rose 9% from 110 to 100.\n")
    assert f["expected"] == "-9%" and "decrease" in f["message"]


def test_wrong_direction_word_is_reported_ko(check):
    f = one(check, "매출은 100억 원에서 110억 원으로 10% 감소했다.\n", lang="ko")
    assert f["status"] == "mismatch" and f["expected"] != f["stated"] and f["expected"] == "+10%"
    assert "방향어" in f["message"] and "증가" in f["message"]


def test_wrong_direction_word_pp_change(check):
    f = one(check, "Share fell 2%p from 10% to 12%.\n")
    assert (f["check"], f["stated"], f["expected"]) == ("pp_change", "2%p", "+2%p")
    assert "direction" in f["message"]


def test_wrong_direction_and_wrong_size_adds_hint(check):
    f = one(check, "Revenue fell 5% from 100 to 110.\n")
    assert f["expected"] == "+10%" and "also wrong" in f["message"] and "(write +10%)" in f["message"]
