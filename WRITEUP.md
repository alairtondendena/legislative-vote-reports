# Write-up

Answers to four questions about the design: what it costs, how it would grow, and how long it took. How to run it and how correctness is shown are in the [README](README.md). Each design decision, with the alternatives I rejected, is in [docs/DECISIONS.md](docs/DECISIONS.md).

## 1. What is the time complexity, and which trade-offs did I make?

With L legislators, B bills, V votes and R vote results:

| Step | What happens | Time | Memory kept |
|---|---|---|---|
| 1 | Read `votes.csv` into a `vote_id → bill_id` dict, rejecting repeated vote ids | O(V) | O(V) |
| 2 | Stream `vote_results.csv` once, adding to four counters (yea/nay × legislator/bill) | O(R) | O(L + V) |
| 3 | Read `legislators.csv` into an `id → legislator` dict, rejecting repeated ids; write the legislator report | O(L) | O(L) |
| 4 | Stream `bills.csv`; write each bill's report row as it is read, rejecting repeated bill ids | O(B) | O(B) ids; titles O(1) |

**Total: O(L + B + V + R) time and O(L + B + V) memory.** Each row of each file is read once, and every lookup is an average O(1) dict access, so the time is the minimum possible: every input has to be read at least once. The two largest inputs, vote results and bill titles, are never held in memory. Only ids and integer counts are kept. The O(B) term is a set of bill ids, used only to reject a bill listed twice; without that check memory would be O(L + V), and I chose the check (see the trade-offs).

### Measured

[`scripts/benchmark.py`](scripts/benchmark.py) generates random datasets of growing size and runs the program on each in a separate process. It was run on an Intel Core i5-1334U with Python 3.10.

*More votes (V and R grow together; shaped like the US House: 500 legislators, 435 voting each time):*

| V | R | Input | Time | R per second | Peak memory |
|---:|---:|---:|---:|---:|---:|
| 91 | 39,585 | 0.9 MB | 0.15 s | 257,412 | 13.9 MB |
| 1,004 | 436,740 | 10.0 MB | 1.30 s | 336,446 | 14.1 MB |
| 4,969 | 2,161,515 | 49.3 MB | 6.44 s | 335,729 | 15.9 MB |
| 10,019 | 4,358,265 | 99.4 MB | 12.89 s | 338,211 | 16.8 MB |
| 20,020 | 8,708,700 | 198.6 MB | 27.33 s | 318,628 | 22.4 MB |

*More results per vote (L = 5,000 and V = 1,991 fixed, so only R grows):*

| R | Input | Time | R per second | Peak memory |
|---:|---:|---:|---:|---:|
| 497,750 | 12.0 MB | 1.62 s | 306,727 | 16.5 MB |
| 1,991,000 | 47.3 MB | 6.11 s | 326,106 | 16.6 MB |
| 3,982,000 | 94.3 MB | 11.84 s | 336,329 | 16.9 MB |
| 7,964,000 | 188.4 MB | 24.71 s | 322,338 | 16.9 MB |

Rows per second stay roughly constant across a 220× range, so time grows linearly. The second table isolates R: it grows 16× while peak memory stays flat. In the first table, memory grows with V and B, at about 450 bytes per vote, for the vote index, the per-bill counters and the set of bill ids. The interpreter alone accounts for about 14 MB. The input checks (field counts and repeated ids) cost about 10% of throughput: before them, the same runs processed about 370,000 vote results per second.

One measurement detail: my first version read peak memory with `wait4`. On Linux, a child process's peak-memory figure starts at its parent's memory size at the moment of the fork, so it included the benchmark's own memory. A 300 MB parent made an 8.7 MB child report 309 MB. The benchmark now has each child read its own peak from `/proc/self/status` instead.

### Trade-offs

