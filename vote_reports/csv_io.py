"""Streaming CSV readers (rows → records) and the report writer.

Readers are generators: a file is read one row at a time, as the caller iterates,
so memory use does not grow with file size unless the caller keeps the records.

Readers reject a file that contradicts itself: a missing header or column, a row whose
field count differs from the header's, a value that is not an integer, or a repeated id.
Each error names the file and, for row errors, the line. Repeated ids are checked for
legislators, bills and votes with a set of the ids seen (O(n) integers). Vote results
are not checked: that set would grow with R, the one input memory must not depend on.
"""

import csv
from collections.abc import Callable, Iterable, Iterator, Sequence
from pathlib import Path
from typing import Protocol, TypeVar

from vote_reports.models import Bill, Legislator, Vote, VoteResult


class _Record(Protocol):
    @property
    def id(self) -> int: ...


R = TypeVar("R", bound=_Record)
Row = dict[str, str]


def _read(
    path: Path, columns: Sequence[str], parse: Callable[[Row], R], *, unique_ids: bool = True
) -> Iterator[R]:
    # newline="" lets the csv module handle line endings itself: the sample
    # files mix CRLF (bills, votes) and LF (legislators, vote_results).
    # utf-8-sig reads plain UTF-8 and also drops a leading byte order mark, which
    # spreadsheet tools often add and which would otherwise corrupt the first header.
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        header = reader.fieldnames
        if header is None:
            raise ValueError(f"{path}: file is empty; expected the columns {', '.join(columns)}")
        missing = [column for column in columns if column not in header]
        if missing:
            raise ValueError(f"{path}: missing column(s) {', '.join(missing)}")
        seen_ids: set[int] = set()
        for row in reader:
            where = f"{path}, line {reader.line_num}"
            # DictReader puts surplus fields under the key None and fills absent ones with None.
            if None in row:
                raise ValueError(
                    f"{where}: more fields than the {len(header)} columns in the header "
                    "(an unquoted comma?)"
                )
            if None in row.values():
                raise ValueError(
                    f"{where}: fewer fields than the {len(header)} columns in the header"
                )
            try:
                record = parse(row)
            except ValueError as error:
                raise ValueError(f"{where}: invalid row {row} ({error})") from error
            if unique_ids:
                if record.id in seen_ids:
                    raise ValueError(f"{where}: duplicate id {record.id}")
                seen_ids.add(record.id)
            yield record


def read_legislators(path: Path) -> Iterator[Legislator]:
    return _read(path, ("id", "name"), lambda row: Legislator(id=int(row["id"]), name=row["name"]))


def read_bills(path: Path) -> Iterator[Bill]:
    return _read(
        path,
        ("id", "title", "sponsor_id"),
        lambda row: Bill(id=int(row["id"]), title=row["title"], sponsor_id=int(row["sponsor_id"])),
    )


def read_votes(path: Path) -> Iterator[Vote]:
    return _read(
        path, ("id", "bill_id"), lambda row: Vote(id=int(row["id"]), bill_id=int(row["bill_id"]))
    )


def read_vote_results(path: Path) -> Iterator[VoteResult]:
    return _read(
        path,
        ("id", "legislator_id", "vote_id", "vote_type"),
        lambda row: VoteResult(
            id=int(row["id"]),
            legislator_id=int(row["legislator_id"]),
            vote_id=int(row["vote_id"]),
            vote_type=int(row["vote_type"]),
        ),
        unique_ids=False,  # see the module docstring
    )


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[object]]) -> None:
    """Write ``rows`` under ``header``, consuming ``rows`` lazily (one row in memory at a time)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
