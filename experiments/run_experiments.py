"""Run all experiments and write CSVs + figures into results/.

Examples
  python experiments/run_experiments.py --quick                  # smoke run (see README for timing)
  python experiments/run_experiments.py                          # full run, synthetic city
  python experiments/run_experiments.py --place "Piedmont, California, USA"   # real OSM city
"""
import argparse
import gc
import json
import math
import os
import platform
import random
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
import matplotlib                                     # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                       # noqa: E402
from graph import INF, make_synthetic_city, load_osm  # noqa: E402
from sssp import DynamicSSSP, dijkstra                # noqa: E402
from disruptions import MODES, TREE_MODES, BLOCK_FACTOR  # noqa: E402

COLORS = {"single": "#56B4E9", "cluster": "#CC79A7", "wave": "#E69F00", "tree": "#332288"}
LABELS = {"single": "Scattered closures", "cluster": "Accident zone",
          "wave": "Congestion wave", "tree": "Tree-edge closures"}
METHOD_COLORS = {"dijkstra": "#000000", "sequential": "#0072B2"}
METHOD_LABELS = {"dijkstra": "full Dijkstra", "sequential": "repair (edge by edge)"}
N_CHECKS = 0   # number of repair==Dijkstra equality assertions performed

# Timing policy: every operation is repeated until it has run for at least
# MIN_TOTAL seconds (between MIN_REPS and MAX_REPS runs); the per-trial value is
# the median of those runs. The graph and the distance array are restored to the
# exact pre-disruption state before every repeat.
MIN_TOTAL, MIN_REPS, MAX_REPS, FULL_REPS = 0.002, 3, 50, 3


def pick_depot(g):
    """Node closest to the centroid of the map (the 'depot' / source)."""
    cx = sum(p[0] for p in g.xy) / g.n
    cy = sum(p[1] for p in g.xy) / g.n
    return min(range(g.n), key=lambda i: (g.xy[i][0] - cx) ** 2 + (g.xy[i][1] - cy) ** 2)


def repair_sequential(dyn, changes):
    touched = 0
    for u, v, w in changes:
        touched += dyn.update_edge(u, v, w)
    return touched


METHODS = {"sequential": repair_sequential}


def generate(mode, g, rng, k, dyn):
    fn = MODES[mode]
    return fn(g, rng, k, dyn.s, dyn.dist) if mode in TREE_MODES else fn(g, rng, k)


def time_full(g, s, reps=FULL_REPS):
    """Median wall time of a from-scratch Dijkstra on the current graph, and its result."""
    times, ref = [], None
    for _ in range(reps):
        t0 = time.perf_counter()
        ref = dijkstra(g, s)
        times.append(time.perf_counter() - t0)
    return float(np.median(times)), ref


def measure_phase(g, dyn, s, changes, methods=("sequential",)):
    """Apply `changes` [(u, v, new_w)] with every repair method in `methods`.

    Each method starts from the same graph + distance state; each is repeated
    (see MIN_TOTAL/MIN_REPS/MAX_REPS) with an exact restore in between, and its
    result is asserted equal to a from-scratch Dijkstra. On return the graph and
    `dyn` are in the post-disruption state. Returns (t_full, {method: stats}).
    """
    global N_CHECKS
    old_w = [(u, v, g.out[u][v]) for u, v, _ in changes]
    dist0 = list(dyn.dist)

    def restore():
        for u, v, w in reversed(old_w):
            g.set_weight(u, v, w)
        dyn.dist[:] = dist0

    gc.collect()
    t_full, ref = None, None
    out = {}
    for i, method in enumerate(methods):
        fn = METHODS[method]
        times, reps, touched = [], MIN_REPS, 0
        while True:
            t0 = time.perf_counter()
            touched = fn(dyn, changes)
            times.append(time.perf_counter() - t0)
            if ref is None:                         # graph is now in the post state
                t_full, ref = time_full(g, s)
            assert dyn.dist == ref, f"REPAIR MISMATCH vs Dijkstra ({method})"
            N_CHECKS += 1
            if len(times) == 1:
                reps = max(MIN_REPS, min(MAX_REPS, math.ceil(MIN_TOTAL / max(times[0], 1e-9))))
            done = len(times) >= reps
            if done and i == len(methods) - 1:
                break                               # leave the post-disruption state
            restore()
            assert dyn.dist == dist0 and all(g.out[u][v] == w for u, v, w in old_w)
            if done:
                break
        out[method] = dict(t_repair=float(np.median(times)), reps=len(times), touched=touched)
    net = sum(1 for a, b in zip(dist0, dyn.dist) if a != b)
    for st in out.values():
        st["net_changed"] = net
    return t_full, out


