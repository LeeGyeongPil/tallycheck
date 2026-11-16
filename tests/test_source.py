"""Reconciliation with CSV/JSON source data."""
import json

import pytest
from conftest import SAMPLES

REPORT = (SAMPLES / "orders_report.md").read_text(encoding="utf-8")
CSV = str(SAMPLES / "orders.csv")


def source(tc, path=CSV, group="channel", cols=()):
    return tc.Source(path, group, list(cols))


def run(check, tc, text=REPORT, **kw):
    return check(text, "en", source(tc, **kw))


def bad(ctx):
    return {(f["line"], f["check"]): (f["stated"], f["expected"]) for f in ctx.findings
            if f["status"] == "mismatch"}


EXPECTED = {(6, "source_count"): ("3", "2"), (7, "source_sum"): ("2.4", "2.2"),
            (8, "source_count"): ("6", "5"), (8, "source_sum"): ("12.0", "11.8")}


def test_planted_mismatches_with_explicit_cols(check, tc):
    ctx = run(check, tc, cols=["Orders=count", "Amount=sum:amount", "Avg amount=mean:amount"])
    assert bad(ctx) == EXPECTED
    web = [f for f in ctx.findings if f["row"] == "Web" and f["check"].startswith("source_")]
    assert web and all(f["status"] == "ok" for f in web)
    assert ctx.mapped == ["Orders=count", "Amount=sum:amount", "Avg amount=mean:amount"]


def test_auto_mapping_without_col(check, tc):
    ctx = run(check, tc)
    assert bad(ctx) == EXPECTED
    assert ctx.mapped == ["Orders=count", "Amount=sum:amount"]


def test_mean_is_checked(check, tc):
    text = REPORT.replace("| Web | 2 | 4.6 | 2.3 |", "| Web | 2 | 4.6 | 2.9 |")
    ctx = run(check, tc, text=text, cols=["Avg amount=mean:amount"])
    only_mean = {k: v for k, v in bad(ctx).items() if k[1] == "source_mean"}
    assert only_mean == {(5, "source_mean"): ("2.9", "2.3")}


def test_share_spec(check, tc):
    text = ("| Channel | Share |\n|---|---:|\n| Web | 39% |\n| Store | 42% |\n| Phone | 19% |\n| Total | 100% |\n")
    ctx = check(text, "en", source(tc, cols=["Share=share:amount"]))
    got = {f["row"]: (f["status"], f["expected"]) for f in ctx.findings if f["check"] == "source_share"}
    assert got == {"Web": ("ok", "39%"), "Store": ("ok", "42%"), "Phone": ("ok", "19%"), "Total": ("ok", "100%")}
    wrong = check(text.replace("| Store | 42% |", "| Store | 50% |"), "en", source(tc, cols=["Share=share:amount"]))
    assert [f["row"] for f in wrong.findings if f["status"] == "mismatch" and f["check"] == "source_share"] == ["Store"]


def test_group_matching_is_case_insensitive_and_reports_unmatched(check, tc):
    text = "| Channel | Orders |\n|---|---:|\n| web | 2 |\n| Kiosk | 1 |\n"
    ctx = check(text, "en", source(tc, cols=["Orders=count"]))
    reasons = {(s["text"], s["reason"]) for s in ctx.skipped}
    assert ("Kiosk", "group_not_in_data") in reasons
    assert ("Store", "group_not_in_report") in reasons and ("Phone", "group_not_in_report") in reasons
    assert [f["status"] for f in ctx.findings if f["check"] == "source_count"] == ["ok"]


def test_table_without_matching_groups_is_left_alone(check, tc):
    text = "| Region | Orders |\n|---|---:|\n| North | 2 |\n| South | 3 |\n"
    ctx = check(text, "en", source(tc))
    assert [f for f in ctx.findings if f["check"].startswith("source_")] == []


def test_json_array_and_records_forms(check, tc, tmp_path):
    rows = [{"channel": "Web", "amount": 2.5}, {"channel": "Web", "amount": 2.1},
            {"channel": "Store", "amount": 5.0}]
    for name, payload in (("a.json", rows), ("b.json", {"records": rows})):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        text = "| Channel | Orders | Amount |\n|---|---:|---:|\n| Web | 2 | 4.6 |\n| Store | 1 | 5.0 |\n"
        ctx = check(text, "en", source(tc, str(path)))
        assert all(f["status"] == "ok" for f in ctx.findings if f["check"].startswith("source_")), name


def test_unknown_column_error_lists_available(tc):
    with pytest.raises(tc.UsageError) as err:
        source(tc, cols=["Revenue=sum:revenue"])
    assert err.value.key == "column_not_found"
    assert err.value.kwargs["available"] == "channel, order_id, amount"


def test_unknown_group_column(tc):
    with pytest.raises(tc.UsageError) as err:
        source(tc, group="region")
    assert err.value.key == "column_not_found"


@pytest.mark.parametrize("spec", ["Orders", "Orders=total", "Orders=sum", "=count", "Orders=sum:"])
def test_bad_col_spec(tc, spec):
    with pytest.raises(tc.UsageError) as err:
        source(tc, cols=[spec])
    assert err.value.key == "bad_col_spec"


def test_non_numeric_field_is_a_data_error(tc, tmp_path):
    path = tmp_path / "d.csv"
    path.write_text("channel,amount\nWeb,abc\n", encoding="utf-8")
    with pytest.raises(tc.UsageError) as err:
        source(tc, str(path), cols=["Amount=sum:amount"])
    assert err.value.key == "data_parse_error"


def test_bad_json_shape(tc, tmp_path):
    path = tmp_path / "d.json"
    path.write_text('{"a": 1}', encoding="utf-8")
    with pytest.raises(tc.UsageError) as err:
        source(tc, str(path))
    assert err.value.key == "data_parse_error"


def test_missing_data_file(tc, tmp_path):
    with pytest.raises(tc.UsageError) as err:
        source(tc, str(tmp_path / "none.csv"))
    assert err.value.key == "file_not_found"


def test_csv_without_header(tc, tmp_path):
    path = tmp_path / "e.csv"
    path.write_text("", encoding="utf-8")
    with pytest.raises(tc.UsageError) as err:
        source(tc, str(path))
    assert err.value.key == "data_parse_error"


def test_missing_values_are_skipped_in_sums(check, tc, tmp_path):
    path = tmp_path / "m.csv"
    path.write_text("channel,amount\nWeb,1.5\nWeb,\nWeb,2.5\n", encoding="utf-8")
    text = "| Channel | Orders | Amount |\n|---|---:|---:|\n| Web | 3 | 4.0 |\n"
    ctx = check(text, "en", source(tc, str(path)))
    assert all(f["status"] == "ok" for f in ctx.findings if f["check"].startswith("source_"))
