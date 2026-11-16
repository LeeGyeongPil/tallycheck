"""The evaluation set is an artifact too: check its shape, fixtures and regexes."""
import re
from pathlib import Path

import pytest
from conftest import ROOT, SAMPLES, clean_env, run_cli

EVALS = ROOT / "evals"


def front(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n"), path
    head = text.split("---\n")[1]
    out = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def body(path: Path) -> str:
    return path.read_text(encoding="utf-8").split("---\n", 2)[2]


def cases(prefix: str):
    return sorted(p for p in EVALS.iterdir() if p.is_dir() and p.name.startswith(prefix))


def test_eval_set_composition():
    trigger = cases("trigger-")
    near = cases("notrigger-near-")
    far = [p for p in cases("notrigger-") if not p.name.startswith("notrigger-near-")]
    tasks = cases("task-")
    errors = [p for p in tasks if p.name.startswith("task-error-")]
    korean = [p for p in trigger if re.search(r"[가-힣]", body(p / "prompt.md"))]
    assert len(trigger) == 12 and len(korean) >= 2
    assert len(near) == 7 and len(near) + len(far) == 10
    assert len(tasks) == 6 and len(errors) >= 1
    for case in trigger + near + far + tasks:
        assert (case / "prompt.md").is_file(), case
        assert front(case / "prompt.md")["name"] == case.name


def test_trigger_prompts_do_not_name_the_skill():
    for case in cases("trigger-"):
        text = body(case / "prompt.md").lower()
        assert "tallycheck" not in text and "skill" not in text, case.name


def test_graders_by_kind():
    for case in cases("trigger-"):
        g = front(case / "graders" / "skill-fired.md")
        assert g["type"] == "tool_used" and g["tool"] == "Skill" and "tallycheck" in g["input_match"]
    for case in [p for p in cases("notrigger-")]:
        g = front(case / "graders" / "skill-not-fired.md")
        assert g["max"] == "0"
    for case in cases("task-"):
        ran = front(case / "graders" / "script-ran.md")
        assert ran["arm"] == "with-only" and "tallycheck" in ran["input_match"]
        values = sorted((case / "graders").glob("value-*.md"))
        assert values, case.name
        # a Skill grader on a task case would inflate the baseline gap
        assert not (case / "graders" / "skill-fired.md").exists()


def test_every_task_has_fixtures_and_exact_value_regexes():
    for case in cases("task-"):
        fixtures = [p for p in (EVALS / "fixtures" / case.name).iterdir() if p.is_file()]
        assert fixtures, case.name
        for fx in fixtures:
            assert fx.read_bytes() == (SAMPLES / fx.name).read_bytes(), f"{fx} drifted from samples/"
        for g in (case / "graders").glob("value-*.md"):
            head = front(g)
            assert head["type"] == "regex"
            pattern = head["pattern"].strip("'")
            re.compile(pattern)
            assert not any(tok in pattern for tok in ("(?P<", "\\A", "\\Z")), g


@pytest.mark.parametrize("name,args,out_name", [
    ("task-q3-shares", ["q3_report.md", "--format", "json", "--lang", "en"], "result.json"),
    ("task-ko-growth", ["q3_report.md", "--lang", "ko"], "result.md"),
    ("task-rounding-ok", ["rounding_ok.md", "--format", "json", "--lang", "en"], "result.json"),
    ("task-csv-reconcile", ["orders_report.md", "--data", "orders.csv", "--group", "channel",
                            "--format", "json", "--lang", "en"], "result.json"),
    ("task-unit-confusion", ["units.md", "--format", "json", "--lang", "en"], "result.json"),
])
def test_value_regexes_match_real_script_output(name, args, out_name, tmp_path):
    """Run the script on the fixture and check every file-regex of that task against its real output."""
    fixture_dir = EVALS / "fixtures" / name
    out = tmp_path / out_name
    proc = run_cli(*[str(fixture_dir / a) if (fixture_dir / a).exists() else a for a in args],
                   "--out", str(out), "--exit-zero")
    assert proc.returncode == 0, proc.stderr
    text = out.read_text(encoding="utf-8")
    for g in sorted((EVALS / name / "graders").glob("value-*.md")):
        pattern = front(g)["pattern"].strip("'")
        assert re.search(pattern, text), f"{g.name}: {pattern}"


def test_error_task_regex_matches_real_error():
    fixture_dir = EVALS / "fixtures" / "task-error-bad-column"
    proc = run_cli(str(fixture_dir / "orders_report.md"), "--data", str(fixture_dir / "orders.csv"),
                   "--group", "channel", "--col", "Amount=sum:revenue", "--lang", "en")
    assert proc.returncode == 2
    pattern = front(next((EVALS / "task-error-bad-column" / "graders").glob("value-*.md")))["pattern"].strip("'")
    assert re.search(pattern, proc.stderr)


def test_mutations_are_caught_by_the_regexes(tmp_path):
    """A fake script that always says 'no mismatches' must fail the q3 task's regexes."""
    text = '{"summary": {"checked": 18, "ok": 18, "mismatches": 0}}'
    patterns = [front(g)["pattern"].strip("'") for g in (EVALS / "task-q3-shares" / "graders").glob("value-*.md")]
    assert not all(re.search(p, text) for p in patterns)
    assert sum(1 for p in patterns if not re.search(p, text)) >= 3


def test_error_task_regex_matches_on_korean_host_when_following_skill_md():
    """Regression (round 3): the eval host has LANG=ko_KR. Following SKILL.md (always --lang in the
    user's language, here English) must give the English error line the grader expects."""
    fixture_dir = EVALS / "fixtures" / "task-error-bad-column"
    proc = run_cli(str(fixture_dir / "orders_report.md"), "--data", str(fixture_dir / "orders.csv"),
                   "--group", "channel", "--col", "Amount=sum:revenue", "--lang", "en",
                   env=clean_env(LANG="ko_KR.UTF-8", LC_ALL="ko_KR.UTF-8"))
    assert proc.returncode == 2
    pattern = front(next((EVALS / "task-error-bad-column" / "graders").glob("value-*.md")))["pattern"].strip("'")
    assert re.search(pattern, proc.stderr)
    assert "hint:" in proc.stderr


def test_skill_md_always_passes_lang():
    """Every runnable command in SKILL.md carries --lang, so output never falls back to the machine locale."""
    text = (ROOT / "skills" / "tallycheck" / "SKILL.md").read_text(encoding="utf-8")
    assert "Always pass `--lang` in the user's language" in text
    commands = re.findall(r"`(python3 scripts/tallycheck\.py[^`]*)`", text)
    assert commands and all("--lang" in c for c in commands)
    assert "`--col \"Amount=sum:revenue\" --lang en`" in text


def test_skill_description_covers_missed_trigger_phrasings():
    """Regression (round 3): trigger-04 (Total row) and trigger-09 (Average row) on small pasted tables did not fire."""
    text = (ROOT / "skills" / "tallycheck" / "SKILL.md").read_text(encoding="utf-8")
    desc = re.search(r"^description: (.*)$", text, re.M).group(1)
    assert len(desc) <= 1024 and "<" not in desc and ">" not in desc
    assert desc.startswith("Checks numbers already written")
    for phrase in ("Total, Subtotal or Average row matches the rows above it", "pasted into the chat",
                   "Use when", "Checks numbers already written", "It only verifies existing text",
                   "not for making charts or visualizations from data",
                   "computing new totals or statistics from raw data"):
        assert phrase in desc, phrase


def test_skill_description_covers_self_generated_report_and_fix_requests():
    """Regression (round 4): on opus, trigger-08 ("numeric sanity check on the report you just generated")
    and trigger-12 ("방금 만든 월간 리포트에서 숫자 틀린 곳 찾아서 고쳐 줘") did not fire, because the
    description only spoke of verifying text, not of the assistant's own report or of fixing wrong numbers."""
    text = (ROOT / "skills" / "tallycheck" / "SKILL.md").read_text(encoding="utf-8")
    desc = re.search(r"^description: (.*)$", text, re.M).group(1)
    for phrase in ("also one the assistant just generated", "numeric sanity check", "a report you just wrote",
                   "find and fix wrong numbers", "then guides fixing the wrong cells"):
        assert phrase in desc, phrase
    # 고치기 요청까지 넓힌 만큼, 글자 교정·표 서식 요청(notrigger-02·03)은 명시적으로 제외한다.
    for phrase in ("proofreading", "table formatting", "Excel formulas", "fact-checking against outside sources"):
        assert phrase in desc, phrase
    # 평가 질의 문장을 그대로 베끼지 않는다(말투만 포괄).
    for prompt in cases("trigger-") + cases("notrigger-"):
        assert body(prompt / "prompt.md").strip() not in desc
    step1 = next(line for line in text.splitlines() if line.startswith("1. "))
    assert "find that file in the working folder first" in step1


def test_skill_md_tells_agent_to_surface_missing_column_error():
    """Regression: task-error-bad-column scored 0.5 because the agent swapped columns silently."""
    text = (ROOT / "skills" / "tallycheck" / "SKILL.md").read_text(encoding="utf-8")
    assert "exactly as the user named them" in text
    assert "never substitute a similar column" in text
    assert "quote its error line verbatim" in text
    # QA Q-7: 데이터 파일을 아예 열지 말라는 과한 지시 대신, 지정한 열로 먼저 돌려 오류·힌트를 보게 한다.
    assert "do not open the data" not in text
    assert "let its error and hint list the available ones" in text


def test_skill_md_mentions_out_never_overwrites_inputs():
    text = (ROOT / "skills" / "tallycheck" / "SKILL.md").read_text(encoding="utf-8")
    assert "refuses an `--out` path that is the report or the data file" in text


def test_not_fired_graders_scoped_to_tallycheck():
    """Regression (v2): an unscoped not-fired grader counted any Skill call (e.g. a charting skill) as a misfire."""
    reference = front(cases("trigger-")[0] / "graders" / "skill-fired.md")["input_match"]
    for case in cases("notrigger-"):
        g = front(case / "graders" / "skill-not-fired.md")
        assert g["tool"] == "Skill" and g["max"] == "0"
        pattern = g["input_match"].strip("'")
        assert re.search(pattern, '{"skill": "tallycheck:tallycheck"}')
        assert re.search(pattern, '{"skill": "tallycheck"}')
        assert not re.search(pattern, '{"skill": "data-viz"}')
        assert g["input_match"] == reference


def test_skill_md_saves_result_with_script_out():
    """Regression (v2): task-ko-growth scored 0.25 when the agent wrote result.md itself."""
    text = (ROOT / "skills" / "tallycheck" / "SKILL.md").read_text(encoding="utf-8")
    assert "create that file with the script itself" in text
    assert "Do not write, rewrite, translate, filter or summarize that file yourself" in text
    assert "even when only one kind of number was asked about" in text
    assert "`python3 scripts/tallycheck.py q3_report.md --lang ko --out result.md`" in text
    step4 = next(line for line in text.splitlines() if line.startswith("4. "))
    assert "chat answer" in step4


def test_ko_growth_following_skill_md_on_english_host(tmp_path):
    """The SKILL.md Korean save command on an English host satisfies every task-ko-growth regex;
    without --lang the Korean header (value-3) is missing."""
    fixture = EVALS / "fixtures" / "task-ko-growth" / "q3_report.md"
    env = clean_env(LANG="en_US.UTF-8", LC_ALL="en_US.UTF-8")
    out = tmp_path / "result.md"
    proc = run_cli(str(fixture), "--lang", "ko", "--out", str(out), "--exit-zero", env=env)
    assert proc.returncode == 0, proc.stderr
    patterns = {g.name: front(g)["pattern"].strip("'")
                for g in sorted((EVALS / "task-ko-growth" / "graders").glob("value-*.md"))}
    assert len(patterns) == 3
    text = out.read_text(encoding="utf-8")
    assert all(re.search(p, text) for p in patterns.values())
    bare = tmp_path / "bare.md"
    run_cli(str(fixture), "--out", str(bare), "--exit-zero", env=env)
    assert not re.search(patterns["value-3.md"], bare.read_text(encoding="utf-8"))
