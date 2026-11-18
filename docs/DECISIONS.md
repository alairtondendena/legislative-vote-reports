# Design decisions

Each decision below gives its reason and the alternative that was rejected. The algorithm, the complexity analysis and the measurements are in [WRITEUP.md](../WRITEUP.md).

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
| D3 | **Streaming pipeline**: time O(L+B+V+R), memory O(L+B+V) | Only ids and counts are kept; vote results and bill titles are streamed. The O(B) term is the set of bill ids that lets repeated bills be rejected (D12). See [WRITEUP.md §1](../WRITEUP.md#1-what-is-the-time-complexity-and-which-trade-offs-did-i-make) | Load everything into lists/DataFrames: O(R) memory |
| D4 | Flat package layout (`vote_reports/` at repo root) | `python3 -m vote_reports` works from a fresh clone with no install step | `src/` layout: the packaging best practice, but it needs `pip install -e .` before running |
| D5 | Two ways to run: plain Python (primary) and **Docker Compose** (fallback) | Plain Python needs nothing installed. Compose removes Python-version risk and gives one-command `reports` and `check` services (`check` runs ruff, mypy and pytest) | Docker only: forces a Docker dependency on users who already have Python |
| D6 | Dev tooling: `uv`, `pytest`, `ruff`, `mypy --strict` | Standard, fast, catches mistakes early, and only needed for development | Plain `unittest`: zero dependencies, but more verbose and less idiomatic today |
| D7 | Input CSVs live in `data/`, reports go to `output/` | The report name `bills.csv` is also an input file name, so separate folders prevent overwriting the input | Writing outputs to the repo root |
| D8 | Generated reports are committed in `output/` | Readers can check the results without running anything | — |
| D9 | A broken file stops the run; a broken reference only warns | If a file contradicts itself (no header, a missing column, the wrong number of fields, a value that isn't an integer, a repeated id), the run stops with the file and line, because no reading of the data can be trusted. If a file refers to something another file lacks (an unknown legislator, vote or bill), the run warns and continues, because the rest of the report is still right. | Failing on everything: the sample data itself has a sponsor missing from `legislators.csv`. Warning on everything: a file that contradicts itself silently produces wrong counts |
| D10 | Reports use LF line endings and UTF-8 | Clean `git diff`s and Unix tools work without `\r` noise. The inputs mix CRLF and LF, so either choice is defensible; both are valid CSV | CRLF (RFC 4180's recommendation): shows as `^M` in diffs |
| D11 | Development runs on Python 3.10; the Docker image uses 3.14 | 3.10 is the oldest supported version, so newer-only syntax fails locally first. It reached end of life in October 2026, so the image uses a currently supported version. The test suite runs on both | One version everywhere: either misses the minimum-version check or ships an end-of-life runtime |
| D12 | Repeated ids are rejected in `legislators.csv`, `bills.csv` and `votes.csv`, not in `vote_results.csv` | A repeated id makes the counts silently wrong: a repeated vote id moved one bill's votes to another; a repeated bill appeared twice in the report. Legislators and votes are in memory already; bills need a set of ids, O(B) | Checking vote results too: O(R) memory, which the streaming design exists to avoid (same reason as E7) |
| D13 | Reports are written to a temporary directory and moved into place after both are complete | A failed run never leaves a half-written or mismatched pair of reports, so committed reports can't be damaged by a bad input | Writing in place: a run that fails on the last bills row had already replaced the earlier reports |
| D14 | CI on GitHub Actions runs lint, `mypy --strict` and the tests on Python 3.10 and 3.14, and runs both Docker Compose services | Every push proves the code works on the oldest supported Python and on the one in the image, and that both documented ways to run it still work. The Docker job also checks that the committed reports are up to date and are not left owned by root. Preparing it showed the `reports` service failed for host users whose uid isn't 1000 (a runner's is 1001); the service now runs as root and hands the reports to the owner of `./output` | Running only the tests: the Docker path is how many people will try the project first |

## 3. Data assumptions and edge cases

| # | Case | Handling | In sample data? |
|---|---|---|---|
| E1 | Sponsor not in `legislators.csv` | `primary_sponsor = "Unknown"` (required by the report definition) | Yes: bill `2900994`, sponsor `400100` |
| E2 | Legislator with no vote results | Row with `0,0` | Yes: `412211` (Yarmuth) |
| E3 | Bill with no vote | Row with `0,0` | No |
| E4 | Vote result from a legislator not in `legislators.csv` | Counted in the bill totals (a legislator did vote); no legislator row; warning | No |
| E5 | Vote result with an unknown `vote_id` | Skipped (no bill to link it to); warning | No |
| E6 | `vote_type` other than 1 or 2 (e.g. Present, Not Voting) | Parsed with a `VoteType` enum; skipped; warning | No |
| E7 | Duplicate `(legislator_id, vote_id)` | Assumed not to happen: checking would need O(R) memory (see [WRITEUP.md §1](../WRITEUP.md#trade-offs)) | No |
| E8 | More than one vote for the same bill | The input format rules it out; checked while indexing votes, with a warning | No |
| E9 | Output order | Same order as the input files, so output is deterministic and easy to diff | — |
| E10 | Commas, quotes or non-ASCII characters in titles and names | Handled by the `csv` module; UTF-8 for both reading and writing; a leading byte order mark (common in spreadsheet exports) is accepted and dropped | No |
| E11 | Value that isn't an integer where an id or vote type is expected | Stop with exit code 1 and an error naming the file and line (D9) | No |
| E12 | CRLF and LF line endings | Both accepted (`newline=""` + `csv` module) | Yes: `bills.csv` and `votes.csv` use CRLF |
| E13 | Empty file, or a header missing a required column | Stop when the file is opened, naming the file and the missing columns. Before, a file with no data rows was never checked and every count came out 0 | No |
| E14 | Row with more or fewer fields than the header (e.g. an unquoted comma in a title) | Stop, naming the file and line. Before, a title like `Act to Fund Roads, 2021` was cut short and `2021` was read as the sponsor id | No |
| E15 | Repeated id in `legislators.csv`, `bills.csv` or `votes.csv` | Stop, naming the file, line and id (D12) | No |
| E16 | Repeated id in `vote_results.csv` | Not checked (D12) | No |
| E17 | Extra columns in a file | Ignored, so the input can gain columns (e.g. a vote date) before the program uses them | No |
| E18 | A run that fails partway | Earlier reports are left untouched; no temporary files remain (D13) | — |
| E19 | Blank `sponsor_id` | `primary_sponsor = "Unknown"`: the sponsor's name is not available, which is the report definition's case for `Unknown`. Before, a blank sponsor stopped the whole run as a non-integer. Other ids may not be blank (E11) | No |

## 4. Verification

1. **Hand-checked expected values** from the sample data: H.R. 3684 has 13 supporters, 6 opposers and sponsor `Unknown`. H.R. 5376 has 6 supporters, 13 opposers and sponsor Rep. John Yarmuth. Every voting legislator has 1 supported and 1 opposed bill; Yarmuth has 0 and 0. These were derived from the CSVs with `awk`, without using the program, and written by hand into `tests/expected/`. The author checked them against the CSVs.
2. **Golden-file test:** the complete output CSVs are compared to committed expected files.
3. **Unit tests:** one small fixture per edge case. E13-E15 and E18 are tested end to end (`tests/test_validation.py`): each damages one file of a copy of the sample data and checks that the run stops with the right message and that earlier reports survive.
4. **Invariant tests:** total supporters across all bills equals total supported bills across all legislators, when every voter is known. The same holds for opposers, and together they equal the number of vote results. Checked on the sample data and on 3 clean synthetic datasets.
5. **Independent check:** a test loads the same CSVs into in-memory `sqlite3` and computes both reports with SQL `JOIN`s and `GROUP BY`. Two separate implementations must agree. The SQL version is also how this would look on PostgreSQL. It runs on the sample data and on 6 seeded synthetic datasets (`scripts/synthetic.py`): 3 clean and 3 "dirty" ones that contain every bad reference from §3. Synthetic files are shuffled so that file order differs from id order, which exposes ordering bugs.
5a. **Mutation checks (manual):** bugs were injected on purpose (yea/nay swapped, empty sponsor, totals keyed by vote id, "Present" counted as nay, unknown legislators dropped, rows sorted by id), and in each case the test suite failed. The cross-check alone caught every one. The same was done for the input checks: disabling any one of them (empty file, missing column, too many or too few fields, repeated id, staged writing) makes at least one test fail. This shows the tests detect wrong results, not just that they pass.
6. **Static checks:** `mypy --strict` and `ruff` must pass with no errors.
7. **Clean-clone check:** before publishing, clone the repo into a fresh directory and follow the README step by step, once with Docker and once without.
