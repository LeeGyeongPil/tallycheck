"""Table checks: totals, subtotals, averages, shares, ignore comments."""
from conftest import findings_by_line


def test_q3_internal_errors(check):
    ctx = check((__import__("conftest").SAMPLES / "q3_report.md").read_text(encoding="utf-8"))
    bad = {(f["line"], f["check"]): f["expected"] for f in ctx.findings if f["status"] == "mismatch"}
    assert bad == {(5, "share_vs_value"): "40.0%", (6, "share_vs_value"): "31.6%",
                   (7, "share_vs_value"): "28.4%", (12, "share_vs_value"): "41%",
                   (13, "share_vs_value"): "33%", (14, "share_vs_value"): "25%",
                   (15, "percent_sum"): "100%", (17, "growth_rate"): "18.4%",
                   (23, "growth_rate"): "20%", (25, "growth_rate"): "19%"}
    assert len(ctx.findings) == 18


def test_total_row_mismatch_and_ok(check):
    ctx = check("| A | V |\n|---|---:|\n| x | 10 |\n| y | 20 |\n| Total | 35 |\n")
    f = findings_by_line(ctx)[5]
    assert (f["check"], f["status"], f["expected"], f["exact"]) == ("total_row", "mismatch", "30", "30.0000")
    ok = check("| A | V |\n|---|---:|\n| x | 10 |\n| y | 20 |\n| **Total** | **30** |\n")
    assert findings_by_line(ok)[5]["status"] == "ok"


def test_total_row_rounding_is_not_an_error(check):
    ctx = check("| A | V |\n|---|---:|\n| x | 1.4 |\n| y | 1.4 |\n| Total | 2.9 |\n")
    assert [f["status"] for f in ctx.findings] == ["ok"]


def test_interval_boundary_is_ok(check):
    # one detail row "2" spans [1.5, 2.5]; total "3" spans [2.5, 3.5]: they touch at 2.5 -> ok
    touch = check("| A | V |\n|---|---:|\n| x | 2 |\n| Total | 3 |\n")
    assert touch.findings[0]["status"] == "ok"
    apart = check("| A | V |\n|---|---:|\n| x | 2 |\n| Total | 4 |\n")
    assert apart.findings[0]["status"] == "mismatch"


def test_decimal_rows_use_displayed_precision(check):
    ok = check("| A | V |\n|---|---:|\n| x | 0.5 |\n| y | 0.5 |\n| Total | 1.1 |\n")
    assert ok.findings[0]["status"] == "ok"
    bad = check("| A | V |\n|---|---:|\n| x | 0.5 |\n| y | 0.5 |\n| Total | 1.2 |\n")
    assert bad.findings[0]["status"] == "mismatch"


def test_subtotal_no_double_count(check):
    text = (__import__("conftest").SAMPLES / "units.md").read_text(encoding="utf-8")
    ctx = check(text)
    rows = {f["line"]: f for f in ctx.findings if f["check"] == "total_row"}
    assert all(f["status"] == "ok" for f in rows.values())
    assert [f["row"] for f in rows.values()] == ["Subtotal", "Subtotal", "Total"]
    assert rows[max(rows)]["exact"] == "50.0000"


def test_subtotal_mismatch_is_reported(check):
    ctx = check("| I | V |\n|---|---:|\n| a | 10 |\n| b | 20 |\n| Subtotal | 40 |\n| c | 5 |\n| Total | 35 |\n")
    status = {f["row"]: f["status"] for f in ctx.findings}
    assert status == {"Subtotal": "mismatch", "Total": "ok"}


def test_mean_row(check):
    good = check("| R | V |\n|---|---:|\n| a | 1,240 |\n| b | 980 |\n| c | 881 |\n| Average | 1,033.7 |\n")
    assert [(f["check"], f["status"]) for f in good.findings] == [("mean_row", "ok")]
    bad = check("| R | V |\n|---|---:|\n| a | 10 |\n| b | 20 |\n| Mean | 17 |\n")
    f = bad.findings[0]
    assert (f["status"], f["expected"]) == ("mismatch", "15")


def test_total_column(check):
    text = ("| Region | Q1 | Q2 | Total |\n|---|---:|---:|---:|\n"
            "| N | 10 | 20 | 30 |\n| S | 5 | 6 | 15 |\n")
    ctx = check(text)
    status = {f["row"]: (f["status"], f["expected"]) for f in ctx.findings if f["check"] == "total_column"}
    assert status == {"N": ("ok", "30"), "S": ("mismatch", "11")}


def test_percent_sum_and_share(check):
    text = ("| Ch | Orders | Share |\n|---|---:|---:|\n| a | 50 | 50% |\n| b | 30 | 30% |\n| c | 20 | 25% |\n")
    ctx = check(text)
    codes = {(f["check"], f["status"]) for f in ctx.findings}
    assert ("percent_sum", "mismatch") in codes and ("share_vs_value", "mismatch") in codes
    ps = [f for f in ctx.findings if f["check"] == "percent_sum"][0]
    assert ps["line"] == 1 and ps["stated"] == "105%" and ps["expected"] == "100%"  # header line (no total row)


def test_percent_sum_reports_total_row_line_when_present(check):
    text = "| Ch | N | Share |\n|---|---:|---:|\n| a | 5 | 70% |\n| b | 5 | 50% |\n| Total | 10 | 120% |\n"
    ps = [f for f in check(text).findings if f["check"] == "percent_sum"][0]
    assert ps["line"] == 5


def test_growth_columns_are_not_treated_as_shares(check):
    text = "| Item | Sales | Growth % |\n|---|---:|---:|\n| a | 10 | 5% |\n| b | 20 | 7% |\n| Total | 30 | 6% |\n"
    ctx = check(text)
    assert {f["check"] for f in ctx.findings} == {"total_row"}


def test_non_additive_headers_skip_total_row(check):
    text = "| Item | Avg price |\n|---|---:|\n| a | 10 |\n| b | 20 |\n| Total | 15 |\n"
    assert check(text).findings == []


def test_ignore_comment_skips_next_table(check):
    text = ("<!-- tallycheck:ignore -->\n| A | V |\n|---|---:|\n| x | 1 |\n| Total | 9 |\n\n"
            "| A | V |\n|---|---:|\n| x | 1 |\n| Total | 9 |\n")
    ctx = check(text)
    assert [f["line"] for f in ctx.findings] == [10]
    assert ctx.findings[0]["table"] == 2


def test_ignore_comment_skips_next_prose_line_only(check):
    text = ("<!-- tallycheck:ignore -->\nGrowth was 99% from 100 to 101.\n"
            "Growth was 99% from 100 to 101.\n")
    ctx = check(text)
    assert [f["line"] for f in ctx.findings] == [3]


def test_code_fences_are_ignored(check):
    text = "```\n| A | V |\n|---|---:|\n| x | 1 |\n| Total | 9 |\n```\n"
    assert check(text).findings == []


def test_unaligned_and_padded_cells(check):
    text = "|A|V|\n|:--|--:|\n|x|1|\n|y|2|\n|Total|9|\n"
    assert check(text).findings[0]["status"] == "mismatch"


def test_text_columns_are_ignored(check):
    text = "| A | Note | V |\n|---|---|---:|\n| x | fine | 1 |\n| y | ok | 2 |\n| Total | - | 3 |\n"
    ctx = check(text)
    assert [(f["column"], f["status"]) for f in ctx.findings] == [("V", "ok")]


def test_no_numbers_no_findings(check):
    ctx = check("# Title\n\nJust words here.\n")
    assert ctx.findings == [] and ctx.skipped == []
