# Improvement plan (working checklist)

Baseline: 5 unittest tests pass (2.5 s); `run_all.py --quick` = 17 s wall (9 s experiments)
on Windows / Python 3.11. Commit after every phase, tests green each time.

## Phase 1: bugs and measurement
- [x] `fig_ripple`: version-independent box-plot labels (`set_xticks`), realistic minimum pins
- [x] `run_all.py --out` also forwarded to `build_report.py` (was ignored)
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
- [x] Sets vs generation-stamped arrays micro-benchmark; adopted (≈6% faster in the full run)

## Phase 3: real data
- [x] osmnx 1.x/2.x compatible loader (`src/rush_hour/osm.py`), offline .graphml reading, `scripts/fetch_cities.py`
- [x] `--graph-file`, `--compare-graphs`; cross-graph experiment, fig9, graph-stats table
- [x] Two real cities: Salt Lake City (grid-like US, 5.5k nodes) and Bologna (irregular European, 5.5k nodes)

## Phase 4: engineering
- [x] `pyproject.toml`, `src/rush_hour/`, no `sys.path` hacks, pytest
- [x] hypothesis property tests (single + batch, inc/dec/delete, dist + parent, path_to, LPA*)
- [x] Type hints/docstrings, ruff config (clean), GitHub Actions (lint + tests + `run_all.py --quick`,
      latest and minimum dependency versions)
- [x] `meta.json` with git commit, code-dirty flag and full CLI args (project-relative paths)

## Phase 5: presentation (scoped down on request)
- [x] Okabe-Ito palette, one colour per method everywhere, units on axes
- [ ] Animated GIF / interactive demo (skipped on request)
- [x] Report: batch repair + proof, effective/no-op, fleet, LPA*, real cities, threats to validity
- [x] README rewrite; final full run; min-versions venv check (found and fixed a matplotlib 3.7 bug)

## Still open
- [ ] PDF of the report (needs LibreOffice, or export the .docx manually)
- [ ] Team names / course / date placeholders in the report (team's job)
- [ ] CI has not run yet on GitHub (workflow added; check the Actions tab after the push)
