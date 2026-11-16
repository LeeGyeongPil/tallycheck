#!/usr/bin/env python3
"""tallycheck - recompute the numbers in a markdown report and flag the wrong ones.

Reads markdown reports, finds pipe tables and growth / percentage-point
sentences (English and Korean), recomputes them with rounding-aware interval
arithmetic and optionally reconciles table cells with a CSV/JSON source.

Standard library only. Exit codes: 0 no mismatch, 1 mismatch found,
2 input or usage error. Run with --help for the options.
"""
from __future__ import annotations

import argparse
import csv
import dataclasses
import difflib
import json
import os
import re
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, getcontext
from typing import Any, Dict, List, Optional, Sequence, Tuple

__version__ = "0.1.2"

getcontext().prec = 50

# --------------------------------------------------------------------------
# Messages (every user-visible sentence lives here, one table per language)
# --------------------------------------------------------------------------

MESSAGES: Dict[str, Dict[str, str]] = {
    "en": {
        "help.description": (
            "Recompute the numbers in markdown reports (table totals, shares, averages, "
            "growth rates, percentage points) with rounding-aware interval arithmetic and "
            "optionally reconcile table cells with a CSV/JSON source. It reports the line, "
            "the check and the value that should be written; it never edits the report."
        ),
        "help.epilog": "Exit codes: 0 no mismatch, 1 mismatch found, 2 input or usage error.",
        "help.report": "markdown report file(s) to check",
        "help.data": "source data (.csv, or .json as an array of objects or {\"records\": [...]})",
        "help.group": "data column that holds the row labels of the report table (needed with --data)",
        "help.col": (
            "map a table header to a source aggregate: HEADER=count|sum:FIELD|mean:FIELD|share:FIELD "
            "(repeatable; headers equal to a data column are mapped to sum automatically)"
        ),
        "help.format": "output format (default: md)",
        "help.out": "write the result to this file and print a one-line summary instead",
        "help.lang": "output language (default: TALLYCHECK_LANG, then LC_ALL, LC_MESSAGES, LANG)",
        "help.exit_zero": "exit 0 even when mismatches are found (input errors still exit 2)",
        "help.version": "show the version and exit",
        "help.help": "show this help message and exit",
        "err.prefix": "error",
        "err.file_not_found": "file not found: {path}",
        "err.file_unreadable": "cannot read file: {path}: {reason}",
        "err.data_needs_group": "--data requires --group",
        "err.needs_data": "--group and --col require --data",
        "err.column_not_found": "column not found in data: {name} (available: {available})",
        "err.bad_col_spec": "invalid --col: {spec} (expected HEADER=count|sum:FIELD|mean:FIELD|share:FIELD)",
        "err.data_parse_error": "cannot read data file: {path}: {reason}",
        "err.write_failed": "cannot write output file: {path}: {reason}",
        "err.out_is_input": "refusing to overwrite an input file with the result: {path}",
        "err.not_utf8": "file is not UTF-8 text: {path}",
        "hint.prefix": "hint",
        "hint.out_other": "choose another --out path, for example --out {example}",
        "hint.resave_utf8": (
            "re-save the file as UTF-8 (for example: iconv -f cp949 -t utf-8 IN > OUT) and run again"
        ),
        "hint.col_close": "did you mean --col \"{header}={kind}:{match}\"?",
        "hint.col_choose": (
            "write --col \"{header}={kind}:COLUMN\" with COLUMN set to one of the data columns "
            "({available}); do not assume another column means the same thing"
        ),
        "hint.group_close": "did you mean --group {match}?",
        "hint.group_choose": (
            "write --group COLUMN with the data column that holds the table's row labels, "
            "one of: {available}"
        ),
        "hint.col_field": "did you mean --col \"{header}=sum:{field}\" (or count, mean:{field}, share:{field})?",
        "hint.col_examples": (
            "examples: --col \"Orders=count\", --col \"Amount=sum:amount\", "
            "--col \"Avg amount=mean:amount\", --col \"Share=share:amount\""
        ),
        "err.bad_data_reason_header": "the CSV file has no header row",
        "err.bad_data_reason_json": "expected a JSON array of objects or {{\"records\": [...]}}",
        "err.bad_data_reason_number": "non-numeric value {value!r} in column {field}",
        "msg.ok": "Recomputed {exact}; {stated} is consistent.",
        "msg.total_row": "{label} / {column}: stated {stated}, but the rows add up to {exact} (write {expected}).",
        "msg.total_column": (
            "{label} / {column}: stated {stated}, but the other columns in this row add up to "
            "{exact} (write {expected})."
        ),
        "msg.percent_sum": (
            "{column}: the shares add up to {stated}, which cannot be 100% even allowing for "
            "rounding (write values that add up to {expected})."
        ),
        "msg.share_vs_value": "{label} / {column}: stated {stated}, but value / total gives {exact} (write {expected}).",
        "msg.mean_row": "{label} / {column}: stated {stated}, but the average of the rows is {exact} (write {expected}).",
        "msg.growth_rate": "'{text}': stated {stated}, but going from {a} to {b} is {exact}% (write {expected}).",
        "msg.pp_change": "'{text}': stated {stated}, but going from {a} to {b} is {exact} points (write {expected}).",
        "msg.unit_confusion": (
            "'{text}': {stated} is not the relative change ({expected}); it matches the "
            "percentage-point difference. Did you mean {alt}?"
        ),
        "msg.unit_confusion_pp": (
            "'{text}': {stated} is not the percentage-point difference ({expected}); it matches the "
            "relative change. Did you mean {alt}?"
        ),
        "msg.source": "{label} / {column}: stated {stated}, but the source data gives {exact} (write {expected}).",
        "md.summary": "Checked {checked}: {ok} ok, {mismatches} mismatch(es), {skipped} skipped.",
        "md.no_mismatch": "No mismatches ({checked} checked).",
        "md.no_claims": "No numeric claims found to check.",
        "md.mapped": "Mapped: {mapped}",
        "md.head": "| Line | Check | Where | Stated | Expected |",
        "md.skipped_title": "Skipped (not judged):",
        "md.skipped_item": "- line {line}: {text} ({reason})",
        "md.wrote": "Wrote {path} ({checked} checked, {mismatches} mismatch(es)).",
        "reason.ambiguous_number": "ambiguous number format",
        "reason.group_not_in_report": "group in the data but not in the table",
        "reason.group_not_in_data": "row label not found in the data",
    },
    "ko": {
        "help.description": (
            "마크다운 보고서의 숫자(표 합계·구성비·평균·증감률·%p)를 반올림을 고려한 구간 산술로 다시 계산하고, "
            "원하면 CSV/JSON 원자료와 표 셀을 대조한다. 몇 번째 줄의 어떤 검사에서 무엇을 써야 하는지 알려 줄 뿐 "
            "보고서를 직접 고치지 않는다."
        ),
        "help.epilog": "종료 코드: 0 불일치 없음, 1 불일치 있음, 2 입력·사용 오류.",
        "help.report": "검사할 마크다운 보고서 파일(여러 개 가능)",
        "help.data": "원자료(.csv, 또는 객체 배열이나 {\"records\": [...]} 형태의 .json)",
        "help.group": "보고서 표의 행 이름이 들어 있는 데이터 열(--data 와 함께 필요)",
        "help.col": (
            "표 머리글을 원자료 집계에 연결: HEADER=count|sum:FIELD|mean:FIELD|share:FIELD "
            "(여러 번 지정 가능, 데이터 열 이름과 같은 머리글은 자동으로 sum 에 연결)"
        ),
        "help.format": "출력 형식(기본: md)",
        "help.out": "결과를 이 파일에 쓰고 한 줄 요약만 출력",
        "help.lang": "출력 언어(기본: TALLYCHECK_LANG, LC_ALL, LC_MESSAGES, LANG 순)",
        "help.exit_zero": "불일치가 있어도 종료 코드 0(입력 오류는 여전히 2)",
        "help.version": "버전을 보여 주고 끝낸다",
        "help.help": "도움말을 보여 주고 끝낸다",
        "err.prefix": "오류",
        "err.file_not_found": "파일을 찾을 수 없습니다: {path}",
        "err.file_unreadable": "파일을 읽을 수 없습니다: {path}: {reason}",
        "err.data_needs_group": "--data 에는 --group 이 필요합니다",
        "err.needs_data": "--group 과 --col 에는 --data 가 필요합니다",
        "err.column_not_found": "데이터에 없는 열입니다: {name} (사용 가능: {available})",
        "err.bad_col_spec": "--col 형식이 올바르지 않습니다: {spec} (HEADER=count|sum:FIELD|mean:FIELD|share:FIELD 형태)",
        "err.data_parse_error": "데이터 파일을 읽을 수 없습니다: {path}: {reason}",
        "err.write_failed": "출력 파일을 쓸 수 없습니다: {path}: {reason}",
        "err.out_is_input": "입력 파일을 결과로 덮어쓰지 않습니다: {path}",
        "err.not_utf8": "UTF-8 텍스트 파일이 아닙니다: {path}",
        "hint.prefix": "힌트",
        "hint.out_other": "--out 에 다른 경로를 주세요. 예: --out {example}",
        "hint.resave_utf8": (
            "파일을 UTF-8 로 다시 저장한 뒤 실행하세요(예: iconv -f cp949 -t utf-8 IN > OUT)"
        ),
        "hint.col_close": "--col \"{header}={kind}:{match}\" 를 뜻한 것 아닌가요?",
        "hint.col_choose": (
            "--col \"{header}={kind}:COLUMN\" 의 COLUMN 을 데이터 열({available}) 중 하나로 쓰세요. "
            "다른 열이 같은 뜻이라고 짐작하지 마세요"
        ),
        "hint.group_close": "--group {match} 를 뜻한 것 아닌가요?",
        "hint.group_choose": "--group COLUMN 에는 표의 행 이름이 들어 있는 데이터 열을 쓰세요. 후보: {available}",
        "hint.col_field": "--col \"{header}=sum:{field}\" (또는 count, mean:{field}, share:{field}) 를 뜻한 것 아닌가요?",
        "hint.col_examples": (
            "예: --col \"Orders=count\", --col \"Amount=sum:amount\", "
            "--col \"Avg amount=mean:amount\", --col \"Share=share:amount\""
        ),
        "err.bad_data_reason_header": "CSV 파일에 머리글 행이 없습니다",
        "err.bad_data_reason_json": "객체 배열이거나 {{\"records\": [...]}} 형태여야 합니다",
        "err.bad_data_reason_number": "{field} 열에 숫자가 아닌 값 {value!r} 이(가) 있습니다",
        "msg.ok": "재계산값 {exact}; {stated} 은(는) 일치합니다.",
        "msg.total_row": "{label} / {column}: 표기 {stated}, 위 행의 합은 {exact} 입니다({expected} 로 고치세요).",
        "msg.total_column": "{label} / {column}: 표기 {stated}, 같은 행 다른 열의 합은 {exact} 입니다({expected} 로 고치세요).",
        "msg.percent_sum": (
            "{column}: 구성비 합이 {stated} 로, 반올림을 감안해도 100% 가 될 수 없습니다"
            "(합이 {expected} 가 되도록 고치세요)."
        ),
        "msg.share_vs_value": "{label} / {column}: 표기 {stated}, 값/합계로 계산하면 {exact} 입니다({expected} 로 고치세요).",
        "msg.mean_row": "{label} / {column}: 표기 {stated}, 위 행의 평균은 {exact} 입니다({expected} 로 고치세요).",
        "msg.growth_rate": "'{text}': 표기 {stated}, {a} 에서 {b} 로의 증감률은 {exact}% 입니다({expected} 로 고치세요).",
        "msg.pp_change": "'{text}': 표기 {stated}, {a} 에서 {b} 로의 차이는 {exact} 포인트입니다({expected} 로 고치세요).",
        "msg.unit_confusion": (
            "'{text}': {stated} 은(는) 상대 증감률({expected})이 아니라 %p 차이와 같습니다. "
            "{alt} 를 뜻한 것 아닌가요?"
        ),
        "msg.unit_confusion_pp": (
            "'{text}': {stated} 은(는) %p 차이({expected})가 아니라 상대 증감률과 같습니다. "
            "{alt} 를 뜻한 것 아닌가요?"
        ),
        "msg.source": "{label} / {column}: 표기 {stated}, 원자료로 계산하면 {exact} 입니다({expected} 로 고치세요).",
        "md.summary": "확인 {checked}개: 일치 {ok}, 불일치 {mismatches}, 건너뜀 {skipped}.",
        "md.no_mismatch": "불일치 없음 ({checked}개 확인).",
        "md.no_claims": "확인할 수치 주장을 찾지 못했습니다.",
        "md.mapped": "연결: {mapped}",
        "md.head": "| 줄 | 검사 | 위치 | 표기 | 기대값 |",
        "md.skipped_title": "건너뜀(판정하지 않음):",
        "md.skipped_item": "- {line}줄: {text} ({reason})",
        "md.wrote": "{path} 에 썼습니다 (확인 {checked}개, 불일치 {mismatches}개).",
        "reason.ambiguous_number": "숫자 표기가 모호함",
        "reason.group_not_in_report": "데이터에는 있으나 표에는 없는 그룹",
        "reason.group_not_in_data": "행 이름이 데이터에 없음",
    },
}

