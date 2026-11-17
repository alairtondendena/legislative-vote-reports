"""Counting rules and edge cases (E1-E9 in docs/PLAN.md §4), on in-memory records."""

from collections.abc import Iterator
from itertools import count, islice

import pytest

from vote_reports.models import Bill, Legislator, Vote, VoteResult, VoteType
from vote_reports.reports import (
    UNKNOWN_SPONSOR,
    BillRow,
    LegislatorRow,
    bill_rows,
    index_votes,
    legislator_rows,
    tally_votes,
)

YEA, NAY = VoteType.YEA, VoteType.NAY

ALICE = Legislator(1, "Alice")
BOB = Legislator(2, "Bob")
CAROL = Legislator(3, "Carol")
LEGISLATORS = {legislator.id: legislator for legislator in (ALICE, BOB, CAROL)}

BILL_A = Bill(id=10, title="Bill A", sponsor_id=ALICE.id)
BILL_B = Bill(id=20, title="Bill B", sponsor_id=BOB.id)
VOTE_A = Vote(id=100, bill_id=BILL_A.id)
VOTE_B = Vote(id=200, bill_id=BILL_B.id)
BILL_ID_BY_VOTE_ID = {VOTE_A.id: BILL_A.id, VOTE_B.id: BILL_B.id}


def results(*casts: tuple[Legislator | int, Vote | int, int]) -> Iterator[VoteResult]:
    """Build vote results from (legislator, vote, vote_type) triples; ids may be raw ints."""
    for result_id, (legislator, vote, vote_type) in enumerate(casts, start=1):
        yield VoteResult(
            id=result_id,
            legislator_id=legislator if isinstance(legislator, int) else legislator.id,
            vote_id=vote if isinstance(vote, int) else vote.id,
            vote_type=vote_type,
        )


def test_counts_support_and_opposition_per_legislator_and_per_bill() -> None:
    tallies = tally_votes(
        results(
            (ALICE, VOTE_A, YEA),
            (BOB, VOTE_A, YEA),
            (CAROL, VOTE_A, NAY),
            (ALICE, VOTE_B, NAY),
            (BOB, VOTE_B, YEA),
        ),
        BILL_ID_BY_VOTE_ID,
    )

    assert list(legislator_rows([ALICE, BOB, CAROL], tallies.by_legislator)) == [
        LegislatorRow(ALICE.id, "Alice", num_supported_bills=1, num_opposed_bills=1),
        LegislatorRow(BOB.id, "Bob", num_supported_bills=2, num_opposed_bills=0),
        LegislatorRow(CAROL.id, "Carol", num_supported_bills=0, num_opposed_bills=1),
    ]
    assert list(bill_rows([BILL_A, BILL_B], tallies.by_bill, LEGISLATORS)) == [
        BillRow(BILL_A.id, "Bill A", supporter_count=2, opposer_count=1, primary_sponsor="Alice"),
        BillRow(BILL_B.id, "Bill B", supporter_count=1, opposer_count=1, primary_sponsor="Bob"),
    ]


def test_e1_sponsor_missing_from_legislators_is_unknown() -> None:
    orphan_bill = Bill(id=30, title="Orphan", sponsor_id=999)
    tallies = tally_votes(results(), BILL_ID_BY_VOTE_ID)

    [row] = bill_rows([orphan_bill], tallies.by_bill, LEGISLATORS)

    assert row.primary_sponsor == UNKNOWN_SPONSOR == "Unknown"


def test_e2_legislator_without_votes_gets_zero_counts() -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA)), BILL_ID_BY_VOTE_ID)

    rows = list(legislator_rows([ALICE, CAROL], tallies.by_legislator))

    assert rows[1] == LegislatorRow(CAROL.id, "Carol", 0, 0)


def test_e3_bill_without_vote_gets_zero_counts() -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA)), BILL_ID_BY_VOTE_ID)

    rows = list(bill_rows([BILL_A, BILL_B], tallies.by_bill, LEGISLATORS))

    assert rows[1] == BillRow(BILL_B.id, "Bill B", 0, 0, "Bob")