def exp_main(g, s, modes, sizes, trials, seed, methods=("sequential",)):
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    rows = []
    for mode in modes:
        for k in sizes:
            t_start = time.time()
            for t in range(trials):
                ch = generate(mode, g, rng, k, dyn)
                block = [(u, v, new) for u, v, _, new in ch]
                clear = [(u, v, old) for u, v, old, _ in reversed(ch)]
                for phase, c in (("block", block), ("clear", clear)):
                    t_full, res = measure_phase(g, dyn, s, c, methods)
                    for method, st in res.items():
                        rows.append(dict(mode=mode, size=k, edges=len(ch), trial=t, phase=phase,
                                         method=method, t_repair=st["t_repair"], t_full=t_full,
                                         reps=st["reps"], touched=st["touched"],
                                         net_changed=st["net_changed"],
                                         effective=st["net_changed"] > 0))
            print(f"    {mode:8s} size {k:5d}: {time.time() - t_start:6.1f} s", flush=True)
        print(f"  main experiment: finished mode '{mode}'", flush=True)
    return pd.DataFrame(rows)


def exp_scaling(dims, trials, seed):
    rng = random.Random(seed)
    rows = []
    for d in dims:
        g = make_synthetic_city(d, d, seed=seed)
        s = pick_depot(g)
        dyn = DynamicSSSP(g, s)
        for label in ("single tree-edge closure", "zone of 20 edges"):
            for t in range(trials):
                ch = MODES["tree"](g, rng, 1, s, dyn.dist) if label.startswith("single") \
                    else MODES["cluster"](g, rng, 20)
                tf, res = measure_phase(g, dyn, s, [(u, v, n) for u, v, _, n in ch])
                measure_phase(g, dyn, s, [(u, v, o) for u, v, o, _ in reversed(ch)])
                st = res["sequential"]
                rows.append(dict(n=g.n, scenario=label, t_repair=st["t_repair"], t_full=tf,
                                 net=st["net_changed"]))
        print(f"  scaling: n={g.n}", flush=True)
    return pd.DataFrame(rows)


def exp_ripple(g, s, n_random, seed):
    """Block one shortest-path-tree edge at a time; record how many distances change."""
    global N_CHECKS
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    dist = dyn.dist
    parent = [-1] * g.n
    for x in range(g.n):
        if x == s:
            continue
        for y, w in g.inn[x].items():
            if dist[y] + w == dist[x]:
                parent[x] = y
                break
    size = [1] * g.n
    for x in sorted(range(g.n), key=lambda i: -dist[i]):
        if parent[x] >= 0:
            size[parent[x]] += size[x]
    tree_nodes = [x for x in range(g.n) if x != s]
    bridge_nodes = [x for x in tree_nodes if g.edge_class.get((parent[x], x)) == "bridge"]
    sample = set(rng.sample(tree_nodes, min(n_random, len(tree_nodes)))) | set(bridge_nodes)
    base = list(dist)
    rows = []
    for v in sorted(sample):
        u = parent[v]
        w = g.out[u][v]
        aff = dyn.update_edge(u, v, w * BLOCK_FACTOR)
        assert aff <= size[v], "affected set exceeds shortest-path-tree subtree"
        assert dijkstra(g, s) == dyn.dist
        dyn.update_edge(u, v, w)
        assert dyn.dist == base
        N_CHECKS += 2
        rows.append(dict(v=v, subtree=size[v], affected=aff,
                         cls=g.edge_class.get((u, v), "local"), depth=base[v]))
    return pd.DataFrame(rows)


def heatmap_case(g, s, seed, k=80, tries=40):
    global N_CHECKS
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    base = list(dyn.dist)
    best = None
    for _ in range(tries):
        ch = MODES["cluster"](g, rng, k)
        for u, v, _, n in ch:
            dyn.update_edge(u, v, n)
        assert dyn.dist == dijkstra(g, s), "REPAIR MISMATCH vs Dijkstra (heatmap)"
        after = list(dyn.dist)
        net = sum(a != b for a, b in zip(base, after))
        if best is None or net > best[0]:
            best = (net, base, after, ch)
        for u, v, o, _ in reversed(ch):
            dyn.update_edge(u, v, o)
        assert dyn.dist == base
        N_CHECKS += 2
    return best


# ---------------------------------------------------------------- analysis
def q25(x):
    return x.quantile(.25)


def q75(x):
    return x.quantile(.75)