CHECK_CODES = (
    "total_row", "total_column", "percent_sum", "share_vs_value", "mean_row",
    "growth_rate", "pp_change", "unit_confusion",
    "source_count", "source_sum", "source_mean", "source_share",
)


class UsageError(Exception):
    """Input or usage problem; carries a message key so it can be localized."""

    def __init__(self, key: str, *, hint: Optional[Tuple[str, Dict[str, Any]]] = None, **kwargs: Any) -> None:
        super().__init__(key)
        self.key = key
        self.kwargs = kwargs
        # 고치는 방법을 알려 주는 두 번째 줄(메시지 키, 인자). 첫 줄 오류 문구는 그대로 둔다.
        self.hint = hint


class AmbiguousNumber(ValueError):
    """A number whose separators cannot be read with certainty (for example 1.234,56)."""


def resolve_lang(cli_value: Optional[str], env: Dict[str, str]) -> str:
    """--lang > TALLYCHECK_LANG > LC_ALL > LC_MESSAGES > LANG; anything but ko is English."""
    for value in (cli_value, env.get("TALLYCHECK_LANG"), env.get("LC_ALL"),
                  env.get("LC_MESSAGES"), env.get("LANG")):
        if value and value.strip():
            return "ko" if value.strip().lower().startswith("ko") else "en"
    return "en"


