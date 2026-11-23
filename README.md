# Rush Hour Rerouting: How Fast Can a Map Heal Itself?

Problem 11: adaptive path-finding in dynamic weighted graphs.
When roads are blocked, slowed down or cleared, how should a routing service update its
shortest-path tree? We compare

* **full Dijkstra recomputation**,
* **per-edge incremental repair** (Ramalingam–Reps style, one edge change at a time),
* **batch repair** (all changes of a disruption in one sweep; proof in the report), and
* for a single destination, **A\*** from scratch and **LPA\*** (Lifelong Planning A*),

on a synthetic city and on real OpenStreetMap networks. Every repaired result is checked
against a fresh Dijkstra, in the tests and inside every experiment.

## 1. Setup

Requires **Python 3.10+**.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt    # also installs this repo as the `rush_hour` package
```

Optional: `pip install -r requirements-osm.txt` (osmnx, to download real cities) and
`pip install -r requirements-dev.txt` (ruff).

## 2. Run everything with one command

```bash
python run_all.py
```

Runs, in order: tests (pytest + hypothesis) → experiments (CSVs + figures in `results/`) →
`report/Rush_Hour_Rerouting_Report.docx` → `RESULTS_AND_INFORMATION.md` (project context, every figure and
the key numbers, generated from `results/`; **start here** for a quick overview). `run_all.py` prints its own wall time at the end.

| Command | What it does | Time (measured) |
|---|---|---|
| `python run_all.py --quick` | small graph, few trials (smoke test, same as CI) | ~45 s |
| `python run_all.py` | full run: 140×140 synthetic city, 15 trials, plus every cached real city | see `results/meta.json` → `runtime_seconds` |

### Flags (forwarded to `experiments/run_experiments.py`)

| Flag | Meaning |
|---|---|
| `--quick` | small graph and few trials |
| `--trials N`, `--seed S`, `--sizes 1 5 20 ...` | experiment size / reproducibility |
| `--width W --height H` | size of the synthetic city |
| `--closure {factor,delete}` | blocked road = 50× travel time (default) or deleted (weight ∞) |
| `--fleet-size K` | vehicles in the fleet-rerouting experiment (default 50) |
| `--graph-file data/x.graphml` | use a cached real network as the main graph (offline) |
| `--place "City, Country"` | download (once) and use a real network as the main graph |
| `--compare-graphs a.graphml b.graphml` | networks for the cross-graph comparison (default: every `data/*.graphml`; give no files to skip) |
| `--out DIR` | results folder (also used by the report builder) |
| `--report FILE.docx` | (run_all only) where to write the report |

### Real cities

```bash
pip install -r requirements-osm.txt
python scripts/fetch_cities.py           # Salt Lake City (USA, grid) and Bologna (Italy, irregular)
python run_all.py                        # picks up every data/*.graphml automatically
```

The two networks used in the results are committed in `data/` (© OpenStreetMap contributors, ODbL), so
the real-city experiments work offline straight after cloning. Cached files are read with
plain networkx if osmnx is not installed. The loader supports osmnx 1.x and 2.x. If no real network is
cached, the report's real-city section says so instead of showing numbers.

## 3. Run the pieces separately

```bash
python -m pytest                                    # all tests
python experiments/run_experiments.py [flags]      # experiments + figures
python report/build_report.py [--results DIR]      # rebuild the report (+PDF if LibreOffice is installed)
ruff check .                                        # lint
```

## 4. What the experiments measure

| Output | Content |
|---|---|
| `raw_main.csv`, `summary_main.csv`, fig1–3 | speed-up vs disruption size for 4 disruption models (scattered closures, accident zone, congestion wave, shortest-path-tree closures), per-edge vs batch repair, **all vs effective (non-no-op) updates**, medians + IQR |
| `raw_scaling.csv`, fig4 | scaling with the number of nodes |
| `raw_ripple.csv`, fig5 | ripple size vs shortest-path-tree subtree size, by road class |
| fig6 | one accident: which nodes are rerouted and by how much |
| `raw_fleet.csv`, fig7 | fleet of K vehicles: routes changed, delay, stranded vehicles |
| `raw_p2p.csv`, fig8 | single-destination rerouting: Dijkstra, early-exit Dijkstra, A*, batch repair, LPA* |
| `raw_closure.csv` | ×50 closure vs true deletion on identical disruptions |
| `raw_marks.csv` | micro-benchmark: Python `set()` vs generation-stamped arrays |
| `raw_crossgraph.csv`, `summary_crossgraph.csv`, `graph_stats.csv`, fig9 | synthetic vs real networks |
| `meta.json` | all parameters, break-even points, git commit, exact command line |

Timing: every repair is repeated until it has run ≥ 2 ms (3–50 runs) and the median is used;
graph, distances and parents are restored exactly between repeats. The key results are summarised
in the report's abstract and conclusion, which are generated from these files.

## 5. Project layout

```
src/rush_hour/graph.py        graph container (INF weight = deleted road), synthetic city, networkx conversion
src/rush_hour/sssp.py         Dijkstra, DynamicSSSP: per-edge + batch repair, parent tree, path_to
src/rush_hour/lpa.py          A*, early-exit Dijkstra, LPA*, consistent straight-line heuristic
src/rush_hour/disruptions.py  closure / accident / congestion / tree-edge generators, closure models
src/rush_hour/osm.py          OpenStreetMap download + cached .graphml loading (osmnx 1.x and 2.x)
src/rush_hour/stats.py        graph statistics (degree, hop diameter, one-way fraction)
experiments/                  run_experiments.py (all experiments) + plots.py (figures)
report/build_report.py        results/ -> Rush_Hour_Rerouting_Report.docx
report/build_summary.py       results/ -> RESULTS_AND_INFORMATION.md
RESULTS_AND_INFORMATION.md    generated overview of the project, figures and results
data/                         cached OpenStreetMap networks used in the results
scripts/fetch_cities.py       download + cache the real networks
tests/                        unit tests, LPA* tests, hypothesis property tests
results/                      CSVs, figures, meta.json (generated)
run_all.py                    one-command pipeline
.github/workflows/ci.yml      lint + tests + quick pipeline on latest and minimum dependency versions
```

## 6. Using the algorithms in your own code

```python
from rush_hour.graph import INF, make_synthetic_city
from rush_hour.sssp import DynamicSSSP

g = make_synthetic_city(60, 60, seed=0)
dyn = DynamicSSSP(g, s=0)                  # runs Dijkstra once
u, v, w = g.edges()[10]
dyn.update_edge(u, v, INF)                 # close a road; returns #nodes whose distance changed
print(dyn.path_to(100), dyn.dist[100])     # new route and travel time (deciseconds)
dyn.update_edges([(u, v, w)])              # batch API: re-open it (any number of changes)
```

Weights are **positive integers** (travel time in deciseconds); `INF` deletes an edge.

## 7. Before you submit

* Team: Dhrithi Shashibushan, Avishi Singh, Kritika Singh, Pankhuri Singhal. Their roles in the report
  come from the `TEAM` list at the top of `report/build_report.py`; fix the order there if needed.
* Fill in the course and date on the title page of the report.
* Check the reference list against the original papers.
* The PDF is only produced if LibreOffice is installed; otherwise export the .docx to PDF manually.
* You should be able to explain every proof step and figure in your own words.

## Notes and limitations

* Pure Python for readability; absolute times are slower than C++/Rust, and break-even sizes
  would move in compiled code. The report has a full "threats to validity" section.
* Single source (one depot); the disruption models are random, not calibrated on real incident data.
