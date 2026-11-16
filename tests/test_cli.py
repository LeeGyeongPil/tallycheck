"""Command-line behaviour: exit codes, output formats, error paths."""
import json

import pytest
from conftest import SAMPLES, clean_env, load_json, run_cli

Q3 = str(SAMPLES / "q3_report.md")
ORDERS = [str(SAMPLES / "orders_report.md"), "--data", str(SAMPLES / "orders.csv"), "--group", "channel"]


def test_q3_json_exit_1_and_ten_mismatches():
    p = run_cli(Q3, "--format", "json")
    assert p.returncode == 1
    data = load_json(p)
    assert data["tool"] == "tallycheck" and data["version"] == "0.1.3"
    assert data["summary"] == {"checked": 18, "ok": 8, "mismatches": 10, "skipped": 0}
    bad = {(f["line"], f["check"]): f for f in data["findings"] if f["status"] == "mismatch"}
    assert {k: v["expected"] for k, v in bad.items()} == {
        (5, "share_vs_value"): "40.0%", (6, "share_vs_value"): "31.6%", (7, "share_vs_value"): "28.4%",
        (12, "share_vs_value"): "41%", (13, "share_vs_value"): "33%", (14, "share_vs_value"): "25%",
        (15, "percent_sum"): "100%", (17, "growth_rate"): "18.4%", (23, "growth_rate"): "20%",
        (25, "growth_rate"): "19%"}
    assert bad[(17, "growth_rate")]["exact"] == "18.3588"
    assert bad[(15, "percent_sum")]["stated"] == "116%"
    ok_lines = {f["line"] for f in data["findings"] if f["status"] == "ok" and f["check"] in ("growth_rate", "pp_change")}
    assert {18, 19, 24} <= ok_lines
    first = data["findings"][0]
    assert first["interval"] == ["39.9645", "40.0097"]
    assert set(first) == {"file", "line", "check", "status", "table", "row", "column", "stated",
                          "expected", "exact", "interval", "message"}


def test_rounding_ok_sample_exit_0():
    p = run_cli(str(SAMPLES / "rounding_ok.md"), "--format", "json")
    assert p.returncode == 0
    s = load_json(p)["summary"]
    assert s["mismatches"] == 0 and s["checked"] >= 6


def test_units_sample():
    data = load_json(run_cli(str(SAMPLES / "units.md"), "--format", "json"))
    bad = [f for f in data["findings"] if f["status"] == "mismatch"]
    assert [(f["check"], f["expected"]) for f in bad] == [("unit_confusion", "9%")]
    assert "4%p" in bad[0]["message"]


def test_source_reconcile_exit_1_four_mismatches():
    p = run_cli(*ORDERS, "--col", "Orders=count", "--col", "Amount=sum:amount",
                "--col", "Avg amount=mean:amount", "--format", "json")
    assert p.returncode == 1
    data = load_json(p)
    assert data["summary"]["mismatches"] == 4
    got = {(f["line"], f["check"]): (f["stated"], f["expected"]) for f in data["findings"] if f["status"] == "mismatch"}
    assert got == {(6, "source_count"): ("3", "2"), (7, "source_sum"): ("2.4", "2.2"),
                   (8, "source_count"): ("6", "5"), (8, "source_sum"): ("12.0", "11.8")}


def test_md_output_lists_line_check_where():
    p = run_cli(Q3, "--lang", "en")
    assert p.returncode == 1
    assert "| 5 | share_vs_value | North / Share | 41.3% | 40.0% |" in p.stdout
    assert p.stdout.startswith("Checked 18: 8 ok, 10 mismatch(es), 0 skipped.")


def test_md_when_clean_and_when_empty(tmp_path):
    p = run_cli(str(SAMPLES / "rounding_ok.md"), "--lang", "en")
    assert p.stdout.strip() == "No mismatches (10 checked)." and p.returncode == 0
    empty = tmp_path / "e.md"
    empty.write_text("Nothing numeric here.\n", encoding="utf-8")
    q = run_cli(str(empty), "--lang", "en", "--format", "json")
    assert q.returncode == 0 and load_json(q)["summary"]["checked"] == 0
    assert "No numeric claims" in run_cli(str(empty), "--lang", "en").stdout


def test_exit_zero_flag():
    assert run_cli(Q3, "--exit-zero").returncode == 0
    assert run_cli(str(SAMPLES / "nope.md"), "--exit-zero").returncode == 2


def test_out_file(tmp_path):
    out = tmp_path / "r.json"
    p = run_cli(Q3, "--format", "json", "--out", str(out), "--lang", "en")
    assert p.returncode == 1
    assert json.loads(out.read_text(encoding="utf-8"))["summary"]["mismatches"] == 10
    assert "Wrote" in p.stdout and "10 mismatch" in p.stdout


def test_out_unwritable_is_exit_2(tmp_path):
    p = run_cli(Q3, "--out", str(tmp_path / "no" / "dir" / "x.md"), "--lang", "en")
    assert p.returncode == 2 and "cannot write output file" in p.stderr


