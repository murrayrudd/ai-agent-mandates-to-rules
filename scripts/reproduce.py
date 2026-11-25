"""Run the complete offline replication from the repository root or any other directory."""
import csv
import hashlib
import json
import os
import subprocess
import sys
from itertools import zip_longest
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"


def check_archive():
    entries = (ROOT / "SHA256SUMS.txt").read_text(encoding="utf8").splitlines()
    for line in entries:
        expected, name = line.split("  ", 1)
        actual = hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Release file differs: {name}")


def run(script, *args):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg",
               MPLCONFIGDIR=str(BUILD / "matplotlib-cache"), SOURCE_DATE_EPOCH="1795564800")
    subprocess.run([sys.executable, "-B", str(ROOT / script), *map(str, args)],
                   cwd=ROOT, env=env, check=True)


def compare_tables(reference, output, filenames):
    for name in filenames:
        expected, actual = reference / name, output / name
        if expected.suffix == ".json":
            if json.loads(expected.read_text()) != json.loads(actual.read_text()):
                raise ValueError(f"Planning result differs: {name}")
            continue
        with expected.open(encoding="utf8", newline="") as original, actual.open(encoding="utf8", newline="") as new:
            for n, (a, b) in enumerate(zip_longest(csv.reader(original), csv.reader(new)), 1):
                if a != b:
                    raise ValueError(f"Table differs: {name}, row {n}: {a} vs {b}")


def check_figures():
    for path in sorted((ROOT / "results/figures").glob("*.png")):
        with Image.open(path) as a, Image.open(BUILD / "figures" / path.name) as b:
            if a.size != b.size or ImageChops.difference(a.convert("RGB"), b.convert("RGB")).getbbox():
                raise ValueError(f"Figure pixels differ: {path.name}. Check the rendering environment.")
        pdf = BUILD / "figures" / path.with_suffix(".pdf").name
        if not pdf.read_bytes().startswith(b"%PDF-"):
            raise ValueError(f"Missing PDF figure: {pdf.name}")


def main():
    check_archive()
    BUILD.mkdir(exist_ok=True)
    run("design/checks/validate_design.py")
    run("scripts/replay.py")
    calibration = ROOT / "development/calibration"
    run("scripts/plan_sample.py", calibration / "events.jsonl.gz", BUILD / "planning")
    compare_tables(calibration / "planning", BUILD / "planning",
                   [p.name for p in (calibration / "planning").iterdir() if p.is_file()])
    run("scripts/analyze.py", ROOT / "data/main", BUILD / "analysis")
    analysis = ROOT / "results/analysis"
    compare_tables(analysis, BUILD / "analysis", [p.name for p in analysis.glob("*.csv")])
    run("scripts/paper_tables.py", ROOT / "data/main", BUILD / "analysis", BUILD / "manuscript")
    names = ["table_3_loss_and_reviews.csv", "table_4_recurrence.csv", "table_5_total_cost.csv", "text_diagnostics.csv"]
    compare_tables(ROOT / "results/manuscript", BUILD / "manuscript", names)
    run("scripts/plot_results.py", BUILD / "analysis", BUILD / "figures")
    run("scripts/plot_specification.py", BUILD / "analysis", BUILD / "figures")
    check_figures()
    print("PASS: calibration planning, eight analysis tables, three manuscript results tables, text diagnostics, and three figures.")


if __name__ == "__main__":
    main()
