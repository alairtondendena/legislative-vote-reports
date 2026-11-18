"""Vote counting and report rows. Pure logic: no file I/O.

``tally_votes`` makes one pass over the vote results; the row generators stream their
input and yield one report row per record, so no stage needs a whole file in memory.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import NamedTuple

from vote_reports.models import Bill, Legislator, Vote, VoteResult, VoteType

logger = logging.getLogger(__name__)

UNKNOWN_SPONSOR = "Unknown"
# Only these vote types count as support or opposition. Any other code, including one
# added to VoteType later (e.g. "Present"), is skipped with a warning, not miscounted.
COUNTED_VOTE_TYPES = frozenset({VoteType.YEA, VoteType.NAY})


class LegislatorRow(NamedTuple):
    """A row of the legislators report; field names are the CSV header."""

    id: int
    name: str
    num_supported_bills: int
    num_opposed_bills: int


class BillRow(NamedTuple):
    """A row of the bills report; field names are the CSV header."""

    id: int
    title: str
    supporter_count: int
    opposer_count: int
    primary_sponsor: str


@dataclass
class Tally:
    """Yea and nay counts keyed by id (of a legislator or a bill). Absent ids count as 0."""

    supported: Counter[int] = field(default_factory=Counter)
    opposed: Counter[int] = field(default_factory=Counter)

    def add(self, key: int, vote_type: VoteType) -> None:
        if vote_type is VoteType.YEA:
            self.supported[key] += 1
        elif vote_type is VoteType.NAY:
            self.opposed[key] += 1
        else:
            raise ValueError(f"no counter for vote type {int(vote_type)}")

    def ids(self) -> set[int]:
        return self.supported.keys() | self.opposed.keys()


class VoteTallies(NamedTuple):
    by_legislator: Tally
    by_bill: Tally


def index_votes(votes: Iterable[Vote]) -> dict[int, int]:
    """Map each vote id to the id of the bill it was on.

    The input format allows at most one vote per bill. That guarantee is what makes a count
    of vote results equal to a count of bills, so it is checked here (O(V) memory).
    """
    bill_id_by_vote_id = {vote.id: vote.bill_id for vote in votes}
    votes_per_bill = Counter(bill_id_by_vote_id.values())
    repeated = sorted(bill_id for bill_id, count in votes_per_bill.items() if count > 1)
    if repeated:
        logger.warning(
            "Bills with more than one vote; each vote is counted, so a legislator who "
            "voted the same way twice on a bill counts it twice: %s",
            repeated,
        )
    return bill_id_by_vote_id


def tally_votes(
    results: Iterable[VoteResult], bill_id_by_vote_id: Mapping[int, int]
) -> VoteTallies:
    """Count yeas and nays per legislator and per bill in a single pass over ``results``.

    Assumes each (legislator, vote) pair occurs at most once. Checking that would need
    a set of every pair seen, i.e. O(R) memory (see docs/DESIGN.md §1).
    """
    tallies = VoteTallies(by_legislator=Tally(), by_bill=Tally())
    unknown_vote_rows = 0
    other_type_rows: Counter[int] = Counter()
    for result in results:
        bill_id = bill_id_by_vote_id.get(result.vote_id)
        if bill_id is None:
            unknown_vote_rows += 1
            continue
        if result.vote_type not in COUNTED_VOTE_TYPES:
            other_type_rows[result.vote_type] += 1
            continue
        vote_type = VoteType(result.vote_type)
        tallies.by_legislator.add(result.legislator_id, vote_type)
        tallies.by_bill.add(bill_id, vote_type)

    if unknown_vote_rows:
        logger.warning(
            "Skipped %d vote results whose vote id is not in votes.csv", unknown_vote_rows
        )
    if other_type_rows:
        logger.warning(
            "Skipped vote results that are neither yea nor nay (vote_type: rows): %s",
            dict(other_type_rows),
        )
    return tallies


def legislator_rows(legislators: Iterable[Legislator], tally: Tally) -> Iterator[LegislatorRow]:
    """One row per legislator, in input order. Legislators with no votes get zero counts."""
    unreported = tally.ids()
    for legislator in legislators:
        unreported.discard(legislator.id)
        yield LegislatorRow(
            id=legislator.id,
            name=legislator.name,
            num_supported_bills=tally.supported[legislator.id],
            num_opposed_bills=tally.opposed[legislator.id],
        )
    _warn_unreported(unreported, missing_from="legislators.csv", still_counted_in="bill totals")


def bill_rows(
    bills: Iterable[Bill], tally: Tally, legislators: Mapping[int, Legislator]
) -> Iterator[BillRow]:
    """One row per bill, in input order. A blank sponsor, or one not in ``legislators``,
    is "Unknown"."""
    unreported = tally.ids()
    for bill in bills:
        unreported.discard(bill.id)
        sponsor = None if bill.sponsor_id is None else legislators.get(bill.sponsor_id)
        yield BillRow(
            id=bill.id,
            title=bill.title,
            supporter_count=tally.supported[bill.id],
            opposer_count=tally.opposed[bill.id],
            primary_sponsor=sponsor.name if sponsor else UNKNOWN_SPONSOR,
        )
    _warn_unreported(unreported, missing_from="bills.csv", still_counted_in="legislator totals")


def _warn_unreported(ids: set[int], *, missing_from: str, still_counted_in: str) -> None:
    if ids:
        logger.warning(
            "Votes reference %d ids missing from %s (still counted in %s): %s",
            len(ids),
            missing_from,
            still_counted_in,
            sorted(ids),
        )
