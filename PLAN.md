# Improvement plan (working checklist)

Baseline: 5 unittest tests pass (2.5 s); `run_all.py --quick` = 17 s wall (9 s experiments)
on Windows / Python 3.11. Commit after every phase, tests green each time.

## Phase 1: bugs and measurement
- [x] `fig_ripple`: version-independent box-plot labels (`set_xticks`), realistic minimum pins
- [x] `run_all.py --out` also forwarded to `build_report.py` (currently ignored)
- [x] Every experiment that repairs (incl. heatmap) asserts repair == Dijkstra
- [x] Effective vs no-op split in raw/summary CSVs (+ no-op fraction); new `tree` disruption mode
- [x] Repeated timing (adaptive reps, medians + IQR), state restored and asserted between reps
- [x] Crossover for all trials and effective-only; fig1/fig2, abstract, conclusions updated
- [x] Measure `--quick` time and state it consistently

## Phase 2: algorithms
- [x] Parent array maintained by every repair path; `path_to(t)`
- [x] `update_edges(changes)` batch repair (one affected-set sweep + one Dijkstra), proof
- [x] True deletions (weight = inf) in `Graph.set_weight` and both repair paths; `--closure {factor,delete}`
- [x] Fleet experiment (K destinations: routes changed, minutes gained, stranded)
- [x] LPA* module + tests; point-to-point comparison vs A*/Dijkstra/repair
- [x] Sets vs generation-stamped arrays micro-benchmark; adopt only if faster

## Phase 3: real data
- [x] osmnx 1.x/2.x compatible loader (`src/osm.py`), graph stats (`src/stats.py`), `scripts/fetch_cities.py`; `--graph-file` flag + cross-graph experiment NOT wired yet
- [ ] Two real cities (grid-like US + irregular Indian/European), cross-graph figure, graph-stats table

## Phase 4: engineering
- [ ] `pyproject.toml`, `src/rush_hour/`, no `sys.path` hacks, pytest
- [ ] hypothesis property tests (single + batch, inc/dec/delete, dist + parent), disruption & `path_to` tests
- [ ] Type hints/docstrings, ruff config, GitHub Actions (tests + `run_all.py --quick`)
- [ ] `meta.json` with git commit + full CLI args

## Phase 5: presentation
- [ ] Okabe-Ito palette, one colour per method everywhere, units on axes
- [ ] Animated GIF of a closure + rerouting generated into `results/`
- [ ] Report: batch repair + proof, effective/no-op, fleet, LPA*, real cities, threats to validity
- [ ] README rewrite; final full run; min-versions venv check