def tr(lang: str, key: str, **kwargs: Any) -> str:
    text = MESSAGES[lang][key]
    return text if key.startswith("help.") else text.format(**kwargs)


# --------------------------------------------------------------------------
# Numbers and interval arithmetic
# --------------------------------------------------------------------------

_CURRENCY = "$₩€£¥"
_KO_UNITS = {"천": 10**3, "만": 10**4, "억": 10**8, "조": 10**12}
_EN_UNITS = {"k": 10**3, "K": 10**3, "M": 10**6, "B": 10**9}
_TOK = r"(?:\d[\d.,]*\d|\d)"
_BODY_RE = re.compile(
    rf"(?:(?P<ko>(?:{_TOK}\s*[조억만천]\s*)+)(?P<kow>원)?"
    rf"|(?P<tok>{_TOK})\s*(?P<en>[kKMB])?\s*(?P<unit>%[pP]|%|pp)?\s*(?P<won>원)?)"
)
_KO_PART_RE = re.compile(rf"({_TOK})\s*([조억만천])")
_AMBIGUOUS_RES = [
    re.compile(r"\d{1,3}(?:\.\d{3})+,\d+"),
    re.compile(r"\d+,\d{1,2}"),
    re.compile(r"\d{1,3}(?:\.\d{3}){2,}"),
    re.compile(r"\d+(?:,\d+)+(?:\.\d+)?"),
]
_AMBIG_SCAN = re.compile(r"(?<![\d.,])(?:\d{1,3}(?:\.\d{3})+,\d+|\d+,\d{1,2}(?![\d,]))(?![\d.])")


@dataclass(frozen=True)
class Num:
    """A displayed number with the interval its rounding allows."""

    value: Decimal
    lo: Decimal
    hi: Decimal
    decimals: int
    kind: str = "plain"        # plain | pct | pp
    commas: bool = False
    prefix: str = ""           # currency symbol
    suffix: str = ""           # trailing "원"
    scale_unit: str = ""       # k M B 천 만 억 조, or "multi" for 1억 2,000만
    parens: bool = False


def _decimal(tok: str) -> Optional[Tuple[Decimal, int, bool]]:
    """Read one digit token. Returns (value, decimals, has_commas), None, or raises."""
    if re.fullmatch(r"\d+(?:\.\d+)?", tok):
        frac = tok.partition(".")[2]
        return Decimal(tok), len(frac), False
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", tok):
        frac = tok.partition(".")[2]
        return Decimal(tok.replace(",", "")), len(frac), True
    for rx in _AMBIGUOUS_RES:
        if rx.fullmatch(tok):
            raise AmbiguousNumber(tok)
    return None


def _half(decimals: int, scale: int = 1) -> Decimal:
    return Decimal("0.5") * Decimal(10) ** (-decimals) * scale


def parse_number(text: str) -> Optional[Num]:
    """Parse a table cell or claim token such as 1,240 / (120) / 41.3% / $2.5M / 1억 2,000만.

    Returns None when the text is not a number and raises AmbiguousNumber for
    separators that cannot be read with certainty (for example 1.234,56).
    """
    t = text.strip()
    if not t:
        return None
    parens = t.startswith("(") and t.endswith(")")
    if parens:
        t = t[1:-1].strip()
    negative = parens
    prefix = ""
    while t and t[0] in "-−+ " + _CURRENCY:
        if t[0] in "-−":
            negative = True
        elif t[0] in _CURRENCY:
            prefix = t[0]
        t = t[1:]
    m = _BODY_RE.fullmatch(t)
    if not m:
        return None
    sign = Decimal(-1) if negative else Decimal(1)
    if m.group("ko"):
        parts = _KO_PART_RE.findall(m.group("ko"))
        total = Decimal(0)
        half: Optional[Decimal] = None
        last_dec = 0
        commas = False
        for tok, unit in parts:
            got = _decimal(tok)
            if got is None:
                return None
            d, dec, com = got
            mult = _KO_UNITS[unit]
            total += d * mult
            h = Decimal(0) if dec == 0 else _half(dec, mult)
            half = h if half is None else min(half, h)
            last_dec, commas = dec, commas or com
        value = sign * total
        single = len(parts) == 1
        return Num(value, value - (half or 0), value + (half or 0), last_dec if single else 0,
                   "plain", commas, prefix, " 원" if m.group("kow") else "",
                   parts[0][1] if single else "multi", parens)
    got = _decimal(m.group("tok"))
    if got is None:
        return None
    d, dec, commas = got
    scale = _EN_UNITS.get(m.group("en") or "", 1)
    unit = m.group("unit") or ""
    kind = "pp" if unit.lower() in ("%p", "pp") else "pct" if unit == "%" else "plain"
    value = sign * d * scale
    half = _half(dec, scale)
    return Num(value, value - half, value + half, dec, kind, commas, prefix,
               "원" if m.group("won") else "", m.group("en") or "", parens)


def overlaps(a_lo: Decimal, a_hi: Decimal, b_lo: Decimal, b_hi: Decimal) -> bool:
    """Closed intervals: touching at an end counts as overlapping."""
    return a_lo <= b_hi and b_lo <= a_hi


def ratio_interval(n_lo: Decimal, n_hi: Decimal, d_lo: Decimal, d_hi: Decimal) -> Optional[Tuple[Decimal, Decimal]]:
    """Interval of n/d, or None when the denominator interval reaches zero."""
    if d_lo <= 0 <= d_hi:
        return None
    cands = [n / d for n in (n_lo, n_hi) for d in (d_lo, d_hi)]
    return min(cands), max(cands)


def fmt4(d: Decimal) -> str:
    q = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return "0.0000" if q == 0 else format(q, "f")


def render_like(value: Decimal, like: Num, unit_text: Optional[str] = None, decimals: Optional[int] = None) -> str:
    """Write value the way `like` was written: same decimals, commas, unit and symbol."""
    dec = like.decimals if decimals is None else decimals
    shown = value
    unit = ""
    if like.scale_unit in _KO_UNITS:
        shown, unit = value / _KO_UNITS[like.scale_unit], like.scale_unit
    elif like.scale_unit in _EN_UNITS:
        shown, unit = value / _EN_UNITS[like.scale_unit], like.scale_unit
    q = Decimal(1).scaleb(-dec)
    rounded = shown.quantize(q, rounding=ROUND_HALF_UP)
    body = format(abs(rounded), ",f" if like.commas or like.scale_unit == "multi" else "f")
    negative = rounded < 0
    kind_suffix = unit_text if unit_text is not None else {"pct": "%", "pp": "%p"}.get(like.kind, "")
    text = like.prefix + body + unit + kind_suffix + like.suffix
    if negative:
        text = f"({text})" if like.parens else f"-{text}"
    return text


# --------------------------------------------------------------------------
# Result collection
# --------------------------------------------------------------------------


