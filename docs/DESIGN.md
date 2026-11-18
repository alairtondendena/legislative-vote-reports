# Design notes

How the program works, what it costs, and how it would extend. How to run it and how correctness is shown are in the [README](../README.md). Each design decision, with the alternatives I rejected, is in [DECISIONS.md](DECISIONS.md).

## 1. Time complexity and trade-offs

With L legislators, B bills, V votes and R vote results:

| Step | What happens | Time | Memory kept |
|---|---|---|---|
| 1 | Read `votes.csv` into a `vote_id → bill_id` dict | O(V) | O(V) |
| 2 | Stream `vote_results.csv` once, adding to four counters (yea/nay × legislator/bill) | O(R) | O(L + V) |
| 3 | Read `legislators.csv` into an `id → legislator` dict; write the legislator report | O(L) | O(L) |
| 4 | Stream `bills.csv`; write each bill's report row as it is read | O(B) | O(1) per row |

**Total: O(L + B + V + R) time and O(L + V) memory.** Each row of each file is read once, and every lookup is an average O(1) dict access, so the time is the minimum possible: every input has to be read at least once. The two largest inputs, vote results and bill titles, are never held in memory. Only ids and integer counts are kept.

### Measured

[`scripts/benchmark.py`](../scripts/benchmark.py) generates random datasets of growing size and runs the program on each in a separate process. It was run on an Intel Core i5-1334U with Python 3.10.

*More votes (V and R grow together; shaped like the US House: 500 legislators, 435 voting each time):*

| V | R | Input | Time | R per second | Peak memory |
|---:|---:|---:|---:|---:|---:|
| 91 | 39,585 | 0.9 MB | 0.13 s | 295,515 | 13.7 MB |
| 1,004 | 436,740 | 10.0 MB | 1.15 s | 380,454 | 13.7 MB |
| 4,969 | 2,161,515 | 49.3 MB | 5.76 s | 375,551 | 14.8 MB |
| 10,019 | 4,358,265 | 99.4 MB | 11.86 s | 367,487 | 15.7 MB |
| 20,020 | 8,708,700 | 198.6 MB | 22.58 s | 385,721 | 19.1 MB |

*More results per vote (L = 5,000 and V = 1,991 fixed, so only R grows):*

| R | Input | Time | R per second | Peak memory |
|---:|---:|---:|---:|---:|
| 497,750 | 12.0 MB | 1.38 s | 359,913 | 15.8 MB |
| 1,991,000 | 47.3 MB | 5.25 s | 379,596 | 15.9 MB |
| 3,982,000 | 94.3 MB | 11.48 s | 346,940 | 16.2 MB |
| 7,964,000 | 188.4 MB | 25.19 s | 316,150 | 16.1 MB |

Rows per second stay roughly constant across a 220× range, so time grows linearly. The second table isolates R: it grows 16× while peak memory stays flat. In the first table, memory grows only with V, at about 280 bytes per vote for the vote index and the per-bill counters. The interpreter alone accounts for about 13 MB.

One measurement detail: my first version read peak memory with `wait4`. On Linux, a child process's peak-memory figure starts at its parent's memory size at the moment of the fork, so it included the benchmark's own memory. A 300 MB parent made an 8.7 MB child report 309 MB. The benchmark now has each child read its own peak from `/proc/self/status` instead.

### Trade-offs

- **Standard library instead of pandas.** pandas would make the core logic a few lines of `merge` and `groupby`. But it adds a heavy dependency, loads every file fully into memory, and hides the edge-case rules (unknown sponsor, skipped vote types, unmatched ids) inside join options. With plain Python those rules are explicit statements that each have a test.
- **Streaming instead of loading everything.** Memory stays flat as vote results grow, but the steps have to run in a fixed order: votes before vote results, legislators before bills. The flow is also less obvious than "load four lists, then compute". To keep it readable, readers and report builders are generators over plain records, and the counting code does no file I/O, so tests pass in lists.
- **One assumption left unchecked.** I assume each (legislator, vote) pair appears at most once. Detecting duplicates would mean remembering every pair seen, which is O(R) memory, exactly what streaming avoids. In a real system a unique constraint in the database guarantees this, which is the right place to enforce it.
- **Warn instead of fail for bad references, but fail on malformed rows.** A vote result that points to an unknown vote is skipped with a warning: the report stays useful and the problem is visible. A row that can't be parsed at all (a non-integer id, a missing column) stops the run with the file and line number, because guessing would hide a broken export.
- **Readability over raw speed.** Profiling a 440k-row run showed that splitting the CSV text into fields takes 0.09 s of about 1.1 s. The rest goes into the Python objects created for each row: `DictReader` dicts, dataclasses and the `VoteType` lookup. A loop over raw tuples with column indexes would be faster (`csv.reader` alone is 3.8× faster than `DictReader`), but much harder to read and change. At around 370k rows per second I kept the readable version and would only optimize after profiling a real workload.
- **Hash joins instead of a sort-merge join.** Using even less memory would need inputs sorted by key and a merge join. The files aren't sorted, and sorting them costs O(R log R) time plus temporary disk space, for a gain that only matters when the vote index itself doesn't fit in memory.

## 2. Adding columns such as "Bill Voted On Date" or "Co-Sponsors"

Adding a column touches four small places: the record in `models.py`, its parser in `csv_io.py`, the row type in `reports.py` (`BillRow` or `LegislatorRow`), and the function that builds that row. The CSV header comes from the row type's field names, so the header and the rows can't get out of sync. The golden files and the SQL cross-check then confirm the new column end to end.