def test_e4_unknown_legislator_counts_for_bill_but_gets_no_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA), (999, VOTE_A, YEA)), BILL_ID_BY_VOTE_ID)

    legislators = list(legislator_rows([ALICE], tallies.by_legislator))
    [bill] = bill_rows([BILL_A], tallies.by_bill, LEGISLATORS)

    assert [row.id for row in legislators] == [ALICE.id]
    assert bill.supporter_count == 2
    assert "missing from legislators.csv" in caplog.text
    assert "[999]" in caplog.text


def test_e4_vote_on_bill_missing_from_bills_counts_for_legislator(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA), (ALICE, VOTE_B, NAY)), BILL_ID_BY_VOTE_ID)

    [alice] = legislator_rows([ALICE], tallies.by_legislator)
    list(bill_rows([BILL_A], tallies.by_bill, LEGISLATORS))

    assert (alice.num_supported_bills, alice.num_opposed_bills) == (1, 1)
    assert "missing from bills.csv" in caplog.text
    assert f"[{BILL_B.id}]" in caplog.text


def test_e5_result_for_unknown_vote_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA), (ALICE, 999, NAY)), BILL_ID_BY_VOTE_ID)

    [alice] = legislator_rows([ALICE], tallies.by_legislator)

    assert (alice.num_supported_bills, alice.num_opposed_bills) == (1, 0)
    assert "Skipped 1 vote results whose vote id is not in votes.csv" in caplog.text


def test_e6_vote_type_other_than_yea_or_nay_is_skipped(caplog: pytest.LogCaptureFixture) -> None:
    present = 3
    tallies = tally_votes(results((ALICE, VOTE_A, YEA), (BOB, VOTE_A, present)), BILL_ID_BY_VOTE_ID)

    rows = list(legislator_rows([ALICE, BOB], tallies.by_legislator))
    [bill] = bill_rows([BILL_A], tallies.by_bill, LEGISLATORS)

    assert rows[1] == LegislatorRow(BOB.id, "Bob", 0, 0)
    assert (bill.supporter_count, bill.opposer_count) == (1, 0)
    assert "neither yea nor nay" in caplog.text
    assert "{3: 1}" in caplog.text


def test_e8_more_than_one_vote_per_bill_is_flagged(caplog: pytest.LogCaptureFixture) -> None:
    second_vote_on_a = Vote(id=101, bill_id=BILL_A.id)

    bill_id_by_vote_id = index_votes([VOTE_A, second_vote_on_a, VOTE_B])

    assert bill_id_by_vote_id == {VOTE_A.id: BILL_A.id, 101: BILL_A.id, VOTE_B.id: BILL_B.id}
    assert "more than one vote" in caplog.text
    assert f"[{BILL_A.id}]" in caplog.text


def test_e9_rows_keep_input_order() -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA)), BILL_ID_BY_VOTE_ID)

    legislators = list(legislator_rows([CAROL, ALICE, BOB], tallies.by_legislator))
    bills = list(bill_rows([BILL_B, BILL_A], tallies.by_bill, LEGISLATORS))

    assert [row.id for row in legislators] == [CAROL.id, ALICE.id, BOB.id]
    assert [row.id for row in bills] == [BILL_B.id, BILL_A.id]


def test_clean_data_logs_no_warnings(caplog: pytest.LogCaptureFixture) -> None:
    tallies = tally_votes(results((ALICE, VOTE_A, YEA)), index_votes([VOTE_A, VOTE_B]))

    list(legislator_rows([ALICE, BOB], tallies.by_legislator))
    list(bill_rows([BILL_A, BILL_B], tallies.by_bill, LEGISLATORS))

    assert caplog.records == []


def test_bill_rows_are_produced_lazily() -> None:
    # An endless stream of bills: if bill_rows tried to load its input, this would hang.
    endless_bills = (Bill(id=n, title=f"Bill {n}", sponsor_id=ALICE.id) for n in count())
    tallies = tally_votes(results(), BILL_ID_BY_VOTE_ID)

    first_rows = list(islice(bill_rows(endless_bills, tallies.by_bill, LEGISLATORS), 3))

    assert [row.id for row in first_rows] == [0, 1, 2]