def summarise(df):
    """Per (mode, phase, size, method): medians/IQRs over trials, for all trials and
    for effective trials only (at least one distance changed), plus the no-op fraction."""
    d = df.copy()
    d["speedup"] = d["t_full"] / d["t_repair"]
    d["t_repair_ms"] = d["t_repair"] * 1e3
    d["t_full_ms"] = d["t_full"] * 1e3
    keys = ["mode", "phase", "size", "method"]
    out = d.groupby(keys).agg(
        speedup_med=("speedup", "median"), speedup_q25=("speedup", q25),
        speedup_q75=("speedup", q75),
        t_repair_ms=("t_repair_ms", "median"), t_repair_ms_q25=("t_repair_ms", q25),
        t_repair_ms_q75=("t_repair_ms", q75),
        t_full_ms=("t_full_ms", "median"), t_full_ms_q25=("t_full_ms", q25),
        t_full_ms_q75=("t_full_ms", q75),
        net_changed_med=("net_changed", "median"), net_changed_mean=("net_changed", "mean"),
        touched_med=("touched", "median"),
        frac_noop=("effective", lambda e: 1 - e.mean()),
        trials=("trial", "count")).reset_index()
    eff = d[d["effective"]].groupby(keys).agg(
        n_effective=("trial", "count"),
        speedup_eff_med=("speedup", "median"), speedup_eff_q25=("speedup", q25),
        speedup_eff_q75=("speedup", q75),
        t_repair_eff_ms=("t_repair_ms", "median"), t_repair_eff_ms_q25=("t_repair_ms", q25),
        t_repair_eff_ms_q75=("t_repair_ms", q75)).reset_index()
    noop = d[~d["effective"]].groupby(keys).agg(
        speedup_noop_med=("speedup", "median"),
        t_repair_noop_ms=("t_repair_ms", "median")).reset_index()
    out = out.merge(eff, on=keys, how="left").merge(noop, on=keys, how="left")
    out["n_effective"] = out["n_effective"].fillna(0).astype(int)
    return out


def crossover(summ, mode, method="sequential", phase="block", col="speedup_med"):
    """Edges-changed value at which the median speed-up crosses 1 (log-log interpolation)."""
    s = summ[(summ["mode"] == mode) & (summ["phase"] == phase) & (summ["method"] == method)]
    s = s.dropna(subset=[col]).sort_values("size")
    sizes, sp = s["size"].values, s[col].values
    for i in range(1, len(sizes)):
        if sp[i - 1] >= 1 > sp[i]:
            x0, x1 = math.log(sizes[i - 1]), math.log(sizes[i])
            y0, y1 = math.log(sp[i - 1]), math.log(sp[i])
            return float(math.exp(x0 + (0 - y0) * (x1 - x0) / (y1 - y0)))
    return None


# ---------------------------------------------------------------- plots
def style():
    plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight", "axes.grid": True,
                         "grid.alpha": .3, "axes.spines.top": False,
                         "axes.spines.right": False, "font.size": 10})


def _sel(summ, mode, method, phase="block"):
    return summ[(summ["mode"] == mode) & (summ["phase"] == phase)
                & (summ["method"] == method)].sort_values("size")


