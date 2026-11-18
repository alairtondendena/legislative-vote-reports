"""Measure run time and peak memory of the report generator as the input grows.

    uv run python -m scripts.benchmark            # about a minute
    uv run python -m scripts.benchmark --quick    # small sizes, a few seconds

Two experiments, each a table:

1. More votes: shaped like the US House (500 legislators, 435 voting on each vote), with
   the number of votes V growing. R grows with V; memory should grow only with V.
2. More results per vote: L and V fixed while more legislators vote on each vote, so
   only R grows. Memory should stay flat; this separates the effect of R from that of V.

Each run is a separate process that calls the CLI's ``main`` and then reports its own peak
resident memory (``VmHWM`` in ``/proc/self/status``). Linux only (on macOS, run it inside the
``check`` container). ``getrusage``/``wait4`` are not used: on Linux a child's ``ru_maxrss``
starts from the parent's RSS at fork time, so it would include the benchmark's own memory.
"""

import argparse
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path

from scripts.synthetic import DatasetSpec, write_dataset

SHARE_OF_BILLS_WITH_A_VOTE = 0.8  # matches scripts/synthetic.py
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Runs in the measured process: the CLI, then its own peak RSS (kB) as the last stdout line.
MEASURED_RUN = """
import sys
from vote_reports.cli import main

exit_code = main(sys.argv[1:])
with open("/proc/self/status") as status:
    print(next(line.split()[1] for line in status if line.startswith("VmHWM:")))
sys.exit(exit_code)
"""


def bills_for(votes: int) -> int:
    return round(votes / SHARE_OF_BILLS_WITH_A_VOTE)


def more_votes(quick: bool) -> list[DatasetSpec]:
    votes = [100, 1_000] if quick else [100, 1_000, 5_000, 10_000, 20_000]
    return [DatasetSpec(legislators=500, bills=bills_for(v), voters_per_vote=435) for v in votes]


def more_results_per_vote(quick: bool) -> list[DatasetSpec]:
    voters = [250, 1_000] if quick else [250, 1_000, 2_000, 4_000]
    return [
        DatasetSpec(legislators=5_000, bills=bills_for(2_000), voters_per_vote=n) for n in voters
    ]


def run(data_dir: Path, out_dir: Path) -> tuple[float, float]:
    """Generate reports for ``data_dir``; return wall-clock seconds and peak RSS in MB."""
    command = [sys.executable, "-c", MEASURED_RUN, "--data-dir", str(data_dir)]
    start = time.perf_counter()
    result = subprocess.run(
        [*command, "--out-dir", str(out_dir)], capture_output=True, text=True, check=True
    )
    seconds = time.perf_counter() - start
    peak_kb = int(result.stdout.splitlines()[-1])
    return seconds, peak_kb / 1024


def print_table(title: str, specs: Iterable[DatasetSpec], workdir: Path) -> None:
    print(f"\n{title}\n")
    print("| L | V | R | Input size | Time | R per second | Peak RSS |")
    print("|---:|---:|---:|---:|---:|---:|---:|")
    for number, spec in enumerate(specs):
        data_dir = workdir / f"data-{number}"
        vote_results = write_dataset(data_dir, spec)
        votes = vote_results // spec.voters_per_vote  # clean datasets have no extra rows
        input_mb = sum(path.stat().st_size for path in data_dir.glob("*.csv")) / 2**20
        seconds, rss_mb = run(data_dir, workdir / "output")
        print(
            f"| {spec.legislators:,} | {votes:,} | {vote_results:,} | {input_mb:,.1f} MB "
            f"| {seconds:.2f} s | {vote_results / seconds:,.0f} | {rss_mb:.1f} MB |",
            flush=True,
        )
        for path in data_dir.iterdir():  # free disk space before the next dataset
            path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark the report generator.")
    parser.add_argument("--quick", action="store_true", help="small sizes only")
    args = parser.parse_args()

    if not Path("/proc/self/status").exists():
        sys.exit("This benchmark reads /proc and needs Linux; on macOS, run it with Docker.")
    with tempfile.TemporaryDirectory() as workdir:
        _, baseline_mb = run(DATA_DIR, Path(workdir) / "output")
        print(f"Python {sys.version.split()[0]}; peak RSS on the sample data: {baseline_mb:.1f} MB")
        print_table("1. More votes (V and R grow)", more_votes(args.quick), Path(workdir))
        print_table(
            "2. More results per vote (only R grows)",
            more_results_per_vote(args.quick),
            Path(workdir),
        )


if __name__ == "__main__":
    main()