- **Standard library instead of pandas.** pandas would make the core logic a few lines of `merge` and `groupby`. But it adds a heavy dependency, loads every file fully into memory, and hides the edge-case rules (unknown sponsor, skipped vote types, unmatched ids) inside join options. With plain Python those rules are explicit statements that each have a test.
- **Streaming instead of loading everything.** Memory stays flat as vote results grow, but the steps have to run in a fixed order: votes before vote results, legislators before bills. The flow is also less obvious than "load four lists, then compute". To keep it readable, readers and report builders are generators over plain records, and the counting code does no file I/O, so tests pass in lists.
- **One assumption left unchecked.** I assume each (legislator, vote) pair appears at most once. Detecting duplicates would mean remembering every pair seen, which is O(R) memory, exactly what streaming avoids. In a real system a unique constraint in the database guarantees this, which is the right place to enforce it.
- **Fail on a broken file, warn on a broken reference.** If a file contradicts itself (no header, a missing column, the wrong number of fields, a value that isn't an integer, a repeated id), the run stops with the file and line, because no reading of the data can be trusted. If a file refers to something another file lacks (an unknown legislator, vote or bill), the run warns and continues, because the rest of the report is still right. Either way nothing is written halfway: both reports are written to a temporary directory and moved into place only when both are complete, so a failed run leaves earlier reports untouched.
- **Rejecting repeated bill ids costs O(B) memory.** Bills are streamed, so spotting a bill listed twice needs a set of the ids seen. Without it, a repeated bill silently appears twice in the report. A set of integers is small (a few MB for 100,000 bills), it does not grow with R, and silent wrong output is the worse failure. Repeated legislator and vote ids are checked at no extra cost, since those files are kept in memory anyway. Vote result ids are not checked, because that set would grow with R.
- **Readability over raw speed.** Profiling a 440k-row run showed that splitting the CSV text into fields takes 0.09 s of about 1.1 s. The rest goes into the Python objects created for each row: `DictReader` dicts, dataclasses and the `VoteType` lookup. A loop over raw tuples with column indexes would be faster (`csv.reader` alone is 3.8× faster than `DictReader`), but much harder to read and change. At around 370k rows per second I kept the readable version and would only optimize after profiling a real workload.
- **Hash joins instead of a sort-merge join.** Using even less memory would need inputs sorted by key and a merge join. The files aren't sorted, and sorting them costs O(R log R) time plus temporary disk space, for a gain that only matters when the vote index itself doesn't fit in memory.

## 2. How would the solution change to support new columns, such as "Bill Voted On Date" or "Co-Sponsors"?

Adding a column touches four small places: the record in `models.py`, its parser in `csv_io.py`, the row type in `reports.py` (`BillRow` or `LegislatorRow`), and the function that builds that row. The CSV header comes from the row type's field names, so the header and the rows can't get out of sync. The golden files and the SQL cross-check then confirm the new column end to end.

**Bill Voted On Date.** The date belongs to a vote, so it would arrive as a new column in `votes.csv`. `Vote` gets a `date` field. `index_votes` also builds `voted_on_by_bill_id`, which is O(V) like the vote index it already builds. `BillRow` gets `voted_on`, empty for bills without a vote. The real question is what to show once a bill has several votes, which this dataset excludes but real bills have: the latest vote, or the final-passage vote. That is a product decision, so I would put the choice in one named function with its own tests, rather than letting it happen implicitly through whichever row the dict kept last.

**Co-Sponsors.** This is a many-to-many relationship, so it would come as a new file such as `cosponsors.csv` (`bill_id, legislator_id`). Two things need deciding:
- *Output format:* a `cosponsor_count` number, or the names joined with `"; "` in one cell. That depends on how the CSV is used; a count is easier to analyse, names are easier to read.
- *Memory:* bills are streamed, so each bill's co-sponsors must be ready when its row is written. The simple approach loads `bill_id → [legislator ids]` first, which costs O(C) memory for C co-sponsorships. That is still small: C is at most a few hundred per bill, while vote results grow with every vote. If it ever got too large, sorting both files by `bill_id` would allow a streaming merge.

A per-legislator column such as `num_cosponsored_bills` is one more counter, O(L).

**When to generalize.** With two reports and a handful of columns, explicit row types are the clearest option. If the number of columns kept growing, or users chose their own columns, I would move to a declarative list of columns (name plus a function that computes the value) and build the header and rows from it. I wouldn't add that before it is needed.

## 3. How would the solution change if, instead of CSV files, it were given a list of legislators or bills to report on?

I see two readings of this question, and the design handles both.

**A list of ids to report on (a subset).** Add `--legislator-ids` / `--bill-ids` options (or a file of ids) and filter during the existing pass:
- During the single pass over vote results, count only results whose legislator or bill is in the requested set. The counters shrink to the selected ids; the lookup tables and the repeated-id checks stay O(L + B + V).
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
- **Distinct counting:** `distinct=True` counts *bills* and *legislators* rather than vote rows. See the note below on how this differs from the command-line version.
- **Integrity:** a `UniqueConstraint` on `(legislator, vote)` turns the unchecked assumption from question 1 into a rule the database enforces.
- **Unknown sponsors:** the `Coalesce` covers a sponsor who isn't in the table. That requires the sponsor foreign key to be nullable, or created with `db_constraint=False` when it may point to people not yet loaded.
- **Delivery:** `.iterator()` streams rows from the database into the CSV writer, or into a `StreamingHttpResponse` for a download, so memory stays flat there too.

**Note: the two versions count differently, on purpose.** The command-line tool counts *vote results*: `num_supported_bills` is the number of yea votes the legislator cast, and `supporter_count` is the number of yea votes on the bill. Those equal the number of *bills* and *legislators* only under two assumptions: at most one vote per bill (checked, with a warning) and at most one result per legislator per vote (not checked, because that would cost O(R) memory; see question 1). The ORM version counts distinct bills and legislators, so it does not depend on either assumption.

- **When they agree:** whenever both assumptions hold, which includes the sample data. There the two versions give identical reports.
- **When they differ:** when a bill has several votes. A legislator who voted yea on two votes on the same bill counts 2 supported bills in the command-line tool and 1 in the ORM version. A legislator who voted yea on one vote and nay on another counts the bill as both supported and opposed in *both* versions; deciding which vote should count is the product question discussed in question 2.
- **Cost:** in the database, `COUNT(DISTINCT ...)` makes PostgreSQL sort or hash each group's values, which is slower than a plain count but needs no extra application memory. In the streaming tool, the same guarantee would need a set of every (legislator, bill) pair seen, which is O(R) memory.

## 4. How long did the work take?

All the work was done in Claude Code sessions (see [docs/AI_USAGE.md](docs/AI_USAGE.md)), so the time is measured from the session transcripts' timestamps rather than estimated:

- **Interaction time:** all time spent in the sessions, including reading Claude's work and replying, but excluding breaks of more than 20 minutes.
- **Claude working time:** from each prompt to Claude's final reply.

| Phase | Interaction time | Claude working time |
|---|---:|---:|
| Analysis and planning | 16 min | 5 min |
| Core implementation | 20 min | 8 min |
| Tests, SQL cross-check, benchmark, docs | 15 min | 15 min |
| Preparing for publication | 15 min | 15 min |
| Audit and input validation | 13 min | 7 min |
| Review and publication | 13 min | 3 min |
| **Total** | **1 h 31 min** | **52 min** |

The sessions took place on the evening of 2026-11-17 and the morning of 2026-11-18 (between 18:15 and 09:49 local time, with an overnight break that is not counted).

The core implementation took about a fifth of the interaction time. The rest went into planning, verification, input validation, benchmarking and documentation. [docs/AI_USAGE.md](docs/AI_USAGE.md) describes how AI assistance was used and how its work was checked.