**Bill Voted On Date.** The date belongs to a vote, so it would arrive as a new column in `votes.csv`. `Vote` gets a `date` field. `index_votes` also builds `voted_on_by_bill_id`, which is O(V) like the vote index it already builds. `BillRow` gets `voted_on`, empty for bills without a vote. The real question is what to show once a bill has several votes, which this dataset excludes but real bills have: the latest vote, or the final-passage vote. That is a product decision, so I would put the choice in one named function with its own tests, rather than letting it happen implicitly through whichever row the dict kept last.

**Co-Sponsors.** This is a many-to-many relationship, so it would come as a new file such as `cosponsors.csv` (`bill_id, legislator_id`). Two things need deciding:
- *Output format:* a `cosponsor_count` number, or the names joined with `"; "` in one cell. That depends on how the CSV is used; a count is easier to analyse, names are easier to read.
- *Memory:* bills are streamed, so each bill's co-sponsors must be ready when its row is written. The simple approach loads `bill_id → [legislator ids]` first, which costs O(C) memory for C co-sponsorships. That is still small: C is at most a few hundred per bill, while vote results grow with every vote. If it ever got too large, sorting both files by `bill_id` would allow a streaming merge.

A per-legislator column such as `num_cosponsored_bills` is one more counter, O(L).

**When to generalize.** With two reports and a handful of columns, explicit row types are the clearest option. If the number of columns kept growing, or users chose their own columns, I would move to a declarative list of columns (name plus a function that computes the value) and build the header and rows from it. I wouldn't add that before it is needed.

## 3. Generating the CSV for a given list of legislators or bills

I see two readings of this question, and the design handles both.

**A list of ids to report on (a subset).** Add `--legislator-ids` / `--bill-ids` options (or a file of ids) and filter during the existing pass:
- During the single pass over vote results, count only results whose legislator or bill is in the requested set. Memory drops to O(selected ids + V) instead of O(L + V).
- Emit rows only for the requested ids, in the order requested. Requested ids that don't exist get a warning, the same way unknown references do today.
- Time is still O(R), because vote results aren't indexed by legislator or bill, so finding the relevant rows still means scanning all of them. That limit is the argument for the next point.

**Records from another source instead of CSV files** (an API, a message queue, or a database). The counting functions in `reports.py` already take iterables of plain records and do no I/O, so only `csv_io.py` changes: a new reader that yields `Legislator`, `Bill`, `Vote` and `VoteResult` from the new source. The counting logic and its tests stay as they are.

**At production scale**, this data would already be in PostgreSQL, so the right answer is to push the aggregation into the database rather than stream rows into Python. With Django models where `VoteResult` has foreign keys to `Legislator` and `Vote`, and `Vote` has a foreign key to `Bill`:

```python
yea = Q(vote_results__vote_type=VoteType.YEA)
nay = Q(vote_results__vote_type=VoteType.NAY)
legislator_rows = (
    Legislator.objects.filter(id__in=legislator_ids)
    .annotate(
        num_supported_bills=Count("vote_results__vote__bill", filter=yea, distinct=True),
        num_opposed_bills=Count("vote_results__vote__bill", filter=nay, distinct=True),
    )
    .values_list("id", "name", "num_supported_bills", "num_opposed_bills")
)

bill_rows = (
    Bill.objects.filter(id__in=bill_ids)
    .annotate(
        supporter_count=Count(
            "votes__vote_results__legislator",
            filter=Q(votes__vote_results__vote_type=VoteType.YEA),
            distinct=True,
        ),
        opposer_count=Count(
            "votes__vote_results__legislator",
            filter=Q(votes__vote_results__vote_type=VoteType.NAY),
            distinct=True,
        ),
        primary_sponsor=Coalesce("sponsor__name", Value("Unknown")),
    )
    .values_list("id", "title", "supporter_count", "opposer_count", "primary_sponsor")
)

writer.writerows(legislator_rows.iterator(chunk_size=2000))  # streamed, like the CLI
```

- **Speed:** Django indexes foreign-key columns by default (`vote_results.legislator_id`, `vote_results.vote_id`, `votes.bill_id`), so the database reads only the rows for the requested ids. That is the time improvement the CSV version can't get.
- **Distinct counting:** `distinct=True` counts *bills* and *legislators* rather than vote rows, so the result stays correct even when a bill has several votes. In the streaming CSV version that guarantee would cost O(R) memory; in the database it is cheap.
- **Integrity:** a `UniqueConstraint` on `(legislator, vote)` turns the unchecked assumption from question 1 into a rule the database enforces.
- **Unknown sponsors:** the `Coalesce` covers a sponsor who isn't in the table. That requires the sponsor foreign key to be nullable, or created with `db_constraint=False` when it may point to people not yet loaded.
- **Delivery:** `.iterator()` streams rows from the database into the CSV writer, or into a `StreamingHttpResponse` for a download, so memory stays flat there too.

## 4. Development time

All the work was done in Claude Code sessions (see [AI_USAGE.md](AI_USAGE.md)), so the time is measured from the session transcripts' timestamps rather than estimated:

- **Interaction time:** all time spent in the sessions, including reading Claude's work and replying, but excluding breaks of more than 20 minutes.
- **Claude working time:** from each prompt to Claude's final reply.

| Phase | Interaction time | Claude working time |
|---|---:|---:|
| Analysis and planning | 16 min | 5 min |
| Core implementation | 20 min | 8 min |
| Tests, SQL cross-check, benchmark, docs | 15 min | 15 min |
| Preparing for publication | 13 min | 13 min |
| **Total** | **1 h 03 min** | **40 min** |

All sessions took place between 2026-11-17 18:15 and 2026-11-17 21:44 (local time).

The core implementation took about a third of the interaction time. The rest went into planning, verification, benchmarking and documentation. [AI_USAGE.md](AI_USAGE.md) describes how AI assistance was used and how its work was checked.
