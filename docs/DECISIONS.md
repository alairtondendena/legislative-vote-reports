# Design decisions

Each decision below gives its reason and the alternative that was rejected. The algorithm, the complexity analysis and the measurements are in [DESIGN.md](DESIGN.md).

## 1. Scope

Read four CSVs (`legislators`, `bills`, `votes`, `vote_results`) and write two reports:

- `output/legislators-support-oppose-count.csv`: `id,name,num_supported_bills,num_opposed_bills`
- `output/bills.csv`: `id,title,supporter_count,opposer_count,primary_sponsor`

**Scope rule:** every file and feature must serve correctness, readability or idiomatic use of the language. Anything else is out. That rules out a database, a web framework and an API layer, which aren't needed and would make the code harder to read.

## 2. Decisions

| # | Decision | Rationale | Alternative rejected |
|---|---|---|---|
| D1 | Python, **standard library only** at runtime (`csv`, `dataclasses`, `enum`, `collections`, `argparse`) | The join and aggregation logic stays explicit and testable, with nothing to install | **pandas**: shorter, but it hides the edge-case handling, adds a heavy dependency, and loads every file fully into memory, which breaks D3 |
| D2 | `requires-python >= 3.10` | Runs on the Python most users already have | Requiring 3.12+ would add little and risk failing on users' machines |
| D3 | **Streaming pipeline**: time O(L+B+V+R), memory O(L+V) | Only ids and counts are kept; vote results and bills are streamed. See [DESIGN.md §1](DESIGN.md#1-time-complexity-and-trade-offs) | Load everything into lists/DataFrames: O(R) memory |
| D4 | Flat package layout (`vote_reports/` at repo root) | `python3 -m vote_reports` works from a fresh clone with no install step | `src/` layout: the packaging best practice, but it needs `pip install -e .` before running |
| D5 | Two ways to run: plain Python (primary) and **Docker Compose** (fallback) | Plain Python needs nothing installed. Compose removes Python-version risk and gives one-command `reports` and `check` services (`check` runs ruff, mypy and pytest) | Docker only: forces a Docker dependency on users who already have Python |
| D6 | Dev tooling: `uv`, `pytest`, `ruff`, `mypy --strict` | Standard, fast, catches mistakes early, and only needed for development | Plain `unittest`: zero dependencies, but more verbose and less idiomatic today |
| D7 | Input CSVs live in `data/`, reports go to `output/` | The report name `bills.csv` is also an input file name, so separate folders prevent overwriting the input | Writing outputs to the repo root |
| D8 | Generated reports are committed in `output/` | Readers can check the results without running anything | — |
| D9 | Bad references are skipped with a warning on stderr, not a crash | One bad row shouldn't stop the whole report, and the warnings make the issue visible | Failing hard: right for a strict pipeline, but the sample data itself includes a missing sponsor that must be handled gracefully |
| D10 | Reports use LF line endings and UTF-8 | Clean `git diff`s and Unix tools work without `\r` noise. The inputs mix CRLF and LF, so either choice is defensible; both are valid CSV | CRLF (RFC 4180's recommendation): shows as `^M` in diffs |
| D11 | Development runs on Python 3.10; the Docker image uses 3.14 | 3.10 is the oldest supported version, so newer-only syntax fails locally first. It reached end of life in October 2026, so the image uses a currently supported version. The test suite runs on both | One version everywhere: either misses the minimum-version check or ships an end-of-life runtime |

## 3. Data assumptions and edge cases

| # | Case | Handling | In sample data? |
|---|---|---|---|
| E1 | Sponsor not in `legislators.csv` | `primary_sponsor = "Unknown"` (required by the report definition) | Yes: bill `2900994`, sponsor `400100` |
| E2 | Legislator with no vote results | Row with `0,0` | Yes: `412211` (Yarmuth) |
| E3 | Bill with no vote | Row with `0,0` | No |
| E4 | Vote result from a legislator not in `legislators.csv` | Counted in the bill totals (a legislator did vote); no legislator row; warning | No |
| E5 | Vote result with an unknown `vote_id` | Skipped (no bill to link it to); warning | No |
| E6 | `vote_type` other than 1 or 2 (e.g. Present, Not Voting) | Parsed with a `VoteType` enum; skipped; warning | No |
| E7 | Duplicate `(legislator_id, vote_id)` | Assumed not to happen: checking would need O(R) memory (see [DESIGN.md §1](DESIGN.md#trade-offs)) | No |
| E8 | More than one vote for the same bill | The input format rules it out; checked while indexing votes, with a warning | No |
| E9 | Output order | Same order as the input files, so output is deterministic and easy to diff | — |
| E10 | Commas, quotes or non-ASCII characters in titles and names | Handled by the `csv` module; UTF-8 for both reading and writing; a leading byte order mark (common in spreadsheet exports) is accepted and dropped | No |
| E11 | Malformed row (non-integer id, missing column) | Stop with exit code 1 and an error naming the file and line. Unlike E4-E6, the row can't be interpreted at all, so guessing would hide a broken export | No |
| E12 | CRLF and LF line endings | Both accepted (`newline=""` + `csv` module) | Yes: `bills.csv` and `votes.csv` use CRLF |

## 4. Verification

1. **Hand-checked expected values** from the sample data: H.R. 3684 has 13 supporters, 6 opposers and sponsor `Unknown`. H.R. 5376 has 6 supporters, 13 opposers and sponsor Rep. John Yarmuth. Every voting legislator has 1 supported and 1 opposed bill; Yarmuth has 0 and 0. These were derived from the CSVs with `awk`, without using the program, and written by hand into `tests/expected/`. _(Pending: the author's own check.)_
2. **Golden-file test:** the complete output CSVs are compared to committed expected files.
3. **Unit tests:** one small fixture per edge case E1-E12.
4. **Invariant tests:** total supporters across all bills equals total supported bills across all legislators, when every voter is known. The same holds for opposers, and together they equal the number of vote results. Checked on the sample data and on 3 clean synthetic datasets.
5. **Independent check:** a test loads the same CSVs into in-memory `sqlite3` and computes both reports with SQL `JOIN`s and `GROUP BY`. Two separate implementations must agree. The SQL version is also how this would look on PostgreSQL. It runs on the sample data and on 6 seeded synthetic datasets (`scripts/synthetic.py`): 3 clean and 3 "dirty" ones that contain every bad reference from §3. Synthetic files are shuffled so that file order differs from id order, which exposes ordering bugs.
5a. **Mutation checks (manual):** bugs were injected on purpose (yea/nay swapped, empty sponsor, totals keyed by vote id, "Present" counted as nay, unknown legislators dropped, rows sorted by id), and in each case the test suite failed. The cross-check alone caught every one. This shows the tests detect wrong results, not just that they pass.
6. **Static checks:** `mypy --strict` and `ruff` must pass with no errors.
7. **Clean-clone check:** before publishing, clone the repo into a fresh directory and follow the README step by step, once with Docker and once without.
