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
    for phrase in ("Total, Subtotal or Average row matches the rows above it", "pasted into the chat",
                   "Use when", "Not for drawing charts or plots", "computing new totals or statistics from raw data"):
        assert phrase in desc, phrase


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
