# Rush Hour Rerouting: How Fast Can a Map Heal Itself?

Problem 11 – adaptive path-finding in dynamic weighted graphs.
Compares **full Dijkstra recomputation** with **incremental shortest-path repair**
(Ramalingam–Reps style) when roads are blocked, slowed down, or cleared.

## 1. Setup (about 2 minutes)

Requires **Python 3.9+**.

```bash
cd rush_hour_rerouting
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Run everything with one command

```bash
python run_all.py
```

This runs, in order: correctness tests → experiments (CSVs + 6 figures in `results/`)
→ builds `report/Rush_Hour_Rerouting_Report.docx`.

| Command | What it does | Time |
|---|---|---|
| `python run_all.py --quick` | small graph, few trials (smoke test) | ~15 s |
| `python run_all.py` | full run on the synthetic city (~20k nodes, 15 trials) | ~2 min |
| `python run_all.py --place "Piedmont, California, USA"` | **real OpenStreetMap city** | depends on city |

The shipped results/report used `python run_all.py --trials 30` (~3 min).
Useful extra flags (forwarded to the experiment script): `--trials 30`, `--seed 1`,
`--sizes 1 5 20 100 500`, `--width 100 --height 100` (synthetic city size).

### Using a real city (recommended for the final report)
```bash
pip install osmnx
python run_all.py --place "Piedmont, California, USA"
```
The street network is downloaded once and cached in `data/`. Start with a small city or
neighbourhood (5k–50k nodes); very large cities make the pure-Python experiment slow.
The report is regenerated automatically with the real-map numbers, and the “synthetic data”
note disappears.

## 3. Run the pieces separately

```bash
python tests/test_correctness.py                         # repair == Dijkstra on random graphs
python experiments/run_experiments.py [--place ...]      # experiments + figures
python report/build_report.py                            # rebuild the Word report (+PDF if LibreOffice is installed)
```

## 4. Project layout

```
src/graph.py          graph container, synthetic city generator, OSMnx loader
src/sssp.py           Dijkstra + DynamicSSSP (decrease / increase repair)
src/disruptions.py    scattered closures, accident zone, congestion wave
tests/                randomised correctness tests
experiments/          benchmark + figure generation
report/               build_report.py  ->  Rush_Hour_Rerouting_Report.docx / .pdf
results/              CSVs, meta.json, fig1..fig6 (generated)
run_all.py            one-command pipeline
```

## 5. Using the algorithm in your own code

```python
from graph import make_synthetic_city
from sssp import DynamicSSSP

g = make_synthetic_city(60, 60, seed=0)
dyn = DynamicSSSP(g, s=0)               # runs Dijkstra once
u, v, w = g.edges()[10]
changed = dyn.update_edge(u, v, w * 50) # block a road; returns #nodes whose distance changed
print(changed, dyn.dist[100])
dyn.update_edge(u, v, w)                # clear it again
```
Weights must be **positive integers** (the loaders store travel time in deciseconds).

## 6. Before you submit

* Fill in the team names on the title page and in Appendix A of the report.
* Re-run on a real city (`--place ...`) so the report is based on real data.
* Check the reference list against the original papers.
* Skim the report text: the numbers are filled in automatically, but you should be able to explain
  every proof step and figure in your own words.

## Notes and limitations

* Everything is pure Python for readability; absolute times are slower than C++/Rust, but the
  ratios and trends are what the study is about.
* A road “closure” is modelled as 50× travel time (finite weight), not an edge deletion.
* The OSMnx loader was written against the documented OSMnx API; the conversion code is unit-tested
  with a mock graph, but the download step needs your internet connection and `osmnx` installed.
