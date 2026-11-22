"""One command to run everything: tests -> experiments -> figures -> Word report.

    python run_all.py                       # synthetic city (works offline), full run
    python run_all.py --quick               # small, ~1 minute
    python run_all.py --place "Piedmont, California, USA"   # real OpenStreetMap city
Extra flags (--trials, --sizes, --seed, ...) are forwarded to experiments/run_experiments.py.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    print("\n$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(r.returncode)


if __name__ == "__main__":
    py = sys.executable
    run([py, os.path.join("tests", "test_correctness.py")])
    run([py, os.path.join("experiments", "run_experiments.py")] + sys.argv[1:])
    run([py, os.path.join("report", "build_report.py")])
    print("\nAll done. Open report/Rush_Hour_Rerouting_Report.docx and the results/ folder.")
