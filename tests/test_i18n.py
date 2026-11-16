"""Bilingual output: identical message keys, precedence of language sources, localized text."""
import json
import re

from conftest import SAMPLES, clean_env, load_json, run_cli

Q3 = str(SAMPLES / "q3_report.md")


def test_message_keys_match(tc):
    en, ko = tc.MESSAGES["en"], tc.MESSAGES["ko"]
    assert set(en) == set(ko)
    for key in en:
        # placeholders must be the same in both languages so format() never fails
        assert sorted(re.findall(r"\{(\w+)", en[key])) == sorted(re.findall(r"\{(\w+)", ko[key])), key
        assert en[key].strip() and ko[key].strip()


def test_every_error_key_has_a_message(tc):
    for key in ("file_not_found", "file_unreadable", "data_needs_group", "needs_data", "column_not_found",
                "bad_col_spec", "data_parse_error", "write_failed"):
        assert "err." + key in tc.MESSAGES["en"]


def test_resolve_lang_order(tc):
    r = tc.resolve_lang
    assert r(None, {}) == "en"
    assert r("ko", {"TALLYCHECK_LANG": "en"}) == "ko"
    assert r("en", {"TALLYCHECK_LANG": "ko", "LANG": "ko_KR.UTF-8"}) == "en"
    assert r(None, {"TALLYCHECK_LANG": "ko", "LC_ALL": "en_US.UTF-8"}) == "ko"
    assert r(None, {"LC_ALL": "en_US.UTF-8", "LC_MESSAGES": "ko_KR", "LANG": "ko_KR"}) == "en"
    assert r(None, {"LC_MESSAGES": "ko_KR", "LANG": "en_US"}) == "ko"
    assert r(None, {"LANG": "ko_KR.UTF-8"}) == "ko"
    assert r(None, {"LANG": "fr_FR.UTF-8"}) == "en"
    assert r(None, {"LC_ALL": "", "LANG": "ko_KR"}) == "ko"


def test_lang_precedence(cli):
    assert cli(Q3, "--lang", "ko", env=clean_env(TALLYCHECK_LANG="en", LANG="en_US")).stdout.startswith("확인")
    assert cli(Q3, env=clean_env(TALLYCHECK_LANG="ko", LC_ALL="en_US.UTF-8")).stdout.startswith("확인")
    assert cli(Q3, env=clean_env(LC_ALL="ko_KR.UTF-8", LANG="en_US.UTF-8")).stdout.startswith("확인")
    assert cli(Q3, env=clean_env(LC_MESSAGES="ko_KR.UTF-8")).stdout.startswith("확인")
    assert cli(Q3, env=clean_env(LANG="ko_KR.UTF-8")).stdout.startswith("확인")
    assert cli(Q3, env=clean_env(LANG="ja_JP.UTF-8")).stdout.startswith("Checked")
    assert cli(Q3, env=clean_env()).stdout.startswith("Checked")
    assert cli(Q3, "--lang", "en", env=clean_env(TALLYCHECK_LANG="ko")).stdout.startswith("Checked")


def test_help_and_md_localized(cli):
    en = cli("--help", "--lang", "en")
    ko = cli("--help", "--lang", "ko")
    assert en.returncode == ko.returncode == 0
    assert "Recompute the numbers" in en.stdout and "마크다운 보고서" in ko.stdout
    assert "Recompute the numbers" not in ko.stdout
    assert "Exit codes" in en.stdout and "종료 코드" in ko.stdout
    md_en = cli(Q3, "--lang", "en").stdout
    md_ko = cli(Q3, "--lang", "ko").stdout
    assert "| Line | Check | Where | Stated | Expected |" in md_en
    assert "| 줄 | 검사 | 위치 | 표기 | 기대값 |" in md_ko
    assert "불일치 없음 (10개 확인)." == cli(str(SAMPLES / "rounding_ok.md"), "--lang", "ko").stdout.strip()
    err_en = cli("nope.md", "--lang", "en").stderr
    err_ko = cli("nope.md", "--lang", "ko").stderr
    assert err_en.startswith("tallycheck: error: file not found: nope.md")
    assert err_ko.startswith("tallycheck: 오류: 파일을 찾을 수 없습니다: nope.md")
    col_ko = cli(str(SAMPLES / "orders_report.md"), "--data", str(SAMPLES / "orders.csv"), "--group", "channel",
                 "--col", "Revenue=sum:revenue", "--lang", "ko").stderr
    assert "데이터에 없는 열입니다: revenue (사용 가능: channel, order_id, amount)" in col_ko


def test_korean_messages_in_json_but_keys_identical(cli):
    en = load_json(cli(Q3, "--lang", "en", "--format", "json"))
    ko = load_json(cli(Q3, "--lang", "ko", "--format", "json"))
    assert en["findings"][0]["message"] != ko["findings"][0]["message"]
    assert "표기" in ko["findings"][0]["message"]


def test_json_keys_language_independent(cli):
    en = load_json(cli(Q3, "--lang", "en", "--format", "json"))
    ko = load_json(cli(Q3, "--lang", "ko", "--format", "json"))

    def strip(d):
        d = json.loads(json.dumps(d))
        for f in d["findings"]:
            f.pop("message")
        return d

    assert list(en) == list(ko)
    assert strip(en) == strip(ko)
    assert {f["check"] for f in en["findings"]} <= {
        "total_row", "total_column", "percent_sum", "share_vs_value", "mean_row", "growth_rate",
        "pp_change", "unit_confusion", "source_count", "source_sum", "source_mean", "source_share"}


def test_skipped_reasons_are_localized(cli, tmp_path):
    path = tmp_path / "a.md"
    path.write_text("| A | V |\n|---|---:|\n| x | 1.234,56 |\n", encoding="utf-8")
    assert "ambiguous number format" in cli(str(path), "--lang", "en").stdout
    assert "숫자 표기가 모호함" in cli(str(path), "--lang", "ko").stdout
    skipped = load_json(cli(str(path), "--format", "json"))["skipped"]
    assert skipped == [{"file": str(path), "line": 3, "text": "1.234,56", "reason": "ambiguous_number"}]


def test_korean_messages_have_no_fixed_particle_after_values(cli, tmp_path):
    # 받침 있는 값(110억)·숫자(110) 뒤에 조사를 고정으로 붙이지 않는다.
    f = tmp_path / "ko.md"
    f.write_text("매출은 100억 원에서 110억 원으로 10% 감소했다.\n"
                 "점유율은 100에서 110으로 20% 늘었다.\n", encoding="utf-8")
    out = cli(str(f), "--lang", "ko", "--format", "json").stdout
    messages = [x["message"] for x in json.loads(out)["findings"]]
    assert len(messages) >= 2
    for m in messages:
        for bad in (" 로의", " 로는", " 로 고치세요"):
            assert bad not in m, m
