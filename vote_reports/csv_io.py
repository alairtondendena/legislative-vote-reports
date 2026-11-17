"""Streaming CSV readers (rows → records) and the report writer.

Readers are generators: a file is read one row at a time, as the caller iterates,
so memory use does not grow with file size unless the caller keeps the records.
"""

import csv
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import TypeVar

from vote_reports.models import Bill, Legislator, Vote, VoteResult

T = TypeVar("T")
Row = dict[str, str]


def _read(path: Path, parse: Callable[[Row], T]) -> Iterator[T]:
    # newline="" lets the csv module handle line endings itself: the sample
    # files mix CRLF (bills, votes) and LF (legislators, vote_results).
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            try:
                record = parse(row)
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(
                    f"{path}, line {reader.line_num}: invalid row {row} ({error!r})"
                ) from error
            yield record


def read_legislators(path: Path) -> Iterator[Legislator]:
    return _read(path, lambda row: Legislator(id=int(row["id"]), name=row["name"]))


def read_bills(path: Path) -> Iterator[Bill]:
    return _read(
        path,
        lambda row: Bill(id=int(row["id"]), title=row["title"], sponsor_id=int(row["sponsor_id"])),
    )


def read_votes(path: Path) -> Iterator[Vote]:
    return _read(path, lambda row: Vote(id=int(row["id"]), bill_id=int(row["bill_id"])))


def read_vote_results(path: Path) -> Iterator[VoteResult]:
    return _read(
        path,
        lambda row: VoteResult(
            id=int(row["id"]),
            legislator_id=int(row["legislator_id"]),
            vote_id=int(row["vote_id"]),
            vote_type=int(row["vote_type"]),
        ),
    )


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    """Write ``rows`` under ``header``, consuming ``rows`` lazily (one row in memory at a time)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