def test_multiple_files_prefix_lines_with_file_name():
    p = run_cli(Q3, str(SAMPLES / "units.md"), "--lang", "en")
    assert p.returncode == 1
    assert f"{Q3}:5" in p.stdout
    data = load_json(run_cli(Q3, str(SAMPLES / "units.md"), "--format", "json"))
    assert len(data["files"]) == 2 and {f["file"] for f in data["findings"]} == set(data["files"])


def test_column_not_found_exit_2():
    p = run_cli(*ORDERS, "--col", "Revenue=sum:revenue", "--lang", "en")
    assert p.returncode == 2
    assert "column not found in data: revenue (available: channel, order_id, amount)" in p.stderr
    assert p.stdout == ""


def test_column_not_found_prints_usage_hint_without_guessing_a_column():
    """Regression (skill-eval round 3): the error must say how to fix --col, but never pick 'amount' for 'revenue'."""
    p = run_cli(*ORDERS, "--col", "Amount=sum:revenue", "--lang", "en")
    lines = p.stderr.strip().splitlines()
    assert p.returncode == 2 and len(lines) == 2
    assert lines[0] == "tallycheck: error: column not found in data: revenue (available: channel, order_id, amount)"
    assert lines[1].startswith("tallycheck: hint: write --col \"Amount=sum:COLUMN\"")
    assert "channel, order_id, amount" in lines[1]
    assert "Amount=sum:amount" not in p.stderr


def test_column_typo_gets_a_close_match_hint():
    p = run_cli(*ORDERS, "--col", "Avg amount=mean:amont", "--lang", "en")
    assert p.returncode == 2
    assert "tallycheck: hint: did you mean --col \"Avg amount=mean:amount\"?" in p.stderr


def test_group_column_hints():
    base = [str(SAMPLES / "orders_report.md"), "--data", str(SAMPLES / "orders.csv"), "--lang", "en"]
    typo = run_cli(*base, "--group", "chanel")
    assert typo.returncode == 2 and "tallycheck: hint: did you mean --group channel?" in typo.stderr
    other = run_cli(*base, "--group", "region")
    assert other.returncode == 2
    assert "column not found in data: region (available: channel, order_id, amount)" in other.stderr
    assert "tallycheck: hint: write --group COLUMN" in other.stderr


def test_bad_col_spec_hints():
    no_kind = run_cli(*ORDERS, "--col", "Amount=revenue", "--lang", "en")
    assert no_kind.returncode == 2
    assert "invalid --col: Amount=revenue" in no_kind.stderr
    assert "did you mean --col \"Amount=sum:revenue\"" in no_kind.stderr
    bare = run_cli(*ORDERS, "--col", "Orders", "--lang", "en")
    assert bare.returncode == 2 and "tallycheck: hint: examples: --col \"Orders=count\"" in bare.stderr


def test_hint_line_is_localized():
    p = run_cli(*ORDERS, "--col", "Amount=sum:revenue", "--lang", "ko")
    lines = p.stderr.strip().splitlines()
    assert lines[0] == "tallycheck: 오류: 데이터에 없는 열입니다: revenue (사용 가능: channel, order_id, amount)"
    assert lines[1].startswith("tallycheck: 힌트: --col \"Amount=sum:COLUMN\"")


def test_lang_flag_beats_korean_machine_locale():
    """Root cause of the failed error task: the eval host runs with LANG=ko_KR, so without --lang the error is Korean."""
    korean_host = clean_env(LANG="ko_KR.UTF-8")
    without = run_cli(*ORDERS, "--col", "Amount=sum:revenue", env=korean_host)
    assert "데이터에 없는 열입니다" in without.stderr
    with_en = run_cli(*ORDERS, "--col", "Amount=sum:revenue", "--lang", "en", env=korean_host)
    assert "tallycheck: error: column not found in data: revenue" in with_en.stderr


def test_input_errors_exit_2(tmp_path):
    missing = run_cli(str(tmp_path / "absent.md"), "--lang", "en")
    assert missing.returncode == 2 and "file not found:" in missing.stderr and "absent.md" in missing.stderr
    needs_group = run_cli(Q3, "--data", str(SAMPLES / "orders.csv"), "--lang", "en")
    assert needs_group.returncode == 2 and "--data requires --group" in needs_group.stderr
    needs_data = run_cli(Q3, "--group", "channel", "--lang", "en")
    assert needs_data.returncode == 2 and "require --data" in needs_data.stderr
    bad_col = run_cli(*ORDERS, "--col", "Orders", "--lang", "en")
    assert bad_col.returncode == 2 and "invalid --col: Orders" in bad_col.stderr
    bad_data = run_cli(Q3, "--data", str(tmp_path / "none.csv"), "--group", "x", "--lang", "en")
    assert bad_data.returncode == 2 and "file not found:" in bad_data.stderr
    no_args = run_cli()
    assert no_args.returncode == 2
    bad_lang = run_cli(Q3, "--lang", "fr")
    assert bad_lang.returncode == 2
    directory = run_cli(str(tmp_path), "--lang", "en")
    assert directory.returncode == 2 and "cannot read file" in directory.stderr


