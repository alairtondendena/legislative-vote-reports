# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A small command-line tool that reads legislative voting data from CSV files and writes two summary reports: one row per legislator and one row per bill.

Keep the solution simple: Python, no database, no web framework.

## Commands

Development uses `uv`. `.python-version` pins 3.10, the minimum supported version, so syntax that needs a newer Python fails during development.

```bash
uv sync                                   # install dev tools (pytest, ruff, mypy)
uv run pytest                             # all tests
uv run pytest tests/test_x.py::test_name  # a single test
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict; covers vote_reports/, scripts/ and tests/
python3 -m vote_reports                   # writes output/ from data/ (no install needed)
uv run python -m scripts.benchmark --quick  # time/peak-memory scaling (Linux only)
```

`tests/test_cross_check.py` recomputes both reports in SQLite on the sample data and on seeded synthetic datasets from `scripts/synthetic.py`; any change to the counting rules must be mirrored in its SQL. `tests/expected/` holds hand-written reference reports. Never regenerate them from the code. When the output legitimately changes, update them by hand and re-run the program to refresh the committed `output/`.

## Decisions already made (see `docs/DECISIONS.md` for the reasoning)

- Runtime uses the **standard library only** and must work on Python ≥ 3.10. No pandas.
- Package layout is **flat** (`vote_reports/` at the repo root), so `python3 -m vote_reports` works without installing anything. Docker Compose is the alternative way to run it: `docker compose run --rm reports` writes `output/`, and `docker compose run --rm check` runs ruff, mypy and pytest on Python 3.14.
- **Streaming is required.** Never load `vote_results.csv` or `bills.csv` fully into memory (no `list(...)`). The target is O(L+B+V+R) time and O(L+B+V) memory (the O(B) is the set of bill ids used to reject repeats). Readers and report builders are generators; report logic stays free of I/O.
- Input validation rule: a file that contradicts itself (missing header/column, wrong field count, non-integer, repeated id) raises `ValueError` in `csv_io.py`; a reference to something missing in another file only logs a warning in `reports.py`. Reports are staged in a temp dir and moved into place only after both succeed.
- Inputs live in `data/` (the original sample files, unchanged) and outputs in `output/`.
- After each significant AI-assisted session, add a row to `docs/AI_USAGE.md`. Development time is measured from the Claude Code session timestamps and reported in `docs/AI_USAGE.md` and `docs/DESIGN.md` §4.

## Data model (input CSVs in `data/`)

- `legislators.csv`: `id,name`
- `bills.csv`: `id,title,sponsor_id`. The column holds the primary sponsor's legislator id.
- `votes.csv`: `id,bill_id`. There is at most one Vote per Bill in this dataset.
- `vote_results.csv`: `id,legislator_id,vote_id,vote_type`, where `vote_type` is `1` = yea/support and `2` = nay/oppose.

Join path: `vote_results.vote_id → votes.id → votes.bill_id → bills.id`, and `vote_results.legislator_id → legislators.id`.

## Reports

1. **Per legislator** (e.g. `legislators-support-oppose-count.csv`): `id,name,num_supported_bills,num_opposed_bills`
2. **Per bill** (`bills.csv`): `id,title,supporter_count,opposer_count,primary_sponsor`. `primary_sponsor` is the sponsor's name, or `Unknown` if the sponsor isn't in `legislators.csv`.

`docs/DESIGN.md` covers complexity and trade-offs (with benchmark results), adding columns such as "Bill Voted On Date" or "Co-Sponsors", reporting on a given list of legislators or bills, and development time. `docs/DECISIONS.md` lists the decisions (D1-D11), data edge cases (E1-E12) and verification steps.

## Data gotchas (verify the outputs against these)

- **Output name collision**: the report name `bills.csv` is the same as an input file. Write outputs to a separate directory (e.g. `output/`) so the input is never overwritten.
- **Sponsor not in dataset**: bill `2900994` (H.R. 3684) has `sponsor_id` `400100`, which is absent from `legislators.csv`, so its sponsor must be `Unknown`. Bill `2952375` (H.R. 5376) is sponsored by `412211` (Rep. John Yarmuth).
- **Legislator with no votes**: `412211` (Yarmuth) appears in `legislators.csv` but casts no votes. They must still be included with `0,0`. Every legislator and every bill should appear in the output, even with zero counts.
- **Mixed line endings**: `bills.csv` and `votes.csv` use CRLF; `legislators.csv` and `vote_results.csv` use LF. Some files have no trailing newline. Always open CSVs with `newline=""` and the `csv` module; shell tools (`awk`, `cut`) need `tr -d '\r'` first.

Expected results from the sample data:
- H.R. 3684 (vote `3314452`): 13 supporters, 6 opposers, sponsor `Unknown`.
- H.R. 5376 (vote `3321166`): 6 supporters, 13 opposers, sponsor `Rep. John Yarmuth (D-KY-3)`.
- The 13 Republicans each have 1 supported and 1 opposed bill. The 6 Democrats who voted (Bowman, Bush, Ocasio-Cortez, Omar, Pressley, Tlaib) also have 1 and 1. Yarmuth has 0 and 0.
