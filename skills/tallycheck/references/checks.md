# What tallycheck checks

## Contents
- Check codes
- Row and column recognition
- Tolerance (rounding-aware intervals)
- Sentence patterns
- Source reconciliation
- Not checked

## Check codes

| Code | Meaning |
|---|---|
| `total_row` | A Total row equals the sum of the detail rows; a Subtotal row equals the detail rows since the previous subtotal. |
| `total_column` | A column headed Total / Sum / 합계 equals the other numeric columns of the same row (at least two). |
| `percent_sum` | A share column (values in %) can add up to 100. Reported on the Total row line, or the header line if there is none. |
| `share_vs_value` | Each share equals the value in the column directly to its left divided by the total (the Total row if it is consistent, otherwise the sum of the rows). |
| `mean_row` | An Average / Mean / Avg / 평균 row equals the sum of the detail rows divided by their count. |
| `growth_rate` | A sentence such as `grew 18.2% from 2,620 to 3,101`, `from A to B, up X%`, `A에서 B로 X% 증가`, `A 대비 X%`. |
| `pp_change` | The same with percentage points (`%p`, `pp`, `percentage points`, `포인트`). |
| `unit_confusion` | A `%` claim between two percentages that only matches the point difference, or a `%p` claim that only matches the relative change. |
| `source_count` `source_sum` `source_mean` `source_share` | A table cell differs from the aggregate of the source data for that row label. |

## Row and column recognition

- First-cell labels, case-insensitive, bold ignored: Total, Sum, Grand total, 합계, 계, 총계, 총합 (total); Subtotal, 소계 (subtotal); Average, Mean, Avg, 평균 (mean).
- A column is a share column when it is written in % (or its header has `%`), the header is not a growth or change column, and the header names a share (share, mix, composition, 비중, 구성비, 비율, 점유) or its Total cell says 100.
- Columns whose header looks like a rate, price, average or index are never summed.
- Columns with any non-numeric cell in the detail rows are skipped.
- An HTML comment whose text is `tallycheck:ignore` (see the README for the exact line) skips the next table, or the next line if it is not a table. Fenced code blocks are skipped.

## Tolerance (rounding-aware intervals)

Every displayed number stands for an interval: half a unit of its last shown digit in each direction (`41.3` is 41.25 to 41.35, `1,240` is 1239.5 to 1240.5). A recomputed value is an interval too, and a check passes when the two intervals overlap (touching counts).

| Written as | Interval |
|---|---|
| `1,240`, `41.3%` | plus or minus half a unit of the last digit |
| `1억`, `4,200만`, `1억 2,000만` | exact (integer with a unit word) |
| `1.2억` | plus or minus 0.05억 |
| `1.4k`, `$2.5M` | plus or minus half a unit of the mantissa, times the suffix |
| with `about`, `around`, `roughly`, `approximately`, `~`, `약`, `대략`, `가량` | the stated claim widens by 5% each side |

Small integers therefore have wide intervals (two rows of `2` may sum to anything from 3 to 5); a one-off error in a short integer column cannot be told from rounding.

Ambiguous separators (`1.234,56`, `12,5`, `1,23,456`) are never guessed: the item is listed as skipped.

## Sentence patterns

Claims are only judged when the sentence names both ends: `X% from A to B` (also `X percent from A to B`), `from A to B, up X%`, `from A to B, a X% decrease` (noun form after the figures), `from A to B (X%)`, `A에서 B로 X%`, `B ... 전 분기 A 대비 X%`. Direction words (up, fell, 증가, 감소) are compared with the real direction; without one the sizes are compared. Sentences with only a percentage are not judged.

## Source reconciliation

`--data` takes a CSV or a JSON file (array of objects or `{"records": [...]}`). `--group` names the column that holds the table's row labels (matched case-insensitively). Tables whose row labels match no group are ignored. The Total row is compared with the aggregate over all rows. Groups in the data but not in the table, and table rows missing in the data, are listed as skipped.

A `--group` or `--col` field that is not in the data stops the run with exit code 2. The error line lists the available columns, and a second `hint:` line shows the corrected option: a near-identical spelling is offered (`amont` gives `--col "Amount=sum:amount"`), but a different column with a similar meaning (`revenue` versus `amount`) is never suggested; pick it with the user. An `--col` without an aggregate (`Amount=revenue`) gets the corrected form `Amount=sum:revenue`. Messages follow `--lang`; pass it so the text is in the user's language rather than the machine's locale.

## Not checked

PDF, spreadsheets, HTML tables, numbers in images, meaning or causality, outside facts, weighted averages, compound growth rates, more than one grouping column.