def fig_speedup(summ, path, n, modes, methods):
    fig, axes = plt.subplots(1, len(modes), figsize=(3.2 * len(modes), 3.6), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, mode in zip(axes, modes):
        for method in methods:
            s = _sel(summ, mode, method)
            c = METHOD_COLORS[method]
            ax.plot(s["size"], s["speedup_med"], "-", marker="o", ms=3, color=c,
                    label=f"{METHOD_LABELS[method]}: all updates")
            ax.fill_between(s["size"], s["speedup_q25"], s["speedup_q75"], color=c, alpha=.12)
            e = s.dropna(subset=["speedup_eff_med"])
            ax.plot(e["size"], e["speedup_eff_med"], ":", marker="^", ms=3, color=c,
                    label=f"{METHOD_LABELS[method]}: effective only")
        ax.axhline(1, color="k", lw=1)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_title(LABELS[mode], fontsize=10)
        ax.set_xlabel("edges changed")
    axes[0].set_ylabel("speed-up  t_Dijkstra / t_repair  (×)")
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle(f"Repair vs. full Dijkstra when blocking roads (n = {n:,} nodes; "
                 "line = median, band = IQR; black line = break-even)", fontsize=10)
    fig.savefig(path); plt.close(fig)


def fig_runtime(summ, path, modes, methods):
    fig, axes = plt.subplots(1, len(modes), figsize=(3.2 * len(modes), 3.4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, mode in zip(axes, modes):
        for method in methods:
            s = _sel(summ, mode, method)
            c = METHOD_COLORS[method]
            ax.plot(s["size"], s["t_repair_ms"], "o-", ms=3, color=c,
                    label=f"{METHOD_LABELS[method]} (all)")
            ax.fill_between(s["size"], s["t_repair_ms_q25"], s["t_repair_ms_q75"], color=c, alpha=.12)
            e = s.dropna(subset=["t_repair_eff_ms"])
            ax.plot(e["size"], e["t_repair_eff_ms"], "^:", ms=3, color=c,
                    label=f"{METHOD_LABELS[method]} (effective)")
        s = _sel(summ, mode, methods[0])
        ax.plot(s["size"], s["t_full_ms"], "s--", ms=3, color=METHOD_COLORS["dijkstra"],
                label=METHOD_LABELS["dijkstra"])
        ax.fill_between(s["size"], s["t_full_ms_q25"], s["t_full_ms_q75"],
                        color=METHOD_COLORS["dijkstra"], alpha=.1)
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_title(LABELS[mode], fontsize=10)
        ax.set_xlabel("edges changed")
    axes[0].set_ylabel("median time per disruption (ms)")
    axes[0].legend(fontsize=7)
    fig.savefig(path); plt.close(fig)


def fig_affected(summ, path, n, modes):
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for mode in modes:
        s = _sel(summ, mode, "sequential")
        ax.plot(s["size"], 100 * s["net_changed_mean"] / n, "o-", ms=3,
                color=COLORS[mode], label=LABELS[mode])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("disruption size (edges changed)")
    ax.set_ylabel("mean % of nodes whose distance changed")
    ax.set_title("How much of the map is affected?")
    ax.legend()
    fig.savefig(path); plt.close(fig)


def fig_scaling(sc, path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, scen in zip(axes, sc["scenario"].unique()):
        s = sc[sc["scenario"] == scen].groupby("n").median(numeric_only=True).reset_index()
        ax.plot(s["n"], s["t_repair"] * 1e3, "o-", color=METHOD_COLORS["sequential"],
                label=METHOD_LABELS["sequential"])
        ax.plot(s["n"], s["t_full"] * 1e3, "s--", color=METHOD_COLORS["dijkstra"],
                label=METHOD_LABELS["dijkstra"])
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_title(scen)
        ax.set_xlabel("number of nodes n")
    axes[0].set_ylabel("median time (ms)"); axes[0].legend(fontsize=8)
    fig.savefig(path); plt.close(fig)


def fig_ripple(rp, path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    cols = {"local": "#56B4E9", "arterial": "#E69F00", "bridge": "#D55E00"}
    for cls, grp in rp.groupby("cls"):
        ax.scatter(grp["subtree"], grp["affected"].clip(lower=.8), s=14, alpha=.7,
                   color=cols.get(cls, "k"), label=f"{cls} ({len(grp)})")
    mx = rp["subtree"].max()
    ax.plot([1, mx], [1, mx], "k--", lw=1, label="upper bound: y = x")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("shortest-path-tree subtree size below the edge (nodes)")
    ax.set_ylabel("nodes whose distance changed")
    ax.set_title("Ripple size vs. subtree size"); ax.legend(fontsize=8)
    ax = axes[1]
    classes = [c for c in ("local", "arterial", "bridge") if c in set(rp["cls"])]
    data = [rp[rp["cls"] == c]["affected"].values for c in classes]
    # No `labels=`/`tick_labels=` keyword: its name changed in matplotlib 3.9, so set
    # the tick labels separately (works on every supported version).
    ax.boxplot(data, showfliers=True)
    ax.set_xticks(range(1, len(classes) + 1))
    ax.set_xticklabels([f"{c}\n(n={len(d)})" for c, d in zip(classes, data)])
    ax.set_yscale("symlog", linthresh=1)
    ax.set_ylabel("nodes whose distance changed")
    ax.set_title("Effect of blocking one tree edge, by road class")
    fig.savefig(path); plt.close(fig)


def fig_heatmap(g, s, case, path):
    net, before, after, ch = case
    xs = np.array([p[0] for p in g.xy]); ys = np.array([p[1] for p in g.xy])
    delta = np.array([(a - b) / 10 / 60 if a != INF and b != INF else 0
                      for a, b in zip(after, before)])          # minutes
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    ax.scatter(xs, ys, s=1, color="#d0d0d0", linewidths=0)
    mask = delta > 0
    sc = ax.scatter(xs[mask], ys[mask], c=delta[mask], s=3, cmap="viridis", linewidths=0)
    for u, v, _, _ in ch:
        ax.plot([g.xy[u][0], g.xy[v][0]], [g.xy[u][1], g.xy[v][1]], color="#D55E00", lw=1.4)
    ax.scatter([g.xy[s][0]], [g.xy[s][1]], marker="*", s=140, color="white", edgecolor="k", zorder=5)
    ax.set_aspect("equal"); ax.grid(False)
    ax.set_title(f"Accident zone ({len(ch)} blocked edges, red): {net:,} of {g.n:,} nodes re-routed\n"
                 "colour = added travel time from depot (★)", fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
    fig.colorbar(sc, ax=ax, shrink=.7, label="extra travel time (minutes)")
    fig.savefig(path); plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--place", help="OSM place name, e.g. 'Piedmont, California, USA'")
    ap.add_argument("--width", type=int, default=140)
    ap.add_argument("--height", type=int, default=140)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--trials", type=int, default=15)
    ap.add_argument("--sizes", type=int, nargs="+",
                    default=[1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000])
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    a = ap.parse_args()
    if a.quick:
        a.width = a.height = 60
        a.trials = 5
        a.sizes = [1, 5, 20, 100, 400]
    os.makedirs(a.out, exist_ok=True)
    style()

    t0 = time.time()
    if a.place:
        print(f"Loading OSM graph for '{a.place}' ...", flush=True)
        g = load_osm(a.place, os.path.join(ROOT, "data"))
        source = f"OpenStreetMap: {a.place}"
    else:
        g = make_synthetic_city(a.width, a.height, seed=a.seed)
        source = f"Synthetic city ({a.width}x{a.height} perturbed grid, arterials, one-way streets, river with 4 bridges)"
    s = pick_depot(g)
    m = g.m
    print(f"Graph: {g.n:,} nodes, {m:,} directed edges; depot = node {s}", flush=True)
    sizes = [k for k in a.sizes if k <= m // 4]
    modes = list(MODES)
    methods = list(METHODS)

    gc.disable()
    print("[1/4] main experiment", flush=True)
    df = exp_main(g, s, modes, sizes, a.trials, a.seed, methods)
    df.to_csv(os.path.join(a.out, "raw_main.csv"), index=False)
    summ = summarise(df)
    summ.to_csv(os.path.join(a.out, "summary_main.csv"), index=False)

    print("[2/4] scaling experiment (synthetic cities of growing size)", flush=True)
    dims = [30, 50, 80, 110, 140] if not a.quick else [20, 35, 50]
    sc = exp_scaling(dims, max(5, a.trials), a.seed)
    sc.to_csv(os.path.join(a.out, "raw_scaling.csv"), index=False)

    print("[3/4] ripple experiment", flush=True)
    rp = exp_ripple(g, s, 300 if not a.quick else 80, a.seed)
    rp.to_csv(os.path.join(a.out, "raw_ripple.csv"), index=False)
    case = heatmap_case(g, s, a.seed)
    gc.enable()

    print("[4/4] figures", flush=True)
    fig_speedup(summ, os.path.join(a.out, "fig1_speedup_vs_size.png"), g.n, modes, methods)
    fig_runtime(summ, os.path.join(a.out, "fig2_runtime_vs_size.png"), modes, methods)
    fig_affected(summ, os.path.join(a.out, "fig3_affected_fraction.png"), g.n, modes)
    fig_scaling(sc, os.path.join(a.out, "fig4_scaling_with_n.png"))
    fig_ripple(rp, os.path.join(a.out, "fig5_ripple.png"))
    fig_heatmap(g, s, case, os.path.join(a.out, "fig6_heatmap.png"))

    meta = dict(graph_source=source, n=g.n, m=m, depot=s, seed=a.seed, trials=a.trials,
                sizes=sizes, modes=modes, methods=methods, block_factor=BLOCK_FACTOR,
                timing=dict(min_total_s=MIN_TOTAL, min_reps=MIN_REPS, max_reps=MAX_REPS,
                            full_reps=FULL_REPS),
                equality_checks_passed=N_CHECKS,
                crossover={col: {method: {mode: crossover(summ, mode, method, col=col)
                                          for mode in modes} for method in methods}
                           for col in ("speedup_med", "speedup_eff_med")},
                python=platform.python_version(), platform=platform.platform(),
                runtime_seconds=round(time.time() - t0, 1),
                heatmap_net_changed=case[0],
                ripple=dict(n=len(rp), max_affected=int(rp["affected"].max()),
                            median_affected=float(rp["affected"].median()),
                            frac_zero=float((rp["affected"] == 0).mean()),
                            median_subtree=float(rp["subtree"].median())))
    with open(os.path.join(a.out, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Done in {meta['runtime_seconds']} s; {N_CHECKS} repair==Dijkstra checks passed.")
    print(f"Results written to {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
