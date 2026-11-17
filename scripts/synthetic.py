"""Generate random datasets in the input format, for tests and benchmarks.

Rows are written as they are generated, so datasets much larger than memory can be made.
The same ``seed`` always produces the same files.
"""

import csv
import random
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path

TRICKY_NAMES = ['Rep. Mary O\'Brien, Jr. "Molly"', "Sen. José Núñez (D-NM)", "Rep. 李 明 (I-HI-1)"]
VOTE_ID_OFFSET = 1_000_000
RESULT_ID_OFFSET = 10_000_000


@dataclass(frozen=True)
class DatasetSpec:
    legislators: int
    bills: int
    voters_per_vote: int
    seed: int = 0
    dirty: bool = False
    """If true, add bad references: unknown legislators, votes and bills, and vote
    types other than yea/nay. Unknown sponsors and legislators or bills without votes
    are always present, since the sample data has them too."""


def write_dataset(directory: Path, spec: DatasetSpec) -> int:
    """Write the four input CSVs to ``directory``. Returns the number of vote results."""
    if not 0 < spec.voters_per_vote < spec.legislators:
        raise ValueError("voters_per_vote must be at least 1 and less than legislators")
    rng = random.Random(spec.seed)
    directory.mkdir(parents=True, exist_ok=True)
    legislator_ids = range(1, spec.legislators + 1)
    bill_ids = range(1, spec.bills + 1)
    # About one bill in five has no vote, and the last legislator never votes.
    voted_bill_ids = [bill_id for bill_id in bill_ids if rng.random() < 0.8]
    voters = legislator_ids[:-1]

    legislator_rows = [
        (i, rng.choice(TRICKY_NAMES) if i % 7 == 0 else f"Legislator {i}") for i in legislator_ids
    ]
    # Sponsor ids go a little past the last legislator, so some are unknown.
    bill_rows = [
        (i, f"Bill {i}, part {i % 3}", rng.randint(1, spec.legislators + 5)) for i in bill_ids
    ]
    # Shuffled so that file order differs from id order, as in the sample data.
    rng.shuffle(legislator_rows)
    rng.shuffle(bill_rows)
    _write(directory / "legislators.csv", ("id", "name"), legislator_rows)
    _write(directory / "bills.csv", ("id", "title", "sponsor_id"), bill_rows)
    vote_rows = [(VOTE_ID_OFFSET + bill_id, bill_id) for bill_id in voted_bill_ids]
    if spec.dirty:
        vote_rows.append((VOTE_ID_OFFSET - 1, spec.bills + 1))  # a vote on an unknown bill
    _write(directory / "votes.csv", ("id", "bill_id"), vote_rows)

    rows_per_vote = spec.voters_per_vote + (len(DIRTY_RESULTS) if spec.dirty else 0)
    _write(
        directory / "vote_results.csv",
        ("id", "legislator_id", "vote_id", "vote_type"),
        _vote_results(rng, spec, [vote_id for vote_id, _ in vote_rows], voters),
    )
    return len(vote_rows) * rows_per_vote


# The extra results added to each vote in a dirty dataset.
DIRTY_RESULTS = ("unknown legislator", "unknown vote", "neither yea nor nay")


def _vote_results(
    rng: random.Random, spec: DatasetSpec, vote_ids: Sequence[int], voters: Sequence[int]
) -> Iterator[tuple[int, int, int, int]]:
    result_ids = count(RESULT_ID_OFFSET)
    for vote_id in vote_ids:
        # sample() picks distinct voters, so each (legislator, vote) pair occurs once.
        for legislator_id in rng.sample(voters, spec.voters_per_vote):
            yield next(result_ids), legislator_id, vote_id, rng.choice((1, 2))
        if spec.dirty:  # one row per entry of DIRTY_RESULTS, in that order
            yield next(result_ids), spec.legislators + 1, vote_id, 1
            yield next(result_ids), voters[0], -vote_id, 2  # vote ids are never negative
            yield next(result_ids), voters[-1], vote_id, 3


def _write(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(rows)
