"""CSV parsing and writing: line endings, quoting, encoding and malformed input."""

import csv
from pathlib import Path

import pytest

from vote_reports.csv_io import read_bills, read_legislators, read_vote_results, write_csv
from vote_reports.models import Bill, Legislator, VoteResult


def test_reads_crlf_and_lf_line_endings_alike(tmp_path: Path) -> None:
    # The sample bills.csv and votes.csv use CRLF; the other two use LF.
    crlf = tmp_path / "crlf.csv"
    lf = tmp_path / "lf.csv"
    crlf.write_bytes(b"id,name\r\n1,Alice\r\n2,Bob")
    lf.write_bytes(b"id,name\n1,Alice\n2,Bob\n")

    expected = [Legislator(1, "Alice"), Legislator(2, "Bob")]
    assert list(read_legislators(crlf)) == expected
    assert list(read_legislators(lf)) == expected


def test_reads_file_with_utf8_byte_order_mark(tmp_path: Path) -> None:
    # Spreadsheet tools often save CSVs with a BOM, which would otherwise end up
    # in the first header ("﻿id") and make every row look malformed.
    path = tmp_path / "legislators.csv"
    path.write_bytes(b"\xef\xbb\xbfid,name\n1,Alice\n")

    assert list(read_legislators(path)) == [Legislator(1, "Alice")]


def test_reads_columns_by_header_name_not_position(tmp_path: Path) -> None:
    path = tmp_path / "bills.csv"
    path.write_text("sponsor_id,id,title\n7,1,A bill\n", encoding="utf-8")

    assert list(read_bills(path)) == [Bill(id=1, title="A bill", sponsor_id=7)]


def test_malformed_row_error_names_file_and_line(tmp_path: Path) -> None:
    path = tmp_path / "vote_results.csv"
    path.write_text(
        "id,legislator_id,vote_id,vote_type\n1,10,100,1\n2,11,100,yea\n", encoding="utf-8"
    )
    results = read_vote_results(path)

    assert next(results) == VoteResult(id=1, legislator_id=10, vote_id=100, vote_type=1)
    with pytest.raises(ValueError, match=r"vote_results\.csv, line 3"):
        next(results)


def test_missing_column_is_reported_as_malformed(tmp_path: Path) -> None:
    path = tmp_path / "bills.csv"
    path.write_text("id,title\n1,A bill\n", encoding="utf-8")

    with pytest.raises(ValueError, match=r"line 2.*sponsor_id"):
        list(read_bills(path))


def test_written_csv_round_trips_commas_quotes_and_unicode(tmp_path: Path) -> None:
    path = tmp_path / "out" / "report.csv"
    rows = [(1, 'H.R. 1: "For the People" Act, as amended'), (2, "Rep. Nydia Velázquez")]

    write_csv(path, ("id", "text"), rows)

    with path.open(newline="", encoding="utf-8") as file:
        assert list(csv.reader(file)) == [["id", "text"], *([str(i), t] for i, t in rows)]
