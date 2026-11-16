# Changelog

All notable changes to this project are documented in this file.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.1] - 2026-11-16

### Changed
- `SKILL.md` tells the agent to create saved result files with the script's own `--out` (never rewrite, filter or summarize them), shows the Korean `--lang ko --out` example and keeps the per-mismatch report in the chat answer.
- `SKILL.md` description leads with "Checks numbers already written" and states it only verifies existing text, so chart and CSV requests do not trigger it.
- The not-fired eval graders are scoped to tallycheck; three regression tests were added and two updated.
- README: the evaluation table shows the re-measured results and the "never edited" wording is clearer.

## [0.1.0] - 2026-11-16

### Added
- `tallycheck.py`: recompute totals, subtotals, averages, share columns, growth rates and percentage points in markdown reports (English and Korean) with rounding-aware interval arithmetic.
- Source reconciliation against CSV/JSON (`--data`, `--group`, `--col`) with count, sum, mean and share aggregates.
- Markdown and JSON output, exit codes 0/1/2, `--exit-zero`, `--out`, and `--lang en|ko`.
- Agent Skills folder (`SKILL.md`, `references/checks.md`), Claude Code plugin manifests, sample reports and an evaluation set.
- Input errors for a missing `--group`/`--col` column or a malformed `--col` print a second `hint:` line with the corrected option (typo suggestions only, never a different column).
- `SKILL.md` tells the agent to pass `--lang` in the user's language, so output does not depend on the machine locale.
- `--out` refuses a path that is one of the input reports or the `--data` file (exit 2 with a hint), so the report is never overwritten; a non-UTF-8 report or data file exits 2 with a re-save hint, and a UTF-8 BOM is accepted.
