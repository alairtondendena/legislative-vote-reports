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
uv run mypy                               # strict; covers vote_reports/ and tests/
```

## Decisions already made (see `docs/PLAN.md` for the reasoning)

- Runtime uses the **standard library only** and must work on Python ≥ 3.10. No pandas.
- Package layout is **flat** (`vote_reports/` at the repo root), so `python3 -m vote_reports` works without installing anything. Docker Compose (`reports` and `tests` services) is the alternative way to run it.
- **Streaming is required.** Never load `vote_results.csv` or `bills.csv` fully into memory (no `list(...)`). The target is O(L+B+V+R) time and O(L+V) memory. Readers and report builders are generators; report logic stays free of I/O.
- Inputs live in `data/` (the original sample files, unchanged) and outputs in `output/`.
- After each significant AI-assisted session, add a row to `docs/AI_USAGE.md`. Add time spent to the time log in `docs/PLAN.md` §9.

## Data model (input CSVs in `data/`)

- `legislators.csv`: `id,name`
- `bills.csv`: `id,title,sponsor_id`. The column holds the primary sponsor's legislator id.
- `votes.csv`: `id,bill_id`. There is at most one Vote per Bill in this dataset.
- `vote_results.csv`: `id,legislator_id,vote_id,vote_type`, where `vote_type` is `1` = yea/support and `2` = nay/oppose.

Join path: `vote_results.vote_id → votes.id → votes.bill_id → bills.id`, and `vote_results.legislator_id → legislators.id`.

## Required outputs

1. **Per legislator** (e.g. `legislators-support-oppose-count.csv`): `id,name,num_supported_bills,num_opposed_bills`
2. **Per bill** (`bills.csv`): `id,title,supporter_count,opposer_count,primary_sponsor`. `primary_sponsor` is the sponsor's name, or `Unknown` if the sponsor isn't in `legislators.csv`.

The write-up (`docs/WRITEUP.md`) covers: time complexity and tradeoffs; extending to new columns like "Bill Voted On Date" or "Co-Sponsors"; handling a given list of legislators/bills instead of CSVs; and time spent.

## Data gotchas (verify the outputs against these)

- **Output name collision**: the suggested output name `bills.csv` is the same as an input file. Write outputs to a separate directory (e.g. `output/`) so the input is never overwritten.
- **Sponsor not in dataset**: bill `2900994` (H.R. 3684) has `sponsor_id` `400100`, which is absent from `legislators.csv`, so its sponsor must be `Unknown`. Bill `2952375` (H.R. 5376) is sponsored by `412211` (Rep. John Yarmuth).
- **Legislator with no votes**: `412211` (Yarmuth) appears in `legislators.csv` but casts no votes. They must still be included with `0,0`. Every legislator and every bill should appear in the output, even with zero counts.
- Some input files have no trailing newline.

Expected results from the sample data:
- H.R. 3684 (vote `3314452`): 13 supporters, 6 opposers, sponsor `Unknown`.
- H.R. 5376 (vote `3321166`): 6 supporters, 13 opposers, sponsor `Rep. John Yarmuth (D-KY-3)`.
- The 13 Republicans each have 1 supported and 1 opposed bill. The 6 Democrats who voted (Bowman, Bush, Ocasio-Cortez, Omar, Pressley, Tlaib) also have 1 and 1. Yarmuth has 0 and 0.
