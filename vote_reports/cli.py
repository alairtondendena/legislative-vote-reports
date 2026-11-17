"""Command-line entry point: read the four input CSVs and write both reports."""

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from vote_reports.csv_io import (
    read_bills,
    read_legislators,
    read_vote_results,
    read_votes,
    write_csv,
)
from vote_reports.reports import (
    BillRow,
    LegislatorRow,
    bill_rows,
    index_votes,
    legislator_rows,
    tally_votes,
)

LEGISLATORS_REPORT = "legislators-support-oppose-count.csv"
BILLS_REPORT = "bills.csv"


def generate_reports(data_dir: Path, out_dir: Path) -> list[Path]:
    """Write both reports to ``out_dir`` and return their paths.

    Memory is O(L + V): legislators and the vote → bill index are kept, while vote
    results and bills are streamed. Time is O(L + B + V + R): each row is read once.
    """
    bills_input = data_dir / "bills.csv"
    bills_output = out_dir / BILLS_REPORT
    # The bills input is still being read while the report is written, so writing over
    # it would truncate it mid-read.
    if bills_output.resolve() == bills_input.resolve():
        raise ValueError(f"{bills_output} would overwrite the input; choose another --out-dir")

    bill_id_by_vote_id = index_votes(read_votes(data_dir / "votes.csv"))
    tallies = tally_votes(read_vote_results(data_dir / "vote_results.csv"), bill_id_by_vote_id)
    legislators = {
        legislator.id: legislator for legislator in read_legislators(data_dir / "legislators.csv")
    }

    legislators_output = out_dir / LEGISLATORS_REPORT
    write_csv(
        legislators_output,
        LegislatorRow._fields,
        legislator_rows(legislators.values(), tallies.by_legislator),
    )
    write_csv(
        bills_output,
        BillRow._fields,
        bill_rows(read_bills(bills_input), tallies.by_bill, legislators),
    )
    return [legislators_output, bills_output]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m vote_reports",
        description="Count how each legislator voted and how each bill was voted on.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="directory holding the four input CSVs (default: %(default)s)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("output"),
        help="directory to write the reports to (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(format="%(levelname)s: %(message)s")

    try:
        written = generate_reports(args.data_dir, args.out_dir)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for path in written:
        print(f"Wrote {path}")
    return 0
