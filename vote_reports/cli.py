"""Command-line entry point: read the four input CSVs and write both reports."""

import argparse
import logging
import os
import sys
import tempfile
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

    Memory is O(L + B + V): legislators, the vote → bill index and the ids already seen
    are kept, while vote results and bill titles are streamed. Time is O(L + B + V + R):
    each row is read once.

    Reports are written to a temporary directory first and moved into place only after
    both are complete, so an error leaves any earlier reports untouched.
    """
    bills_input = data_dir / "bills.csv"
    if (out_dir / BILLS_REPORT).resolve() == bills_input.resolve():
        raise ValueError(
            f"{out_dir / BILLS_REPORT} would replace the input; choose another --out-dir"
        )

    bill_id_by_vote_id = index_votes(read_votes(data_dir / "votes.csv"))
    tallies = tally_votes(read_vote_results(data_dir / "vote_results.csv"), bill_id_by_vote_id)
    legislators = {
        legislator.id: legislator for legislator in read_legislators(data_dir / "legislators.csv")
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    # Inside out_dir, so the final moves stay on one filesystem and are atomic.
    with tempfile.TemporaryDirectory(dir=out_dir, prefix=".staging-") as staging:
        staged = Path(staging)
        write_csv(
            staged / LEGISLATORS_REPORT,
            LegislatorRow._fields,
            legislator_rows(legislators.values(), tallies.by_legislator),
        )
        write_csv(
            staged / BILLS_REPORT,
            BillRow._fields,
            bill_rows(read_bills(bills_input), tallies.by_bill, legislators),
        )
        written = [out_dir / LEGISLATORS_REPORT, out_dir / BILLS_REPORT]
        for path in written:
            os.replace(staged / path.name, path)
    return written


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
