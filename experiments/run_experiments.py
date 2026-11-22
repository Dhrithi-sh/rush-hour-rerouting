"""Run all experiments and write CSVs + figures into results/.

Examples
  python experiments/run_experiments.py --quick                  # ~1 min smoke run
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
from disruptions import MODES, BLOCK_FACTOR           # noqa: E402

COLORS = {"single": "#1f77b4", "cluster": "#d62728", "wave": "#2ca02c"}
LABELS = {"single": "Scattered closures", "cluster": "Accident zone",
          "wave": "Congestion wave"}
N_CHECKS = 0   # number of repair==Dijkstra equality assertions performed


def pick_depot(g):
    """Node closest to the centroid of the map (the 'depot' / source)."""
    cx = sum(p[0] for p in g.xy) / g.n
    cy = sum(p[1] for p in g.xy) / g.n
    return min(range(g.n), key=lambda i: (g.xy[i][0] - cx) ** 2 + (g.xy[i][1] - cy) ** 2)


def run_phase(g, dyn, s, changes):
    """Apply `changes` [(u,v,new_w)] by repair, then time a full Dijkstra on the
    resulting graph; assert both give identical distances."""
    global N_CHECKS
    prev = list(dyn.dist)
    gc.collect()
    t0 = time.perf_counter()
    touched = 0
    for u, v, w in changes:
        touched += dyn.update_edge(u, v, w)
    t_rep = time.perf_counter() - t0
    t0 = time.perf_counter()
    ref = dijkstra(g, s)
    t_full = time.perf_counter() - t0
    assert ref == dyn.dist, "REPAIR MISMATCH vs Dijkstra"
    N_CHECKS += 1
    net = sum(1 for a, b in zip(prev, dyn.dist) if a != b)
    return t_rep, t_full, touched, net


def exp_main(g, s, sizes, trials, seed):
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    rows = []
    for mode, fn in MODES.items():
        for k in sizes:
            t_start = time.time()
            for t in range(trials):
                ch = fn(g, rng, k)
                block = [(u, v, new) for u, v, _, new in ch]
                clear = [(u, v, old) for u, v, old, _ in reversed(ch)]
                for phase, c in (("block", block), ("clear", clear)):
                    tr, tf, touched, net = run_phase(g, dyn, s, c)
                    rows.append(dict(mode=mode, size=k, edges=len(ch), trial=t,
                                     phase=phase, t_repair=tr, t_full=tf,
                                     touched=touched, net_changed=net))
            print(f"    {mode:8s} size {k:5d}: {time.time() - t_start:6.1f} s", flush=True)
        print(f"  main experiment: finished mode '{mode}'", flush=True)
    return pd.DataFrame(rows)


def tree_edge_block(g, dyn, rng):
    """Block the shortest-path-tree edge into a random node (an edge that is guaranteed to
    matter), so the scaling experiment does not measure no-op updates."""
    while True:
        v = rng.randrange(g.n)
        if v == dyn.s:
            continue
        for u, w in g.inn[v].items():
            if dyn.dist[u] + w == dyn.dist[v]:
                return [(u, v, w, w * BLOCK_FACTOR)]


def exp_scaling(dims, trials, seed):
    rng = random.Random(seed)
    rows = []
    for d in dims:
        g = make_synthetic_city(d, d, seed=seed)
        s = pick_depot(g)
        dyn = DynamicSSSP(g, s)
        for label in ("single tree-edge closure", "zone of 20 edges"):
            for t in range(trials):
                ch = tree_edge_block(g, dyn, rng) if label.startswith("single") \
                    else MODES["cluster"](g, rng, 20)
                tr, tf, touched, net = run_phase(g, dyn, s, [(u, v, n) for u, v, _, n in ch])
                run_phase(g, dyn, s, [(u, v, o) for u, v, o, _ in reversed(ch)])
                rows.append(dict(n=g.n, scenario=label, t_repair=tr, t_full=tf, net=net))
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
    for v in sample:
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
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    best = None
    for _ in range(tries):
        ch = MODES["cluster"](g, rng, k)
        before = list(dyn.dist)
        for u, v, _, n in ch:
            dyn.update_edge(u, v, n)
        after = list(dyn.dist)
        net = sum(a != b for a, b in zip(before, after))
        if best is None or net > best[0]:
            best = (net, before, after, ch)
        for u, v, o, _ in reversed(ch):
            dyn.update_edge(u, v, o)
    return best


# ---------------------------------------------------------------- plots
def summarise(df):
    d = df.copy()
    d["speedup"] = d["t_full"] / d["t_repair"]
    g = d.groupby(["mode", "phase", "size"])
    out = g.agg(speedup_med=("speedup", "median"),
                speedup_q25=("speedup", lambda x: x.quantile(.25)),
                speedup_q75=("speedup", lambda x: x.quantile(.75)),
                t_repair_ms=("t_repair", lambda x: x.median() * 1e3),
                t_full_ms=("t_full", lambda x: x.median() * 1e3),
                net_changed_med=("net_changed", "median"),
                net_changed_mean=("net_changed", "mean"),
                touched_med=("touched", "median"),
                trials=("trial", "count")).reset_index()
    return out


def crossover(summ, mode, phase="block"):
    """Edges-changed value at which median speedup crosses 1 (log-log interpolation)."""
    s = summ[(summ["mode"] == mode) & (summ["phase"] == phase)].sort_values("size")
    sizes, sp = s["size"].values, s["speedup_med"].values
    for i in range(1, len(sizes)):
        if sp[i - 1] >= 1 > sp[i]:
            x0, x1 = math.log(sizes[i - 1]), math.log(sizes[i])
            y0, y1 = math.log(sp[i - 1]), math.log(sp[i])
            return float(math.exp(x0 + (0 - y0) * (x1 - x0) / (y1 - y0)))
    return None


def style():
    plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight", "axes.grid": True,
                         "grid.alpha": .3, "axes.spines.top": False,
                         "axes.spines.right": False, "font.size": 10})


def fig_speedup(summ, path, n):
    fig, ax = plt.subplots(figsize=(6.4, 4))
    for mode in MODES:
        for phase, ls in (("block", "-"), ("clear", "--")):
            s = summ[(summ["mode"] == mode) & (summ["phase"] == phase)].sort_values("size")
            ax.plot(s["size"], s["speedup_med"], ls, marker="o", ms=3, color=COLORS[mode],
                    label=f"{LABELS[mode]} ({'blocking' if phase == 'block' else 'clearing'})")
            if phase == "block":
                ax.fill_between(s["size"], s["speedup_q25"], s["speedup_q75"],
                                color=COLORS[mode], alpha=.12)
    ax.axhline(1, color="k", lw=1)
    ax.text(ax.get_xlim()[0] * 1.1, 1.08, "break-even (repair = full recompute)", fontsize=8)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Disruption size (number of edges changed)")
    ax.set_ylabel("Speed-up  (t_Dijkstra / t_repair)")
    ax.set_title(f"Incremental repair vs. full Dijkstra  (n = {n:,} nodes)")
    ax.legend(fontsize=7, ncol=2, loc="upper right")
    fig.savefig(path); plt.close(fig)


def fig_runtime(summ, path):
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4), sharey=True)
    for ax, mode in zip(axes, MODES):
        s = summ[(summ["mode"] == mode) & (summ["phase"] == "block")].sort_values("size")
        ax.plot(s["size"], s["t_repair_ms"], "o-", ms=3, color=COLORS[mode], label="incremental repair")
        ax.plot(s["size"], s["t_full_ms"], "s--", ms=3, color="gray", label="full Dijkstra")
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_title(LABELS[mode])
        ax.set_xlabel("edges changed")
    axes[0].set_ylabel("median time per disruption (ms)")
    axes[0].legend(fontsize=8)
    fig.savefig(path); plt.close(fig)


def fig_affected(summ, path, n):
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for mode in MODES:
        s = summ[(summ["mode"] == mode) & (summ["phase"] == "block")].sort_values("size")
        ax.plot(s["size"], 100 * s["net_changed_mean"] / n, "o-", ms=3,
                color=COLORS[mode], label=LABELS[mode])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Disruption size (edges changed)")
    ax.set_ylabel("Mean % of nodes whose distance changed")
    ax.set_title("How much of the map is affected?")
    ax.legend()
    fig.savefig(path); plt.close(fig)


def fig_scaling(sc, path):
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, scen in zip(axes, sc["scenario"].unique()):
        s = sc[sc["scenario"] == scen].groupby("n").median(numeric_only=True).reset_index()
        ax.plot(s["n"], s["t_repair"] * 1e3, "o-", color="#d62728", label="incremental repair")
        ax.plot(s["n"], s["t_full"] * 1e3, "s--", color="gray", label="full Dijkstra")
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_title(scen)
        ax.set_xlabel("number of nodes n")
    axes[0].set_ylabel("median time (ms)"); axes[0].legend(fontsize=8)
    fig.savefig(path); plt.close(fig)


def fig_ripple(rp, path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    cols = {"local": "#1f77b4", "arterial": "#ff7f0e", "bridge": "#d62728"}
    for cls, grp in rp.groupby("cls"):
        ax.scatter(grp["subtree"], grp["affected"].clip(lower=.8), s=14, alpha=.7,
                   color=cols.get(cls, "k"), label=f"{cls} ({len(grp)})")
    mx = rp["subtree"].max()
    ax.plot([1, mx], [1, mx], "k--", lw=1, label="upper bound: y = x")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("shortest-path-tree subtree size below the edge")
    ax.set_ylabel("nodes whose distance changed")
    ax.set_title("Ripple size vs. subtree size"); ax.legend(fontsize=8)
    ax = axes[1]
    classes = [c for c in ("local", "arterial", "bridge") if c in set(rp["cls"])]
    data = [rp[rp["cls"] == c]["affected"].values for c in classes]
    ax.boxplot(data, tick_labels=[f"{c}\n(n={len(d)})" for c, d in zip(classes, data)], showfliers=True)
    ax.set_yscale("symlog", linthresh=1)
    ax.set_ylabel("nodes whose distance changed"); ax.set_title("Effect of blocking one tree edge, by road class")
    fig.savefig(path); plt.close(fig)


def fig_heatmap(g, s, case, path):
    net, before, after, ch = case
    xs = np.array([p[0] for p in g.xy]); ys = np.array([p[1] for p in g.xy])
    delta = np.array([(a - b) / 10 / 60 if a != INF and b != INF else 0
                      for a, b in zip(after, before)])          # minutes
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    ax.scatter(xs, ys, s=1, color="#d0d0d0", linewidths=0)
    mask = delta > 0
    sc = ax.scatter(xs[mask], ys[mask], c=delta[mask], s=3, cmap="plasma", linewidths=0)
    for u, v, _, _ in ch:
        ax.plot([g.xy[u][0], g.xy[v][0]], [g.xy[u][1], g.xy[v][1]], color="cyan", lw=1.4)
    ax.scatter([g.xy[s][0]], [g.xy[s][1]], marker="*", s=140, color="lime", edgecolor="k", zorder=5)
    ax.set_aspect("equal"); ax.grid(False)
    ax.set_title(f"Accident zone (80 blocked edges, cyan): {net:,} of {g.n:,} nodes re-routed\n"
                 "colour = added travel time from depot (★)", fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
    fig.colorbar(sc, ax=ax, shrink=.7, label="extra minutes")
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

    gc.disable()
    print("[1/4] main experiment", flush=True)
    df = exp_main(g, s, sizes, a.trials, a.seed)
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
    gc.enable()

    print("[4/4] figures", flush=True)
    fig_speedup(summ, os.path.join(a.out, "fig1_speedup_vs_size.png"), g.n)
    fig_runtime(summ, os.path.join(a.out, "fig2_runtime_vs_size.png"))
    fig_affected(summ, os.path.join(a.out, "fig3_affected_fraction.png"), g.n)
    fig_scaling(sc, os.path.join(a.out, "fig4_scaling_with_n.png"))
    fig_ripple(rp, os.path.join(a.out, "fig5_ripple.png"))
    case = heatmap_case(g, s, a.seed)
    fig_heatmap(g, s, case, os.path.join(a.out, "fig6_heatmap.png"))

    meta = dict(graph_source=source, n=g.n, m=m, depot=s, seed=a.seed, trials=a.trials,
                sizes=sizes, block_factor=BLOCK_FACTOR, equality_checks_passed=N_CHECKS,
                crossover={mode: crossover(summ, mode) for mode in MODES},
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
