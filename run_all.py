"""One command to run everything: tests -> experiments -> figures -> Word report.

    python run_all.py                       # synthetic city, full run
    python run_all.py --quick               # small smoke run (timing: see README)
    python run_all.py --place "Piedmont, California, USA"   # real OpenStreetMap city
Extra flags (--trials, --sizes, --seed, --out, ...) are forwarded to experiments/run_experiments.py;
--out is also passed to the report builder so the report is built from the same results;
--report sets where the .docx is written.
"""
import argparse
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def run(cmd):
    print("\n$", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=ROOT)
    if r.returncode != 0:
        sys.exit(r.returncode)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    ap.add_argument("--report", default=os.path.join(ROOT, "report", "Rush_Hour_Rerouting_Report.docx"),
                    help="where to write the Word report (default: report/Rush_Hour_Rerouting_Report.docx)")
    known, rest = ap.parse_known_args()
    rest += ["--out", known.out]
    t0 = time.time()
    py = sys.executable
    run([py, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"])
    run([py, os.path.join("experiments", "run_experiments.py")] + rest)
    run([py, os.path.join("report", "build_report.py"), "--results", known.out, "--out", known.report])
    print(f"\nAll done in {time.time() - t0:.0f} s. Report: {os.path.relpath(known.report, ROOT)}; "
          f"results: {os.path.relpath(known.out, ROOT)}")
