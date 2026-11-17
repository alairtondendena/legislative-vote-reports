"""Independent verification: the reports must match a SQL implementation of the report definitions.

Both reports are computed a second time in SQL (in-memory SQLite) and the results compared
row by row. The SQL is short and declarative, so it is easy to check against the definitions by
reading, and it shares no counting logic with the Python code. It runs on the sample
data and on seeded random datasets, with and without bad references.
"""

import csv
import sqlite3
from pathlib import Path

import pytest

from scripts.synthetic import DatasetSpec, write_dataset
from vote_reports.cli import BILLS_REPORT, LEGISLATORS_REPORT, generate_reports

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

SCHEMA = {
    "legislators": ("id INTEGER", "name TEXT"),
    "bills": ("id INTEGER", "title TEXT", "sponsor_id INTEGER"),
    "votes": ("id INTEGER", "bill_id INTEGER"),
    "vote_results": ("id INTEGER", "legislator_id INTEGER", "vote_id INTEGER", "vote_type INTEGER"),
}

# Each vote result joined to the bill it was cast on. Inner join: a result whose vote
# is unknown has no bill and is dropped. Only yeas and nays count.
CASTS = """
    WITH casts AS (
        SELECT r.legislator_id, v.bill_id, r.vote_type
        FROM vote_results r JOIN votes v ON v.id = r.vote_id
        WHERE r.vote_type IN (1, 2)
    )
"""

LEGISLATORS_SQL = (
    CASTS
    + """
    SELECT l.id, l.name,
           COUNT(CASE WHEN c.vote_type = 1 THEN 1 END) AS num_supported_bills,
           COUNT(CASE WHEN c.vote_type = 2 THEN 1 END) AS num_opposed_bills
    FROM legislators l LEFT JOIN casts c ON c.legislator_id = l.id
    GROUP BY l.rowid ORDER BY l.rowid
"""
)

BILLS_SQL = (
    CASTS
    + """
    SELECT b.id, b.title,
           COUNT(CASE WHEN c.vote_type = 1 THEN 1 END) AS supporter_count,
           COUNT(CASE WHEN c.vote_type = 2 THEN 1 END) AS opposer_count,
           COALESCE(s.name, 'Unknown') AS primary_sponsor
    FROM bills b
    LEFT JOIN legislators s ON s.id = b.sponsor_id
    LEFT JOIN casts c ON c.bill_id = b.id
    GROUP BY b.rowid ORDER BY b.rowid
"""
)

SAMPLE = None  # stands for the sample data/ directory
SYNTHETIC = [
    DatasetSpec(legislators=40, bills=30, voters_per_vote=25, seed=seed, dirty=dirty)
    for seed in (1, 2, 3)
    for dirty in (False, True)
]
ALL_DATASETS = [SAMPLE, *SYNTHETIC]
CLEAN_DATASETS = [SAMPLE, *(spec for spec in SYNTHETIC if not spec.dirty)]


def dataset_id(spec: DatasetSpec | None) -> str:
    if spec is None:
        return "sample"
    return f"seed{spec.seed}-{'dirty' if spec.dirty else 'clean'}"


def dataset_dir(spec: DatasetSpec | None, tmp_path: Path) -> Path:
    if spec is None:
        return DATA_DIR
    write_dataset(tmp_path / "data", spec)
    return tmp_path / "data"


def load_sqlite(data_dir: Path) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    for table, columns in SCHEMA.items():
        db.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        with (data_dir / f"{table}.csv").open(newline="", encoding="utf-8") as file:
            rows = list(csv.reader(file))[1:]
        placeholders = ", ".join("?" * len(columns))
        db.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)
    return db


def read_report(path: Path) -> list[tuple[str, ...]]:
    with path.open(newline="", encoding="utf-8") as file:
        return [tuple(row) for row in csv.reader(file)][1:]


def sql_report(db: sqlite3.Connection, query: str) -> list[tuple[str, ...]]:
    return [tuple(str(value) for value in row) for row in db.execute(query)]


@pytest.mark.parametrize("spec", ALL_DATASETS, ids=dataset_id)
@pytest.mark.parametrize(
    ("report", "query"), [(LEGISLATORS_REPORT, LEGISLATORS_SQL), (BILLS_REPORT, BILLS_SQL)]
)
def test_report_matches_sql(
    spec: DatasetSpec | None, tmp_path: Path, report: str, query: str
) -> None:
    data_dir = dataset_dir(spec, tmp_path)
    out_dir = tmp_path / "output"
    generate_reports(data_dir, out_dir)

    expected = sql_report(load_sqlite(data_dir), query)

    assert read_report(out_dir / report) == expected
    assert len(expected) > 0


@pytest.mark.parametrize("spec", CLEAN_DATASETS, ids=dataset_id)
def test_support_and_opposition_totals_agree(spec: DatasetSpec | None, tmp_path: Path) -> None:
    """Every cast is one legislator voting on one bill, so both reports must add up to
    the same totals, and (with every reference valid) to the number of vote results."""
    clean_data_dir = dataset_dir(spec, tmp_path)
    out_dir = tmp_path / "output"
    generate_reports(clean_data_dir, out_dir)
    legislators = read_report(out_dir / LEGISLATORS_REPORT)
    bills = read_report(out_dir / BILLS_REPORT)
    with (clean_data_dir / "vote_results.csv").open(newline="", encoding="utf-8") as file:
        vote_result_count = sum(1 for _ in csv.DictReader(file))

    supported = sum(int(row[2]) for row in legislators)
    opposed = sum(int(row[3]) for row in legislators)

    assert supported == sum(int(row[2]) for row in bills)
    assert opposed == sum(int(row[3]) for row in bills)
    assert supported + opposed == vote_result_count