class Ctx:
    """Collects findings for one run and formats messages in the chosen language."""

    def __init__(self, lang: str, source: Optional["Source"] = None) -> None:
        self.lang = lang
        self.source = source
        self.file = ""
        self.findings: List[Dict[str, Any]] = []
        self.skipped: List[Dict[str, Any]] = []
        self.mapped: List[str] = []

    def t(self, key: str, **kwargs: Any) -> str:
        return tr(self.lang, key, **kwargs)

    def add(self, *, line: int, check: str, ok: bool, stated: str, expected: str,
            exact: Decimal, interval: Tuple[Decimal, Decimal], table: Optional[int] = None,
            row: Optional[str] = None, column: Optional[str] = None, **fmt: Any) -> None:
        if ok:
            message = self.t("msg.ok", exact=fmt4(exact), stated=stated)
        else:
            key = fmt.pop("message_key", "msg." + check)
            if check.startswith("source_"):
                key = "msg.source"
            message = self.t(key, stated=stated, expected=expected, exact=fmt4(exact),
                             label=row or "", column=column or "", **fmt)
        self.findings.append({
            "file": self.file, "line": line, "check": check,
            "status": "ok" if ok else "mismatch",
            "table": table, "row": row, "column": column,
            "stated": stated, "expected": expected, "exact": fmt4(exact),
            "interval": [fmt4(interval[0]), fmt4(interval[1])],
            "message": message,
        })

    def skip(self, line: int, text: str, reason: str) -> None:
        entry = {"file": self.file, "line": line, "text": text, "reason": reason}
        if entry not in self.skipped:
            self.skipped.append(entry)


# --------------------------------------------------------------------------
# Markdown tables
# --------------------------------------------------------------------------

_TOTAL_LABELS = {"total", "sum", "grand total", "총계", "합계", "계", "총합", "총합계"}
_SUBTOTAL_LABELS = {"subtotal", "sub-total", "소계"}
_MEAN_LABELS = {"average", "mean", "avg", "평균"}
_SHARE_RE = re.compile(r"share|mix|proportion|composition|portion|distribution|% of|pct of|percent of|"
                       r"비중|구성비|비율|점유|구성", re.I)
_GROWTH_RE = re.compile(r"growth|change|chg|yoy|mom|qoq|delta|diff|증감|성장|변화|증가|감소|전년|전월", re.I)
_NONADD_RE = re.compile(r"avg|average|mean|rate|ratio|\bper\b|/|price|index|score|rank|"
                        r"평균|단가|율|지수|점수|순위", re.I)
