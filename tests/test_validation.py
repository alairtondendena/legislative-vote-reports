"""Inputs that contradict themselves must stop the run, and leave earlier reports untouched.

Each case damages one file of a copy of the sample data in a way that used to produce
wrong reports silently (see docs/DECISIONS.md §3: E13-E15 and E18).
"""

import shutil
from pathlib import Path

import pytest

from vote_reports.cli import BILLS_REPORT, LEGISLATORS_REPORT, generate_reports

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data"
PREVIOUS_REPORT = "previous report\n"


def append_line(path: Path, line: str) -> None:
    """Append a line, adding a line break first if the file doesn't end with one."""
    text = path.read_text(encoding="utf-8")
    separator = "" if text.endswith("\n") else "\n"
    path.write_text(f"{text}{separator}{line}\n", encoding="utf-8")


def overwrite(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


CASES = {
    "empty file": (
        "vote_results.csv",
        lambda p: overwrite(p, ""),
        r"vote_results\.csv: file is empty",
    ),
    "header only, misspelled columns": (
        "vote_results.csv",
        lambda p: overwrite(p, "id,legislatorid,voteid,votetype\n"),
        r"vote_results\.csv: missing column\(s\) legislator_id, vote_id, vote_type",
    ),
    "missing column": (
        "bills.csv",
        lambda p: overwrite(p, "id,title\n1,A bill\n"),
        r"bills\.csv: missing column\(s\) sponsor_id",
    ),
    "unquoted comma in a title": (
        "bills.csv",
        lambda p: append_line(p, "9,Act to Fund Roads, 2021,412211"),
        r"bills\.csv, line \d+: more fields than the 3 columns",
    ),
    "empty id": (
        "bills.csv",
        lambda p: append_line(p, ",A bill without an id,412211"),
        r"bills\.csv, line \d+: invalid row",
    ),
    "missing field": (
        "votes.csv",
        lambda p: append_line(p, "3400000"),
        r"votes\.csv, line \d+: fewer fields than the 2 columns",
    ),
    "duplicate legislator id": (
        "legislators.csv",
        lambda p: append_line(p, "904789,Someone Else"),
        r"legislators\.csv, line \d+: duplicate id 904789",
    ),
    "duplicate bill id": (
        "bills.csv",
        lambda p: append_line(p, "2952375,H.R. 5376: Build Back Better Act,412211"),
        r"bills\.csv, line \d+: duplicate id 2952375",
    ),
    "duplicate vote id": (
        "votes.csv",
        lambda p: append_line(p, "3314452,2952375"),
        r"votes\.csv, line \d+: duplicate id 3314452",
    ),
}


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    return Path(shutil.copytree(SAMPLE_DIR, tmp_path / "data"))


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    """An output directory holding reports from an earlier run."""
    out = tmp_path / "output"
    out.mkdir()
    for report in (LEGISLATORS_REPORT, BILLS_REPORT):
        (out / report).write_text(PREVIOUS_REPORT, encoding="utf-8")
    return out


@pytest.mark.parametrize(("file", "damage", "error"), CASES.values(), ids=CASES.keys())
def test_self_contradictory_input_stops_the_run(
    data_dir: Path, out_dir: Path, file: str, damage: object, error: str
) -> None:
    assert callable(damage)
    damage(data_dir / file)

    with pytest.raises(ValueError, match=error):
        generate_reports(data_dir, out_dir)

    # Neither report is replaced, even the one that could be finished before the error,
    # and no temporary files are left behind.
    assert sorted(path.name for path in out_dir.iterdir()) == sorted(
        [LEGISLATORS_REPORT, BILLS_REPORT]
    )
    for report in (LEGISLATORS_REPORT, BILLS_REPORT):
        assert (out_dir / report).read_text(encoding="utf-8") == PREVIOUS_REPORT


def test_successful_run_replaces_reports_and_leaves_no_temporary_files(
    data_dir: Path, out_dir: Path
) -> None:
    generate_reports(data_dir, out_dir)

    assert sorted(path.name for path in out_dir.iterdir()) == sorted(
        [LEGISLATORS_REPORT, BILLS_REPORT]
    )
    for report in (LEGISLATORS_REPORT, BILLS_REPORT):
        assert (out_dir / report).read_text(encoding="utf-8") != PREVIOUS_REPORT


def test_repeated_vote_result_ids_are_not_checked(data_dir: Path, out_dir: Path) -> None:
    # Checking them would need a set of every vote result id: O(R) memory. Pinned here
    # so that a change to this documented limitation is deliberate.
    append_line(data_dir / "vote_results.csv", "92516784,904789,3321166,2")

    generate_reports(data_dir, out_dir)