def test_binary_report_is_exit_2(tmp_path):
    path = tmp_path / "b.md"
    path.write_bytes(b"\xff\xfe\x00bad")
    p = run_cli(str(path), "--lang", "en")
    assert p.returncode == 2 and "file is not UTF-8 text" in p.stderr


def test_out_refuses_to_overwrite_inputs(tmp_path):
    """QA Q-1: --out pointing at the report or the --data file must not destroy it."""
    report = tmp_path / "x.md"
    report.write_bytes((SAMPLES / "units.md").read_bytes())
    original = report.read_bytes()
    same = run_cli(str(report), "--out", str(report), "--lang", "en")
    assert same.returncode == 2
    assert f"tallycheck: error: refusing to overwrite an input file with the result: {report}" in same.stderr
    assert "tallycheck: hint: choose another --out path, for example --out result.md" in same.stderr
    assert report.read_bytes() == original and same.stdout == ""
    # 다른 표기(./x.md, 심볼릭 링크)로 같은 파일을 가리켜도 거부한다.
    dotted = run_cli("x.md", "--out", "./x.md", "--format", "json", "--lang", "en", cwd=tmp_path)
    assert dotted.returncode == 2 and "--out result.json" in dotted.stderr
    link = tmp_path / "link.md"
    link.symlink_to(report)
    assert run_cli(str(report), "--out", str(link), "--lang", "en").returncode == 2
    assert report.read_bytes() == original
    # --data 파일도 마찬가지이고, 한국어 메시지·힌트가 나온다.
    data = tmp_path / "orders.csv"
    data.write_bytes((SAMPLES / "orders.csv").read_bytes())
    data_before = data.read_bytes()
    p = run_cli(str(SAMPLES / "orders_report.md"), "--data", str(data), "--group", "channel",
                "--out", str(data), "--lang", "ko")
    assert p.returncode == 2
    assert f"tallycheck: 오류: 입력 파일을 결과로 덮어쓰지 않습니다: {data}" in p.stderr
    assert "tallycheck: 힌트: --out 에 다른 경로를 주세요" in p.stderr
    assert data.read_bytes() == data_before
    # 입력이 아닌 경로는 그대로 쓴다.
    ok = run_cli(str(report), "--out", str(tmp_path / "result.md"), "--lang", "en")
    assert ok.returncode in (0, 1) and (tmp_path / "result.md").exists()


def test_non_utf8_input_gets_hint(tmp_path):
    """QA Q-2: a cp949 report or data file gets a localized message and a re-save hint, not a codec error."""
    report = tmp_path / "cp949.md"
    report.write_bytes("| 항목 | 값 |\n|---|---|\n| 가 | 1 |\n".encode("cp949"))
    en = run_cli(str(report), "--lang", "en")
    assert en.returncode == 2
    assert f"tallycheck: error: file is not UTF-8 text: {report}" in en.stderr
    assert "tallycheck: hint: re-save the file as UTF-8" in en.stderr
    assert "codec" not in en.stderr and "Traceback" not in en.stderr
    ko = run_cli(str(report), "--lang", "ko")
    assert ko.returncode == 2 and "UTF-8 텍스트 파일이 아닙니다" in ko.stderr and "힌트:" in ko.stderr
    data = tmp_path / "orders.csv"
    data.write_bytes("channel,amount\n웹,1\n".encode("cp949"))
    p = run_cli(str(SAMPLES / "orders_report.md"), "--data", str(data), "--group", "channel", "--lang", "en")
    assert p.returncode == 2
    assert f"file is not UTF-8 text: {data}" in p.stderr and "hint: re-save the file as UTF-8" in p.stderr


def test_report_with_bom_is_read(tmp_path):
    report = tmp_path / "bom.md"
    report.write_bytes(b"\xef\xbb\xbf" + (SAMPLES / "q3_report.md").read_bytes())
    p = run_cli(str(report), "--format", "json", "--lang", "en")
    assert p.returncode == 1 and json.loads(p.stdout)["summary"]["mismatches"] == 10


def test_version_flag():
    p = run_cli("--version")
    assert p.returncode == 0 and "tallycheck 0.1.3" in p.stdout


def test_errors_leave_no_traceback():
    for args in ([], ["--col"], ["x.md", "--format", "xml"]):
        assert "Traceback" not in run_cli(*args).stderr


@pytest.mark.parametrize("name", ["q3_report.md", "rounding_ok.md", "units.md"])
def test_stdout_is_utf8_for_both_languages(name):
    for lang in ("en", "ko"):
        p = run_cli(str(SAMPLES / name), "--lang", lang, env=clean_env(PYTHONIOENCODING="utf-8"))
        assert p.returncode in (0, 1)