_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")
_IGNORE_RE = re.compile(r"^\s*<\!--\s*tallycheck:ignore\s*--\>\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


@dataclass
class Row:
    line: int
    label: str
    cells: List[str]
    kind: str  # detail | total | subtotal | mean


@dataclass
class Table:
    index: int
    line: int
    header: List[str]
    rows: List[Row]
    ignored: bool = False


def _clean_cell(cell: str) -> str:
    c = cell.strip().replace("\\|", "|")
    c = re.sub(r"^(?:\*\*|__|\*|_)+|(?:\*\*|__|\*|_)+$", "", c).strip()
    return c


def _split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [_clean_cell(c) for c in re.split(r"(?<!\\)\|", s)]


def _row_kind(label: str) -> str:
    norm = re.sub(r"\s+", " ", label.lower().strip(" :*_"))
    if norm in _TOTAL_LABELS:
        return "total"
    if norm in _SUBTOTAL_LABELS:
        return "subtotal"
    if norm in _MEAN_LABELS:
        return "mean"
    return "detail"


def _is_table_start(lines: Sequence[str], i: int) -> bool:
    return ("|" in lines[i] and i + 1 < len(lines) and "|" in lines[i + 1]
            and bool(_SEP_RE.match(lines[i + 1])))


def parse_markdown(lines: Sequence[str]) -> Tuple[List[Table], List[Tuple[int, str]]]:
    """Split a document into tables and prose lines (code fences and ignored parts removed)."""
    tables: List[Table] = []
    prose: List[Tuple[int, str]] = []
    i, fence, ignore_next = 0, False, False
    while i < len(lines):
        line = lines[i]
        if _FENCE_RE.match(line):
            fence = not fence
            i += 1
            continue
        if fence:
            i += 1
            continue
        if _IGNORE_RE.match(line):
            ignore_next = True
            i += 1
            continue
        if not line.strip():
            i += 1
            continue
        if _is_table_start(lines, i):
            header = _split_row(line)
            start = i
            i += 2
            rows: List[Row] = []
            while i < len(lines) and "|" in lines[i] and lines[i].strip():
                cells = _split_row(lines[i])
                cells = (cells + [""] * len(header))[:max(len(header), len(cells))]
                rows.append(Row(i + 1, cells[0], cells, _row_kind(cells[0])))
                i += 1
            tables.append(Table(len(tables) + 1, start + 1, header, rows, ignore_next))
        else:
            if not ignore_next:
                prose.append((i + 1, line))
            i += 1
        ignore_next = False
    return tables, prose


@dataclass
class Col:
    idx: int
    header: str
    nums: List[Optional[Num]]
    usable: bool
    kind: str
    percentish: bool
    is_share: bool
    additive: bool
    is_total_col: bool


def _analyze_column(ctx: Ctx, tbl: Table, j: int) -> Col:
    header = tbl.header[j] if j < len(tbl.header) else ""
    nums: List[Optional[Num]] = []
    for r in tbl.rows:
        cell = r.cells[j] if j < len(r.cells) else ""
        try:
            nums.append(parse_number(cell))
        except AmbiguousNumber:
            ctx.skip(r.line, cell, "ambiguous_number")
            nums.append(None)
    details = [n for r, n in zip(tbl.rows, nums) if r.kind == "detail"]
    kinds = {n.kind for n in details if n is not None}
    usable = bool(details) and all(n is not None for n in details) and len(kinds) == 1 \
        and kinds <= {"plain", "pct"}
    kind = next(iter(kinds)) if usable else ""
    percentish = usable and (kind == "pct" or "%" in header)
    has_100 = any(n is not None and r.kind == "total" and n.lo <= 100 <= n.hi
                  for r, n in zip(tbl.rows, nums))
    is_share = bool(percentish and not _GROWTH_RE.search(header)
                    and (_SHARE_RE.search(header) or has_100))
    additive = bool(usable and (is_share or (not percentish and not _NONADD_RE.search(header))))
    is_total_col = re.sub(r"\s+", " ", header.lower().strip()) in _TOTAL_LABELS
    return Col(j, header, nums, usable, kind, percentish, is_share, additive, is_total_col)


def _sum_interval(nums: Sequence[Num]) -> Tuple[Decimal, Decimal, Decimal]:
    return (sum((n.lo for n in nums), Decimal(0)), sum((n.hi for n in nums), Decimal(0)),
            sum((n.value for n in nums), Decimal(0)))


def check_table(ctx: Ctx, tbl: Table) -> None:
    ncol = len(tbl.header)
    if tbl.ignored:
        return
    cols = {j: _analyze_column(ctx, tbl, j) for j in range(1, ncol)}
    for col in cols.values():
        _check_column_totals(ctx, tbl, col)
        if col.is_share:
            _check_percent_sum(ctx, tbl, col)
            _check_share_vs_value(ctx, tbl, col, cols.get(col.idx - 1))
    _check_total_columns(ctx, tbl, cols)
    if ctx.source is not None:
        _reconcile_table(ctx, tbl)


def _check_column_totals(ctx: Ctx, tbl: Table, col: Col) -> None:
    j = col.idx
    acc: List[Num] = []
    all_details: List[Num] = [n for r, n in zip(tbl.rows, col.nums) if r.kind == "detail" and n is not None]
    for r, n in zip(tbl.rows, col.nums):
        if r.kind == "detail":
            if n is not None:
                acc.append(n)
        elif r.kind in ("subtotal", "total") and n is not None and col.additive:
            group = acc if r.kind == "subtotal" else all_details
            if group:
                lo, hi, exact = _sum_interval(group)
                ok = overlaps(lo, hi, n.lo, n.hi)
                ctx.add(line=r.line, check="total_row", ok=ok, table=tbl.index, row=r.label,
                        column=col.header, stated=_cell(r, j), expected=render_like(exact, n),
                        exact=exact, interval=(lo, hi))
            if r.kind == "subtotal":
                acc = []
        elif r.kind == "mean" and n is not None and col.usable and all_details:
            count = Decimal(len(all_details))
            lo, hi, exact = _sum_interval(all_details)
            lo, hi, exact = lo / count, hi / count, exact / count
            ok = overlaps(lo, hi, n.lo, n.hi)
            ctx.add(line=r.line, check="mean_row", ok=ok, table=tbl.index, row=r.label,
                    column=col.header, stated=_cell(r, j), expected=render_like(exact, n),
                    exact=exact, interval=(lo, hi))


def _cell(row: Row, j: int) -> str:
    return row.cells[j] if j < len(row.cells) else ""


def _check_percent_sum(ctx: Ctx, tbl: Table, col: Col) -> None:
    details = [n for r, n in zip(tbl.rows, col.nums) if r.kind == "detail" and n is not None]
    if len(details) < 2:
        return
    lo, hi, exact = _sum_interval(details)
    ok = lo <= 100 <= hi
    totals = [r for r in tbl.rows if r.kind == "total"]
    line = totals[0].line if totals else tbl.line
    decimals = max(n.decimals for n in details)
    like = dataclasses.replace(details[0], decimals=decimals)
    ctx.add(line=line, check="percent_sum", ok=ok, table=tbl.index, row=totals[0].label if totals else None,
            column=col.header, stated=render_like(exact, like),
            expected=render_like(Decimal(100), like), exact=exact, interval=(lo, hi))


def _check_share_vs_value(ctx: Ctx, tbl: Table, col: Col, left: Optional[Col]) -> None:
    if left is None or not left.usable or left.kind != "plain" or left.percentish:
        return
    details = [(r, n, ln) for r, n, ln in zip(tbl.rows, col.nums, left.nums) if r.kind == "detail"]
    left_nums = [ln for _, _, ln in details if ln is not None]
    if not left_nums:
        return
    s_lo, s_hi, s_exact = _sum_interval(left_nums)
    den_lo, den_hi, den = s_lo, s_hi, s_exact
    for r, ln in zip(tbl.rows, left.nums):
        if r.kind == "total" and ln is not None:
            if overlaps(s_lo, s_hi, ln.lo, ln.hi):
                den_lo, den_hi, den = ln.lo, ln.hi, ln.value
            break
    for r, n, ln in details:
        if n is None or ln is None:
            continue
        ratio = ratio_interval(ln.lo * 100, ln.hi * 100, den_lo, den_hi)
        if ratio is None or den == 0:
            continue
        exact = ln.value / den * 100
        ok = overlaps(ratio[0], ratio[1], n.lo, n.hi)
        ctx.add(line=r.line, check="share_vs_value", ok=ok, table=tbl.index, row=r.label,
                column=col.header, stated=_cell(r, col.idx), expected=render_like(exact, n),
                exact=exact, interval=ratio)


def _check_total_columns(ctx: Ctx, tbl: Table, cols: Dict[int, Col]) -> None:
    for tc in cols.values():
        if not tc.is_total_col:
            continue
        summands = [c for c in cols.values() if c.idx != tc.idx and c.usable and c.kind == "plain"
                    and not c.percentish and c.additive and not c.is_total_col]
        if len(summands) < 2:
            continue
        for k, r in enumerate(tbl.rows):
            n = tc.nums[k]
            parts = [c.nums[k] for c in summands]
            if n is None or any(p is None for p in parts):
                continue
            lo, hi, exact = _sum_interval([p for p in parts if p is not None])
            ok = overlaps(lo, hi, n.lo, n.hi)
            ctx.add(line=r.line, check="total_column", ok=ok, table=tbl.index, row=r.label,
                    column=tc.header, stated=_cell(r, tc.idx), expected=render_like(exact, n),
                    exact=exact, interval=(lo, hi))


# --------------------------------------------------------------------------
# Prose claims (growth rates, percentage points; English and Korean)
# --------------------------------------------------------------------------

_N = r"\d+(?:,\d+)*(?:\.\d+)?"
_KO_PART = rf"{_N}\s*[조억만천]"
_KO_AMT = rf"(?:{_KO_PART})(?:\s*{_KO_PART})*"
_AMT = rf"(?:{_KO_AMT}|[$₩€£¥]?{_N}(?:[kKMB](?![A-Za-z]))?)%?"
_PP = (r"(?:%[pP](?![A-Za-z])|%pt(?![A-Za-z])|%\s?points?(?![A-Za-z])|%포인트|pp(?![A-Za-z])|"
       r"percentage[ -]points?|percent[ -]points?|퍼센트\s?포인트|포인트)")
_CLAIM = rf"(?P<csign>[-−+])?(?P<cnum>{_N})\s*(?P<cunit>{_PP}|%|퍼센트)"
_DIR = (r"up|down|increase|decrease|rise|rose|rising|grew|growth|gain|fall|fell|drop|decline|"
        r"change|higher|lower|lost|loss")
_PERIOD = r"(?:전\s*분기|전년\s*동기|전년|전월|전주|전일|작년|전기|지난\s*(?:분기|달|해|주))"

_EN1 = re.compile(rf"{_CLAIM}(?:\s+(?:growth|increase|decrease|decline|change|rise|drop|gain|jump))?[\s(,]*(?:from)\s+(?P<a>{_AMT})\s+(?:to|→)\s+(?P<b>{_AMT})")
_EN2 = re.compile(
    rf"from\s+(?P<a>{_AMT})\s+(?:to|→)\s+(?P<b>{_AMT})"
    rf"(?:\s*[,;]?\s*(?:an?\s+|the\s+)?\b(?:{_DIR})\w*(?:\s+(?:of|by))?\s*|\s*\(\s*){_CLAIM}",
    re.I)
_KO1 = re.compile(
    rf"(?P<b>{_AMT})\s*원?[^\d\n|]{{0,10}}?{_PERIOD}\s*(?P<a>{_AMT})\s*원?\s*대비\s*(?:약\s*)?{_CLAIM}")
_KO2 = re.compile(
    rf"(?P<a>{_AMT})\s*원?에서\s*(?P<b>{_AMT})\s*원?(?:으로|로)\s*(?:약\s*)?{_CLAIM}")

_DOWN_RE = re.compile(r"\b(?:down|decreas\w*|declin\w*|drop\w*|fell|fall\w*|lower\w*|loss|lost|shr[au]nk|dip\w*)\b"
                      r"|감소|하락|줄었|줄어|떨어|내렸|내려|낮|축소|하회", re.I)
_UP_RE = re.compile(r"\b(?:up|increas\w*|ris\w*|rose|grew|grow\w*|gain\w*|higher|jump\w*|climb\w*|surg\w*|expand\w*)\b"
                    r"|증가|늘|상승|올랐|올라|오른|성장|높|확대|상회", re.I)
_APPROX_BEFORE = re.compile(r"(?:about|around|roughly|approximately|approx\.?|nearly|almost|~|≈|약|대략)\s*(?:by\s+|of\s+)?$", re.I)
_APPROX_AFTER = re.compile(r"^\s*(?:가량|정도|쯤|or so)")


def _claim_span(m: "re.Match[str]") -> Tuple[int, int]:
    start = m.start("csign") if m.group("csign") else m.start("cnum")
    return start, m.end("cunit")


def check_prose(ctx: Ctx, prose: Sequence[Tuple[int, str]]) -> None:
    for lineno, line in prose:
        if _AMBIG_SCAN.search(line):
            ctx.skip(lineno, _AMBIG_SCAN.search(line).group(0), "ambiguous_number")  # type: ignore[union-attr]
            continue
        seen = set()
        for rx in (_EN1, _EN2, _KO1, _KO2):
            for m in rx.finditer(line):
                cs, ce = _claim_span(m)
                if cs in seen:
                    continue
                seen.add(cs)
                _check_claim(ctx, lineno, line, m, cs, ce)


def _looks_like_year(n: Num) -> bool:
    return n.kind == "plain" and n.decimals == 0 and not n.commas and not n.scale_unit \
        and not n.prefix and Decimal(1900) <= n.value <= Decimal(2100)


def _check_claim(ctx: Ctx, lineno: int, line: str, m: "re.Match[str]", cs: int, ce: int) -> None:
    try:
        a, b = parse_number(m.group("a")), parse_number(m.group("b"))
        is_pp = bool(re.fullmatch(_PP, m.group("cunit")))
        claim = parse_number(m.group("cnum") + ("%p" if is_pp else "%"))
    except AmbiguousNumber:
        return
    if a is None or b is None or claim is None or a.lo <= 0:
        return
    if _looks_like_year(a) and _looks_like_year(b):
        return  # "from 2021 to 2023, growth of 5%" is a period, not two measurements
    stated = line[cs:ce].strip()
    unit_text = line[m.end("cnum"):m.end("cunit")] if is_pp else "%"
    window = line[max(0, m.start() - 25):m.end()] + line[m.end():m.end() + 12]
    negative = m.group("csign") in ("-", "−") or bool(_DOWN_RE.search(window))
    neutral = not negative and not _UP_RE.search(window)
    sign = -1 if negative else 1
    approx = bool(_APPROX_BEFORE.search(line[max(0, cs - 16):cs]) or _APPROX_AFTER.search(line[ce:ce + 12]))
    c_lo, c_hi = claim.lo, claim.hi
    if approx:
        c_lo, c_hi = c_lo * Decimal("0.95"), c_hi * Decimal("1.05")

    pct_ctx = a.kind == "pct" and b.kind == "pct"
    rel = ratio_interval(b.lo * 100, b.hi * 100, a.lo, a.hi)
    rel_exact = (b.value / a.value - 1) * 100
    if rel is not None:
        # (b/a - 1) * 100 = b*100/a - 100
        rel = (rel[0] - 100, rel[1] - 100)
    pp_iv = (b.lo - a.hi, b.hi - a.lo)
    pp_exact = b.value - a.value

    def matches(iv: Optional[Tuple[Decimal, Decimal]]) -> bool:
        if iv is None:
            return False
        lo, hi = iv
        if neutral:
            if lo <= 0 <= hi:
                lo, hi = Decimal(0), max(abs(lo), abs(hi))
            elif hi < 0:
                lo, hi = -hi, -lo
            return overlaps(lo, hi, c_lo, c_hi)
        s_lo, s_hi = (c_lo, c_hi) if sign > 0 else (-c_hi, -c_lo)
        return overlaps(lo, hi, s_lo, s_hi)

    def shown(exact: Decimal, suffix: str) -> str:
        value = abs(exact) if neutral or exact * sign >= 0 else exact
        return render_like(value, dataclasses.replace(claim, kind="plain"), unit_text=suffix)

    a_txt, b_txt = m.group("a").strip(), m.group("b").strip()
    common = dict(line=lineno, stated=stated, text=m.group(0).strip(), a=a_txt, b=b_txt)
    if is_pp:
        if matches(pp_iv):
            ctx.add(check="pp_change", ok=True, expected=shown(pp_exact, unit_text), exact=pp_exact,
                    interval=pp_iv, **common)
        elif pct_ctx and matches(rel):
            alt = shown(rel_exact, "%")
            ctx.add(check="unit_confusion", ok=False, expected=shown(pp_exact, unit_text), exact=pp_exact,
                    interval=pp_iv, message_key="msg.unit_confusion_pp", alt=alt, **common)
        else:
            ctx.add(check="pp_change", ok=False, expected=shown(pp_exact, unit_text), exact=pp_exact,
                    interval=pp_iv, **common)
        return
    if rel is None:
        return
    if matches(rel):
        ctx.add(check="growth_rate", ok=True, expected=shown(rel_exact, "%"), exact=rel_exact,
                interval=rel, **common)
    elif pct_ctx and matches(pp_iv):
        alt = shown(pp_exact, "%p")
        ctx.add(check="unit_confusion", ok=False, expected=shown(rel_exact, "%"), exact=rel_exact,
                interval=rel, alt=alt, **common)
    else:
        ctx.add(check="growth_rate", ok=False, expected=shown(rel_exact, "%"), exact=rel_exact,
                interval=rel, **common)


# --------------------------------------------------------------------------
# Source data (CSV / JSON) reconciliation
# --------------------------------------------------------------------------

_COUNT_WORDS = {"count", "orders", "n", "rows", "records", "건수", "개수"}
_COL_SPEC_RE = re.compile(r"^(?P<header>.+?)=(?P<spec>count|(?:sum|mean|share):[^=]+)$")


def parse_col_spec(text: str) -> Tuple[str, str, Optional[str]]:
    m = _COL_SPEC_RE.match(text.strip())
    if not m:
        # "Amount=revenue" 처럼 집계 종류만 빠진 경우엔 고친 형태를 그대로 보여 준다
        header, eq, rhs = text.strip().partition("=")
        header, rhs = header.strip(), rhs.strip()
        if eq and header and rhs and ":" not in rhs and rhs.lower() not in ("count", "sum", "mean", "share"):
            hint = ("hint.col_field", {"header": header, "field": rhs})
        else:
            hint = ("hint.col_examples", {})
        raise UsageError("bad_col_spec", spec=text, hint=hint)
    spec = m.group("spec")
    if spec == "count":
        return m.group("header").strip(), "count", None
    kind, _, field = spec.partition(":")
    return m.group("header").strip(), kind, field.strip()


class Source:
    """Rows of a CSV/JSON file grouped by one column, with count/sum/mean/share aggregates."""

    def __init__(self, path: str, group: str, col_specs: Sequence[str]) -> None:
        self.path = path
        self.columns, self.rows = self._load(path)
        self.group_field = self.resolve(group, role="group")
        self.groups: Dict[str, List[Dict[str, Any]]] = {}
        self.display: Dict[str, str] = {}
        for row in self.rows:
            label = str(row.get(self.group_field, "")).strip()
            key = label.casefold()
            self.groups.setdefault(key, []).append(row)
            self.display.setdefault(key, label)
        self.specs: Dict[str, Tuple[str, Optional[str]]] = {}
        for text in col_specs:
            header, kind, field = parse_col_spec(text)
            if field is not None:
                field = self.resolve(field, role="col", header=header, kind=kind)
                self.numbers(self.rows, field)  # fail early on non-numeric data
            self.specs[header.casefold()] = (kind, field)
        self._auto_bad: set = set()

    @staticmethod
    def _load(path: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        def bad(reason_key: str, **kw: Any) -> UsageError:
            return UsageError("data_parse_error", path=path, reason_key=reason_key, reason_kw=kw)

        try:
            with open(path, encoding="utf-8-sig", newline="") as fh:
                if path.lower().endswith(".json"):
                    data = json.load(fh)
                    if isinstance(data, dict) and isinstance(data.get("records"), list):
                        data = data["records"]
                    if not isinstance(data, list) or not all(isinstance(r, dict) for r in data):
                        raise bad("err.bad_data_reason_json")
                    columns: List[str] = []
                    for r in data:
                        columns.extend(k for k in r if k not in columns)
                    return columns, data
                reader = csv.DictReader(fh)
                if not reader.fieldnames:
                    raise bad("err.bad_data_reason_header")
                return list(reader.fieldnames), list(reader)
        except FileNotFoundError:
            raise UsageError("file_not_found", path=path) from None
        except UnicodeDecodeError:
            # cp949 등으로 내보낸 파일: 날 파이썬 오류 대신 다시 저장하는 방법을 알려 준다.
            raise UsageError("not_utf8", path=path, hint=("hint.resave_utf8", {})) from None
        except (OSError, ValueError, csv.Error) as exc:  # includes JSONDecodeError
            if isinstance(exc, UsageError):
                raise
            raise UsageError("data_parse_error", path=path, reason_text=str(exc)) from None

    def resolve(self, name: str, role: str = "col", header: str = "", kind: str = "sum") -> str:
        if name in self.columns:
            return name
        for c in self.columns:
            if c.casefold() == name.casefold():
                return c
        available = ", ".join(self.columns)
        # 철자가 거의 같은 열(오타)만 제안하고, 뜻이 비슷한 다른 열(revenue -> amount)은 짐작하지 않는다
        close = difflib.get_close_matches(name.casefold(), [c.casefold() for c in self.columns], n=1, cutoff=0.8)
        match = next((c for c in self.columns if close and c.casefold() == close[0]), None)
        if role == "group":
            hint = ("hint.group_close", {"match": match}) if match else \
                ("hint.group_choose", {"available": available})
        else:
            kw = {"header": header, "kind": kind, "match": match, "available": available}
            hint = ("hint.col_close" if match else "hint.col_choose", kw)
        raise UsageError("column_not_found", name=name, available=available, hint=hint)

    def numbers(self, rows: Sequence[Dict[str, Any]], field: str) -> List[Decimal]:
        out: List[Decimal] = []
        for r in rows:
            v = r.get(field)
            if v is None or (isinstance(v, str) and not v.strip()):
                continue
            try:
                if isinstance(v, bool):
                    raise ValueError
                out.append(Decimal(str(v).strip()))
            except Exception:
                raise UsageError("data_parse_error", path=self.path, reason_key="err.bad_data_reason_number",
                                 reason_kw={"value": str(v), "field": field}) from None
        return out

    def spec_for(self, header: str) -> Optional[Tuple[str, Optional[str]]]:
        key = header.casefold()
        if key in self.specs:
            return self.specs[key]
        if key in _COUNT_WORDS:
            return "count", None
        for c in self.columns:
            if c.casefold() == key and c != self.group_field and c not in self._auto_bad:
                try:
                    self.numbers(self.rows, c)
                except UsageError:
                    self._auto_bad.add(c)
                    return None
                return "sum", c
        return None

    def aggregate(self, spec: Tuple[str, Optional[str]], group: Optional[str]) -> Optional[Decimal]:
        """Aggregate for one group (case-insensitive key) or for all rows when group is None."""
        kind, field = spec
        rows = self.rows if group is None else self.groups[group]
        if kind == "count":
            return Decimal(len(rows))
        assert field is not None
        vals = self.numbers(rows, field)
        if kind == "sum":
            return sum(vals, Decimal(0))
        if kind == "mean":
            return sum(vals, Decimal(0)) / len(vals) if vals else None
        total = sum(self.numbers(self.rows, field), Decimal(0))
        if total == 0:
            return None
        return Decimal(100) if group is None else sum(vals, Decimal(0)) / total * 100


def _reconcile_table(ctx: Ctx, tbl: Table) -> None:
    src = ctx.source
    assert src is not None
    details = [r for r in tbl.rows if r.kind == "detail"]
    matched = [r for r in details if r.label.strip().casefold() in src.groups]
    if not matched:
        return
    for r in details:
        if r.label.strip().casefold() not in src.groups:
            ctx.skip(r.line, r.label, "group_not_in_data")
    present = {r.label.strip().casefold() for r in matched}
    for key, name in src.display.items():
        if key not in present:
            ctx.skip(tbl.line, name, "group_not_in_report")
    for j in range(1, len(tbl.header)):
        header = tbl.header[j]
        spec = src.spec_for(header)
        if spec is None:
            continue
        kind, field = spec
        text = f"{header}={kind}" + (f":{field}" if field else "")
        if text not in ctx.mapped:
            ctx.mapped.append(text)
        for r in tbl.rows:
            if r.kind == "detail" and r not in matched:
                continue
            if r.kind in ("subtotal", "mean"):
                continue
            try:
                n = parse_number(_cell(r, j))
            except AmbiguousNumber:
                continue
            if n is None or (kind != "share" and n.kind != "plain"):
                continue
            exact = src.aggregate(spec, None if r.kind == "total" else r.label.strip().casefold())
            if exact is None:
                continue
            ok = overlaps(n.lo, n.hi, exact, exact)
            ctx.add(line=r.line, check="source_" + kind, ok=ok, table=tbl.index, row=r.label,
                    column=header, stated=_cell(r, j), expected=render_like(exact, n),
                    exact=exact, interval=(exact, exact))


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def check_text(ctx: Ctx, text: str) -> None:
    """Run every check on one markdown document (ctx.file must already be set)."""
    tables, prose = parse_markdown(text.splitlines())
    for tbl in tables:
        check_table(ctx, tbl)
    check_prose(ctx, prose)
    ctx.findings.sort(key=lambda f: (f["file"], f["line"]))


def build_result(ctx: Ctx, files: Sequence[str]) -> Dict[str, Any]:
    ok = sum(1 for f in ctx.findings if f["status"] == "ok")
    bad = len(ctx.findings) - ok
    return {
        "tool": "tallycheck", "version": __version__, "files": list(files),
        "summary": {"checked": len(ctx.findings), "ok": ok, "mismatches": bad,
                    "skipped": len(ctx.skipped)},
        "findings": ctx.findings, "skipped": ctx.skipped, "mapped": ctx.mapped,
    }


def _md_cell(text: Any) -> str:
    return str(text).replace("|", "\\|")


def render_md(result: Dict[str, Any], lang: str) -> str:
    s = result["summary"]
    lines: List[str] = []
    if s["checked"] == 0:
        lines.append(tr(lang, "md.no_claims"))
    elif s["mismatches"] == 0:
        lines.append(tr(lang, "md.no_mismatch", checked=s["checked"]))
    else:
        lines.append(tr(lang, "md.summary", checked=s["checked"], ok=s["ok"],
                        mismatches=s["mismatches"], skipped=s["skipped"]))
    if result["mapped"]:
        lines += ["", tr(lang, "md.mapped", mapped=", ".join(result["mapped"]))]
    bad = [f for f in result["findings"] if f["status"] == "mismatch"]
    if bad:
        many = len(result["files"]) > 1
        lines += ["", tr(lang, "md.head"), "|---:|---|---|---|---|"]
        for f in bad:
            where = " / ".join(x for x in (f["row"], f["column"]) if x) or _prose_where(f)
            line = f"{f['file']}:{f['line']}" if many else str(f["line"])
            lines.append(f"| {line} | {f['check']} | {_md_cell(where)} | {_md_cell(f['stated'])} | "
                         f"{_md_cell(f['expected'])} |")
    if result["skipped"]:
        lines += ["", tr(lang, "md.skipped_title")]
        for sk in result["skipped"]:
            lines.append(tr(lang, "md.skipped_item", line=sk["line"], text=sk["text"],
                            reason=tr(lang, "reason." + sk["reason"])))
    return "\n".join(lines) + "\n"


def _prose_where(f: Dict[str, Any]) -> str:
    m = re.search(r"'(.*?)'", f["message"])
    return m.group(1) if m else ""


class _Parser(argparse.ArgumentParser):
    def __init__(self, lang: str, **kwargs: Any) -> None:
        self.lang = lang
        super().__init__(**kwargs)

    def error(self, message: str) -> Any:
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {tr(self.lang, 'err.prefix')}: {message}\n")


def build_parser(lang: str) -> argparse.ArgumentParser:
    p = _Parser(lang, prog="tallycheck", add_help=False,
                description=tr(lang, "help.description"), epilog=tr(lang, "help.epilog"),
                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-h", "--help", action="help", help=tr(lang, "help.help"))
    p.add_argument("--version", action="version", version=f"tallycheck {__version__}",
                   help=tr(lang, "help.version"))
    p.add_argument("reports", nargs="+", metavar="REPORT.md", help=tr(lang, "help.report"))
    p.add_argument("--data", metavar="FILE", help=tr(lang, "help.data"))
    p.add_argument("--group", metavar="COLUMN", help=tr(lang, "help.group"))
    p.add_argument("--col", action="append", default=[], metavar="HEADER=SPEC", help=tr(lang, "help.col"))
    p.add_argument("--format", choices=("md", "json"), default="md", help=tr(lang, "help.format"))
    p.add_argument("--out", metavar="PATH", help=tr(lang, "help.out"))
    p.add_argument("--lang", choices=("en", "ko"), help=tr(lang, "help.lang"))
    p.add_argument("--exit-zero", action="store_true", help=tr(lang, "help.exit_zero"))
    return p


def _scan_lang(argv: Sequence[str]) -> Optional[str]:
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            return argv[i + 1]
        if arg.startswith("--lang="):
            return arg.split("=", 1)[1]
    return None


def _format_error(lang: str, exc: UsageError) -> str:
    kw = dict(exc.kwargs)
    if exc.key == "data_parse_error":
        if "reason_key" in kw:
            kw["reason"] = tr(lang, kw.pop("reason_key"), **kw.pop("reason_kw", {}))
        else:
            kw["reason"] = kw.pop("reason_text", "")
        kw.pop("reason_key", None)
    line = f"tallycheck: {tr(lang, 'err.prefix')}: {tr(lang, 'err.' + exc.key, **kw)}"
    if exc.hint:
        hint_key, hint_kw = exc.hint
        line += f"\ntallycheck: {tr(lang, 'hint.prefix')}: {tr(lang, hint_key, **hint_kw)}"
    return line


def _same_file(a: str, b: str) -> bool:
    """True when two paths name the same file (symlinks, ./x vs x, hard links, case-insensitive disks)."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def run(args: argparse.Namespace, lang: str) -> int:
    if args.data and not args.group:
        raise UsageError("data_needs_group")
    if (args.group or args.col) and not args.data:
        raise UsageError("needs_data")
    for path in args.reports:
        if not os.path.exists(path):
            raise UsageError("file_not_found", path=path)
    if args.out:
        # 보고서는 절대 고치지 않는다: --out 이 입력 파일(보고서·--data)과 같으면 쓰기 전에 거부한다.
        inputs = list(args.reports) + ([args.data] if args.data else [])
        for path in inputs:
            if os.path.exists(path) and _same_file(args.out, path):
                example = "result.json" if args.format == "json" else "result.md"
                raise UsageError("out_is_input", path=args.out, hint=("hint.out_other", {"example": example}))
    source = Source(args.data, args.group, args.col) if args.data else None
    ctx = Ctx(lang, source)
    for path in args.reports:
        try:
            # utf-8-sig: 메모장 등이 붙이는 BOM 을 떼어 첫 줄 표도 알아보게 한다.
            with open(path, encoding="utf-8-sig") as fh:
                text = fh.read()
        except UnicodeDecodeError:
            raise UsageError("not_utf8", path=path, hint=("hint.resave_utf8", {})) from None
        except OSError as exc:
            raise UsageError("file_unreadable", path=path, reason=str(exc)) from None
        ctx.file = path
        check_text(ctx, text)
    result = build_result(ctx, args.reports)
    output = (json.dumps(result, ensure_ascii=False, indent=2) + "\n") if args.format == "json" \
        else render_md(result, lang)
    s = result["summary"]
    if args.out:
        try:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(output)
        except OSError as exc:
            raise UsageError("write_failed", path=args.out, reason=str(exc)) from None
        sys.stdout.write(tr(lang, "md.wrote", path=args.out, checked=s["checked"], mismatches=s["mismatches"]) + "\n")
    else:
        sys.stdout.write(output)
    return 1 if s["mismatches"] and not args.exit_zero else 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    lang = resolve_lang(_scan_lang(argv), dict(os.environ))
    parser = build_parser(lang)
    args = parser.parse_args(argv)
    lang = resolve_lang(args.lang, dict(os.environ))
    try:
        return run(args, lang)
    except UsageError as exc:
        sys.stderr.write(_format_error(lang, exc) + "\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())
