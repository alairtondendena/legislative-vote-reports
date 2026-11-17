"""Command-line behaviour: arguments, exit codes and the input-overwrite guard."""

import shutil
from pathlib import Path

import pytest

from vote_reports.cli import BILLS_REPORT, LEGISLATORS_REPORT, main

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    copy = tmp_path / "data"
    shutil.copytree(DATA_DIR, copy)
    return copy


def test_writes_both_reports_and_exits_zero(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = tmp_path / "reports"

    exit_code = main(["--data-dir", str(data_dir), "--out-dir", str(out_dir)])

    assert exit_code == 0
    assert (out_dir / LEGISLATORS_REPORT).is_file()
    assert (out_dir / BILLS_REPORT).is_file()
    assert str(out_dir / BILLS_REPORT) in capsys.readouterr().out


def test_refuses_to_overwrite_the_input_bills_file(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    original = (data_dir / "bills.csv").read_bytes()

    exit_code = main(["--data-dir", str(data_dir), "--out-dir", str(data_dir)])

    assert exit_code == 1
    assert "would overwrite the input" in capsys.readouterr().err
    assert (data_dir / "bills.csv").read_bytes() == original


def test_missing_input_file_exits_with_error(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (data_dir / "votes.csv").unlink()

    exit_code = main(["--data-dir", str(data_dir), "--out-dir", str(tmp_path / "reports")])

    assert exit_code == 1
    assert "votes.csv" in capsys.readouterr().err


def test_malformed_input_exits_with_error(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (data_dir / "vote_results.csv").open("a", encoding="utf-8") as file:
        file.write("\nnot-a-number,1,1,1\n")

    exit_code = main(["--data-dir", str(data_dir), "--out-dir", str(tmp_path / "reports")])

    assert exit_code == 1
    assert "vote_results.csv, line" in capsys.readouterr().err
