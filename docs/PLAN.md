# Plan: Legislative Vote Reports

This document records the plan, the design decisions and the reason behind each one. Decisions are final unless marked as open.

## 1. Goal and scope

Read four CSVs (`legislators`, `bills`, `votes`, `vote_results`) and write two reports:

- `output/legislators-support-oppose-count.csv`: `id,name,num_supported_bills,num_opposed_bills`
- `output/bills.csv`: `id,title,supporter_count,opposer_count,primary_sponsor`

Plus run instructions and a write-up (`docs/WRITEUP.md`) on complexity, trade-offs and extensibility.

**Scope rule:** every file and feature must serve correctness, readability or idiomatic use of the language. Anything else is out. That rules out a database, a web framework and an API layer, which aren't needed and would make the code harder to read.

## 2. Key decisions

| # | Decision | Rationale | Alternative rejected |
|---|---|---|---|
| D1 | Python, **standard library only** at runtime (`csv`, `dataclasses`, `enum`, `collections`, `argparse`) | The join and aggregation logic stays explicit and testable, with nothing to install | **pandas**: shorter, but it hides the edge-case handling, adds a heavy dependency, and loads every file fully into memory, which breaks D3 |
| D2 | `requires-python >= 3.10` | Runs on the Python most users already have | Requiring 3.12+ would add little and risk failing on users' machines |
| D3 | **Streaming pipeline**: time O(L+B+V+R), memory O(L+V) | See §3 | Load everything into lists/DataFrames: O(R) memory |
| D4 | Flat package layout (`vote_reports/` at repo root) | `python3 -m vote_reports` works from a fresh clone with no install step | `src/` layout: the packaging best practice, but it needs `pip install -e .` before running |
| D5 | Two ways to run: plain Python (primary) and **Docker Compose** (fallback) | Plain Python needs nothing installed. Compose removes Python-version risk and gives one-command `reports` and `check` services (`check` runs ruff, mypy and pytest) | Docker only: forces a Docker dependency on users who already have Python |
| D6 | Dev tooling: `uv`, `pytest`, `ruff`, `mypy --strict` | Standard, fast, catches mistakes early, and only needed for development | Plain `unittest`: zero dependencies, but more verbose and less idiomatic today |
| D7 | Input CSVs move to `data/`, reports go to `output/` | The suggested report name `bills.csv` is also an input file name, so separate folders prevent overwriting the input | Writing outputs to the repo root |
| D8 | Generated reports are committed in `output/` | Readers can check the results without running anything | — |
| D9 | Bad references are skipped with a warning on stderr, not a crash | One bad row shouldn't stop the whole report, and the warnings make the issue visible | Failing hard: right for a strict pipeline, but the sample data itself includes a missing sponsor that must be handled gracefully |
| D10 | Reports use LF line endings and UTF-8 | Clean `git diff`s and Unix tools work without `\r` noise. The inputs mix CRLF and LF, so either choice is defensible; both are valid CSV | CRLF (RFC 4180's recommendation): shows as `^M` in diffs |
| D11 | Development runs on Python 3.10; the Docker image uses 3.14 | 3.10 is the oldest supported version, so newer-only syntax fails locally first. It reached end of life in October 2026, so the image uses a currently supported version. The test suite runs on both | One version everywhere: either misses the minimum-version check or ships an end-of-life runtime |

## 3. Algorithm and complexity

The work is a two-way join (`vote_results → votes → bills`, and `vote_results → legislators`) followed by a group-by count. Steps run in an order that keeps only small lookup tables in memory:

| Step | Input | Handling | Memory kept |
|---|---|---|---|
| 1 | `votes.csv` | load `vote_id → bill_id`; check the rule of at most one vote per bill | O(V) |
| 2 | `vote_results.csv` | **streamed**: one pass, adding to four `Counter`s (support/oppose × legislator/bill) | O(L + V) counters, O(1) per row |
| 3 | `legislators.csv` | load `id → name` (needed later to look up sponsor names); write the legislator report row by row | O(L) |
| 4 | `bills.csv` | **streamed**: each bill row becomes a report row and is written immediately; titles are never held in memory | O(1) per row |

- **Time: O(L+B+V+R).** Each row of each file is read once, and every lookup is an average O(1) dict access. This is the minimum possible, since every input row has to be read.
- **Memory: O(L+V).** Only the id→name and vote→bill maps and integer counters stay in memory. The largest file (`vote_results`) and the largest strings (bill titles) are streamed. Bill counters exist only for bills that have a vote, so there are at most V of them.
- **Why not lower:** using less memory would need a merge-join over inputs sorted by key. The inputs aren't sorted, and an external sort costs O(R log R) time, disk I/O and much more code.
- **Readability is preserved:** readers and report builders are generators (`Iterable` in, `Iterator` out) and pure functions. Tests pass them lists; production passes them file streams.
- **Leftover detection at no extra cost:** as each report row is emitted, its entry is removed from the counter. Anything left at the end belongs to a legislator or bill missing from the input files, and a warning is logged.

**Trade-off:** detecting duplicate `(legislator_id, vote_id)` rows would need a set of every pair seen, which is O(R) memory and breaks D3. We **assume these pairs are unique**, as a unique constraint in the source database would guarantee, and document that assumption instead of checking it.

The complexity claims are checked with `scripts/benchmark.py`, and the results are in [WRITEUP.md](WRITEUP.md#measured). Time grows linearly. With L and V fixed, peak memory stays at about 16 MB while R grows 16×.

## 4. Data assumptions and edge cases

| # | Case | Handling | In sample data? |
|---|---|---|---|
| E1 | Sponsor not in `legislators.csv` | `primary_sponsor = "Unknown"` (required by the report definition) | Yes: bill `2900994`, sponsor `400100` |
| E2 | Legislator with no vote results | Row with `0,0` | Yes: `412211` (Yarmuth) |
| E3 | Bill with no vote | Row with `0,0` | No |
| E4 | Vote result from a legislator not in `legislators.csv` | Counted in the bill totals (a legislator did vote); no legislator row; warning | No |
| E5 | Vote result with an unknown `vote_id` | Skipped (no bill to link it to); warning | No |
| E6 | `vote_type` other than 1 or 2 (e.g. Present, Not Voting) | Parsed with a `VoteType` enum; skipped; warning | No |
| E7 | Duplicate `(legislator_id, vote_id)` | Assumed not to happen (see trade-off in §3) | No |
| E8 | More than one vote for the same bill | The input format rules it out; checked during step 1 with a warning | No |
| E9 | Output order | Same order as the input files, so output is deterministic and easy to diff | — |
| E10 | Commas, quotes or non-ASCII characters in titles and names | Handled by the `csv` module; UTF-8 for both reading and writing; a leading byte order mark (common in spreadsheet exports) is accepted and dropped | No |
| E11 | Malformed row (non-integer id, missing column) | Stop with exit code 1 and an error naming the file and line. Unlike E4-E6, the row can't be interpreted at all, so guessing would hide a broken export | No |
| E12 | CRLF and LF line endings | Both accepted (`newline=""` + `csv` module) | Yes: `bills.csv` and `votes.csv` use CRLF |

## 5. Verification strategy

1. **Hand-checked expected values** from the sample data: H.R. 3684 has 13 supporters, 6 opposers and sponsor `Unknown`. H.R. 5376 has 6 supporters, 13 opposers and sponsor Rep. John Yarmuth. Every voting legislator has 1 supported and 1 opposed bill; Yarmuth has 0 and 0. These were derived from the CSVs with `awk`, without using the program, and written by hand into `tests/expected/`. _(Pending: the author's own check.)_
2. **Golden-file test:** the complete output CSVs are compared to committed expected files.
3. **Unit tests:** one small fixture per edge case E1-E12.
4. **Invariant tests:** total supporters across all bills equals total supported bills across all legislators, when every voter is known. The same holds for opposers, and together they equal the number of vote results. Checked on the sample data and on 3 clean synthetic datasets.
5. **Independent check:** a test loads the same CSVs into in-memory `sqlite3` and computes both reports with SQL `JOIN`s and `GROUP BY`. Two separate implementations must agree. The SQL version is also how this would look on PostgreSQL. It runs on the sample data and on 6 seeded synthetic datasets (`scripts/synthetic.py`): 3 clean and 3 "dirty" ones that contain every bad reference from §4. Synthetic files are shuffled so that file order differs from id order, which exposes ordering bugs.
5a. **Mutation checks (manual):** bugs were injected on purpose (yea/nay swapped, empty sponsor, totals keyed by vote id, "Present" counted as nay, unknown legislators dropped, rows sorted by id), and in each case the test suite failed. The cross-check alone caught every one. This shows the tests detect wrong results, not just that they pass.
6. **Static checks:** `mypy --strict` and `ruff` must pass with no errors.
7. **Clean-clone check:** before publishing, clone the repo into a fresh directory and follow the README step by step, once with Docker and once without.

## 6. Planned repository layout

```
vote_reports/
  __init__.py
  __main__.py      # `python3 -m vote_reports` entry point
  cli.py           # argparse + generate_reports(): wires the pipeline together
  models.py        # frozen dataclasses + VoteType enum
  csv_io.py        # generator readers (CSV → models) and the row writer
  reports.py       # tally (one pass) + report row generators; no I/O
tests/             # unit, golden, invariant and sqlite cross-check tests
  expected/        # hand-written reference reports (never generated by the code)
scripts/           # dev tools: synthetic.py (seeded dataset generator), benchmark.py
data/              # the four sample input CSVs
output/            # generated reports (committed)
docs/              # PLAN.md, AI_USAGE.md, WRITEUP.md
Dockerfile, compose.yaml, .dockerignore, pyproject.toml, README.md, CLAUDE.md
```

Commands (to be documented in the README):

```bash
# Option A: any Python ≥ 3.10, nothing to install
python3 -m vote_reports

# Option B: Docker
docker compose run --rm reports
docker compose run --rm check     # ruff + mypy + pytest
```

## 7. Schedule

**Day 1 (2026-11-17): correct core**
1. `git init`; move CSVs to `data/`; `pyproject.toml` with ruff/mypy/pytest. → check: `uv run pytest` runs.
2. Models, readers, tally, reports, writer, CLI. → check: output matches §5.1.
3. Golden-file test. Dockerfile and `compose.yaml`. → check: both commands work.

**Day 2 (2026-11-18): rigor**
4. Edge cases E1-E10, each with a test.
5. Invariant tests and the sqlite cross-check.
6. Benchmark script; record the results in the write-up.
7. `mypy --strict` and `ruff` clean. Draft `README.md` and `docs/WRITEUP.md`.

**Day 3 (2026-11-19): review and publishing**
8. Fresh-eyes review of all code and docs.
9. Clean-clone check (§5.7).
10. Finalize the time log, the write-up and `docs/AI_USAGE.md`.
11. Push to the remote.

## 8. Time log

Kept as work happens. Used in the write-up.

| Date | Phase | Time |
|---|---|---|
| 2026-11-17 | Planning, documentation | _fill in_ |
