"""Run all experiments and write CSVs + figures into results/.

Examples
  python experiments/run_experiments.py --quick                  # smoke run (see README for timing)
  python experiments/run_experiments.py                          # full run, synthetic city
  python experiments/run_experiments.py --closure delete         # closures delete the road
  python experiments/run_experiments.py --place "Piedmont, California, USA"   # real OSM city
"""
import argparse
import gc
import json
import math
import os
import platform
import random
import statistics
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
import plots                                                       # noqa: E402
from graph import INF, make_synthetic_city, load_osm               # noqa: E402
from sssp import DynamicSSSP, dijkstra, dijkstra_tree, check_tree  # noqa: E402
from disruptions import MODES, BLOCK_FACTOR, CLOSURES, blocked, generate  # noqa: E402
from lpa import LPAStar, astar, dijkstra_to, straight_line_heuristic      # noqa: E402

N_CHECKS = 0   # number of repair==Dijkstra equality assertions performed

# Timing policy: every operation is repeated until it has run for at least
# MIN_TOTAL seconds (between MIN_REPS and MAX_REPS runs); the per-trial value is
# the median of those runs. Stateful methods are restored to the exact
# pre-disruption state (graph weights + distance/parent arrays) between repeats.
MIN_TOTAL, MIN_REPS, MAX_REPS = 0.002, 3, 50


def pick_depot(g):
    """Node closest to the centroid of the map (the 'depot' / source)."""
    cx = sum(p[0] for p in g.xy) / g.n
    cy = sum(p[1] for p in g.xy) / g.n
    return min(range(g.n), key=lambda i: (g.xy[i][0] - cx) ** 2 + (g.xy[i][1] - cy) ** 2)


def time_repeated(run, undo=None, check=None, keep_last=True, min_reps=MIN_REPS):
    """Time run() repeatedly (policy above). undo() must restore the state that
    run() started from; check(result) is called after every run, untimed. If
    keep_last, the state produced by the last run is kept. Returns
    (median seconds, number of runs, last result)."""
    times, reps, res = [], min_reps, None
    while True:
        t0 = time.perf_counter()
        res = run()
        times.append(time.perf_counter() - t0)
        if check:
            check(res)
        if len(times) == 1:
            reps = max(min_reps, min(MAX_REPS, math.ceil(MIN_TOTAL / max(times[0], 1e-9))))
        if len(times) >= reps:
            break
        if undo:
            undo()
    if undo and not keep_last:
        undo()
    return float(statistics.median(times)), len(times), res


def apply_weights(g, changes):
    """Apply [(u, v, w)] to g; return the undo list [(u, v, old_w)]."""
    old = [(u, v, g.weight(u, v)) for u, v, _ in changes]
    for u, v, w in changes:
        g.set_weight(u, v, w)
    return old


def revert_weights(g, old):
    for u, v, w in reversed(old):
        g.set_weight(u, v, w)


# ---------------------------------------------------------------- repair methods
def repair_sequential(dyn, changes):
    touched = 0
    for u, v, w in changes:
        touched += dyn.update_edge(u, v, w)
    return touched


def repair_batch(dyn, changes):
    return dyn.update_edges(changes)


METHODS = {"sequential": repair_sequential, "batch": repair_batch}


def measure_phase(g, dyn, changes, methods=("sequential", "batch")):
    """Apply `changes` [(u, v, new_w)] with every repair method in `methods`.

    Full Dijkstra (dist + parent) is timed on the post-change graph first. Every
    method then starts from the same graph + dist + parent state, is repeated with
    an exact restore in between, and after every run its distances are asserted
    equal to Dijkstra's (and its parent array checked once). On return the graph
    and `dyn` are in the post-disruption state. Returns (t_full, {method: stats}).
    """
    global N_CHECKS
    s = dyn.s
    gc.collect()
    old = apply_weights(g, changes)
    t_full, _, (ref, _) = time_repeated(lambda: dijkstra_tree(g, s), min_reps=3)
    revert_weights(g, old)
    snap = dyn.snapshot()

    def undo():
        revert_weights(g, old)
        dyn.restore(snap)

    out = {}
    for i, method in enumerate(methods):
        fn = METHODS[method]
        first = [True]

        def check(_):
            global N_CHECKS
            assert dyn.dist == ref, f"REPAIR MISMATCH vs Dijkstra ({method})"
            if first[0]:
                check_tree(g, s, dyn.dist, dyn.parent)
                first[0] = False
            N_CHECKS += 1

        last = i == len(methods) - 1
        t, reps, touched = time_repeated(lambda: fn(dyn, changes), undo, check, keep_last=last)
        out[method] = dict(t_repair=t, reps=reps, touched=touched)
        if not last:
            assert dyn.dist == snap[0], "state not restored between methods"
    net = sum(1 for a, b in zip(snap[0], dyn.dist) if a != b)
    stranded = sum(1 for a, b in zip(snap[0], dyn.dist) if a != INF and b == INF)
    for st in out.values():
        st["net_changed"], st["stranded"] = net, stranded
    return t_full, out


# ---------------------------------------------------------------- experiments
def exp_main(g, s, modes, sizes, trials, seed, methods, closure):
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    rows = []
    for mode in modes:
        for k in sizes:
            t_start = time.time()
            for t in range(trials):
                ch = generate(mode, g, rng, k, dyn.parent, closure)
                block = [(u, v, new) for u, v, _, new in ch]
                clear = [(u, v, old) for u, v, old, _ in reversed(ch)]
                for phase, c in (("block", block), ("clear", clear)):
                    t_full, res = measure_phase(g, dyn, c, methods)
                    for method, st in res.items():
                        rows.append(dict(mode=mode, size=k, edges=len(ch), trial=t, phase=phase,
                                         method=method, t_repair=st["t_repair"], t_full=t_full,
                                         reps=st["reps"], touched=st["touched"],
                                         net_changed=st["net_changed"], stranded=st["stranded"],
                                         effective=st["net_changed"] > 0))
            print(f"    {mode:8s} size {k:5d}: {time.time() - t_start:6.1f} s", flush=True)
    return pd.DataFrame(rows)


def exp_scaling(dims, trials, seed, methods, closure):
    rng = random.Random(seed)
    rows = []
    for d in dims:
        g = make_synthetic_city(d, d, seed=seed)
        s = pick_depot(g)
        dyn = DynamicSSSP(g, s)
        for label, mode, k in (("single tree-edge closure", "tree", 1),
                               ("zone of 20 edges", "cluster", 20)):
            for t in range(trials):
                ch = generate(mode, g, rng, k, dyn.parent, closure)
                tf, res = measure_phase(g, dyn, [(u, v, n) for u, v, _, n in ch], methods)
                measure_phase(g, dyn, [(u, v, o) for u, v, o, _ in reversed(ch)], methods)
                for method, st in res.items():
                    rows.append(dict(n=g.n, scenario=label, method=method, trial=t,
                                     t_repair=st["t_repair"], t_full=tf, net=st["net_changed"]))
        print(f"  scaling: n={g.n}", flush=True)
    return pd.DataFrame(rows)


def exp_ripple(g, s, n_random, seed, closure):
    """Block one shortest-path-tree edge at a time; record how many distances change."""
    global N_CHECKS
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    parent, dist = list(dyn.parent), list(dyn.dist)
    size = [1] * g.n
    for x in sorted(range(g.n), key=lambda i: -dist[i]):
        if parent[x] >= 0:
            size[parent[x]] += size[x]
    tree_nodes = [x for x in range(g.n) if parent[x] >= 0]
    bridge_nodes = [x for x in tree_nodes if g.edge_class.get((parent[x], x)) == "bridge"]
    sample = set(rng.sample(tree_nodes, min(n_random, len(tree_nodes)))) | set(bridge_nodes)
    rows = []
    for v in sorted(sample):
        u = parent[v]
        w = g.out[u][v]
        aff = dyn.update_edge(u, v, blocked(w, closure))
        assert aff <= size[v], "affected set exceeds shortest-path-tree subtree"
        assert dijkstra(g, s) == dyn.dist
        check_tree(g, s, dyn.dist, dyn.parent)
        stranded = sum(1 for x in range(g.n) if dyn.dist[x] == INF)
        dyn.update_edge(u, v, w)
        assert dyn.dist == dist
        N_CHECKS += 2
        rows.append(dict(v=v, subtree=size[v], affected=aff, stranded=stranded,
                         cls=g.edge_class.get((u, v), "local"), depth=dist[v]))
    return pd.DataFrame(rows)


def heatmap_case(g, s, seed, closure, k=80, tries=40):
    """Worst of `tries` random accident zones of k edges (most nodes re-routed)."""
    global N_CHECKS
    rng = random.Random(seed)
    dyn = DynamicSSSP(g, s)
    base = list(dyn.dist)
    best = None
    for _ in range(tries):
        ch = MODES["cluster"](g, rng, k, closure)
        dyn.update_edges([(u, v, n) for u, v, _, n in ch])
        assert dyn.dist == dijkstra(g, s), "REPAIR MISMATCH vs Dijkstra (heatmap)"
        after = list(dyn.dist)
        net = sum(a != b for a, b in zip(base, after))
        if best is None or net > best[0]:
            best = (net, base, after, ch)
        dyn.update_edges([(u, v, o) for u, v, o, _ in ch])
        assert dyn.dist == base
        N_CHECKS += 2
    return best


def exp_fleet(g, s, n_vehicles, sizes, trials, seed, closure):
    """Delivery fleet: K vehicles leave the depot for K destinations. After each
    accident zone (batch repair), count whose route changed and the delay."""
    global N_CHECKS
    rng = random.Random(seed + 101)
    dyn = DynamicSSSP(g, s)
    dests = rng.sample([x for x in range(g.n) if x != s and dyn.dist[x] < INF], n_vehicles)
    rows = []
    for placement in ("anywhere", "on a route"):
        for k in sizes:
            for t in range(trials):
                if placement == "anywhere":
                    ch = MODES["cluster"](g, rng, k, closure)
                else:   # centre the accident on a random node of a random vehicle's route
                    route = dyn.path_to(rng.choice(dests))
                    centre = rng.choice(route[1:])
                    ch = _cluster_at(g, centre, k, closure)
                closed = {(u, v) for u, v, _, _ in ch}
                before = {d: (dyn.dist[d], dyn.path_to(d)) for d in dests}
                t_full, res = measure_phase(g, dyn, [(u, v, n) for u, v, _, n in ch], ("batch",))
                changed = delayed = stranded = used_closed = no_detour = 0
                extra = []
                for d in dests:
                    d0, p0 = before[d]
                    d1, p1 = dyn.dist[d], dyn.path_to(d)
                    used_closed += any((a, b) in closed for a, b in zip(p0, p0[1:]))
                    changed += p1 != p0
                    if d1 == INF:
                        stranded += 1
                    elif d1 > d0:
                        delayed += 1
                        no_detour += p1 == p0                  # slower, but still the best route
                        extra.append((d1 - d0) / 600)            # deciseconds -> minutes
                rows.append(dict(placement=placement, size=k, trial=t, vehicles=n_vehicles,
                                 used_closed=used_closed, routes_changed=changed, delayed=delayed,
                                 stranded=stranded, delayed_same_route=no_detour,
                                 extra_min_total=sum(extra),
                                 extra_min_mean=float(np.mean(extra)) if extra else 0.0,
                                 extra_min_max=max(extra) if extra else 0.0,
                                 t_repair=res["batch"]["t_repair"], t_full=t_full,
                                 net_changed=res["batch"]["net_changed"]))
                dyn.update_edges([(u, v, o) for u, v, o, _ in ch])
                assert dyn.dist == dijkstra(g, s)
                N_CHECKS += 1
        print(f"  fleet: placement '{placement}' done", flush=True)
    return pd.DataFrame(rows)


def _cluster_at(g, centre, k, closure):
    from disruptions import _bfs_edges
    return [(u, v, g.out[u][v], blocked(g.out[u][v], closure))
            for (u, v), _ in _bfs_edges(g, centre, k)]


P2P_METHODS = ["full Dijkstra", "Dijkstra to t", "A*", "batch repair", "LPA*"]


def exp_p2p(g, s, n_pairs, seed, closure):
    """Point-to-point rerouting s -> t: the route's own roads are blocked.
    Compares recomputation (full / early-exit Dijkstra, A*) with incremental
    repair of the whole tree (batch) and LPA* (single target)."""
    global N_CHECKS
    rng = random.Random(seed + 202)
    base_dist = dijkstra(g, s)
    far = sorted((x for x in range(g.n) if base_dist[x] < INF), key=lambda x: base_dist[x])
    targets = rng.sample(far[len(far) // 2:], n_pairs)      # destinations in the farther half
    rows = []
    for pi, t in enumerate(targets):
        g_fs, g_dyn, g_lpa = g.copy(), g.copy(), g.copy()
        h = straight_line_heuristic(g, t)
        dyn = DynamicSSSP(g_dyn, s)
        lpa = LPAStar(g_lpa, s, t, h)
        for scen in ("1 road on the route", "3 roads on the route", "20-edge zone on the route"):
            route = dyn.path_to(t)
            hops = list(zip(route, route[1:]))
            if scen.startswith("1 "):
                edges = rng.sample(hops, 1)
                ch = [(u, v, g_dyn.out[u][v], blocked(g_dyn.out[u][v], closure)) for u, v in edges]
            elif scen.startswith("3 "):
                edges = rng.sample(hops, min(3, len(hops)))
                ch = [(u, v, g_dyn.out[u][v], blocked(g_dyn.out[u][v], closure)) for u, v in edges]
            else:
                ch = _cluster_at(g_dyn, rng.choice(route[1:]), 20, closure)
            for phase, c in (("block", [(u, v, n) for u, v, _, n in ch]),
                             ("clear", [(u, v, o) for u, v, o, _ in ch])):
                apply_weights(g_fs, c)          # the from-scratch methods' graph follows along
                ref = dijkstra(g_fs, s)[t]
                rec = {}
                rec["full Dijkstra"] = time_repeated(lambda: dijkstra_tree(g_fs, s))[0]
                rec["Dijkstra to t"] = time_repeated(lambda: dijkstra_to(g_fs, s, t),
                                                     check=lambda r: _eq(r, ref))[0]
                rec["A*"] = time_repeated(lambda: astar(g_fs, s, t, h), check=lambda r: _eq(r, ref))[0]
                for name, obj, gg, run, val in (
                        ("batch repair", dyn, g_dyn, lambda: dyn.update_edges(c), lambda: dyn.dist[t]),
                        ("LPA*", lpa, g_lpa, lambda: lpa.update_edges(c), lambda: lpa.distance())):
                    snap, old_w = obj.snapshot(), [(u, v, gg.weight(u, v)) for u, v, _ in c]

                    def undo(obj=obj, snap=snap, gg=gg, old_w=old_w):
                        revert_weights(gg, old_w)
                        obj.restore(snap)
                    rec[name], _, work = time_repeated(run, undo, check=lambda _r, val=val: _eq(val(), ref))
                    if name == "LPA*":
                        rec["lpa_expansions"] = work
                for p in (dyn.path_to(t), lpa.path()):     # both report a valid s -> t route
                    _eq(sum(g_fs.out[a][b] for a, b in zip(p, p[1:])) if p else INF, ref)
                for mth in P2P_METHODS:
                    rows.append(dict(pair=pi, target=t, scenario=scen, phase=phase, method=mth,
                                     time=rec[mth], lpa_expansions=rec["lpa_expansions"],
                                     route_hops=len(hops)))
        print(f"  point-to-point: pair {pi + 1}/{n_pairs}", flush=True)
    return pd.DataFrame(rows)


def _eq(a, b):
    global N_CHECKS
    assert a == b, f"point-to-point mismatch: {a} != {b}"
    N_CHECKS += 1


def exp_closure(g, s, modes, sizes, trials, seed):
    """Same disruptions under both closure models: factor (x50) vs delete (INF)."""
    rows = []
    for closure in CLOSURES:
        rng = random.Random(seed + 303)      # identical disruption locations for both models
        dyn = DynamicSSSP(g, s)
        for mode in modes:
            for k in sizes:
                for t in range(trials):
                    ch = generate(mode, g, rng, k, dyn.parent, closure)
                    tf, res = measure_phase(g, dyn, [(u, v, n) for u, v, _, n in ch])
                    measure_phase(g, dyn, [(u, v, o) for u, v, o, _ in reversed(ch)])
                    for method, st in res.items():
                        rows.append(dict(closure=closure, mode=mode, size=k, trial=t, method=method,
                                         t_repair=st["t_repair"], t_full=tf,
                                         net_changed=st["net_changed"], stranded=st["stranded"]))
    return pd.DataFrame(rows)


class SetMarksSSSP(DynamicSSSP):
    """The previous per-edge increase repair, which allocated two Python set()
    objects per call. Kept only to benchmark against the generation-stamped
    arrays now used by DynamicSSSP."""

    def _increase(self, u, v, old_w):
        import heapq
        dist, parent, out, inn = self.dist, self.parent, self.g.out, self.g.inn
        if dist[u] == INF or dist[u] + old_w != dist[v]:
            return 0
        pop, push = heapq.heappop, heapq.heappush
        A, in_a, queued, heap = [], set(), {v}, [(dist[v], v)]
        while heap:
            d, x = pop(heap)
            support = -1
            for y, wy in inn[x].items():
                if y not in in_a and dist[y] + wy == d:
                    support = y
                    break
            if support >= 0:
                parent[x] = support
                continue
            A.append(x)
            in_a.add(x)
            for z, wz in out[x].items():
                if z not in queued and d + wz == dist[z]:
                    queued.add(z)
                    push(heap, (dist[z], z))
        heap = []
        for x in A:
            best, arg = INF, -1
            for y, wy in inn[x].items():
                if y not in in_a and dist[y] + wy < best:
                    best, arg = dist[y] + wy, y
            dist[x], parent[x] = best, arg
            if best < INF:
                heap.append((best, x))
        heapq.heapify(heap)
        while heap:
            d, x = pop(heap)
            if d > dist[x]:
                continue
            for z, wz in out[x].items():
                if z in in_a and d + wz < dist[z]:
                    dist[z], parent[z] = d + wz, x
                    push(heap, (d + wz, z))
        return len(A)


def exp_marks(g, s, n_edges, seed):
    """Micro-benchmark: set() marks vs generation-stamped arrays, on single
    shortest-path-tree closures (x50), interleaving the two in random order."""
    global N_CHECKS
    rng = random.Random(seed + 404)
    impls = {"sets": SetMarksSSSP(g, s), "arrays": DynamicSSSP(g, s)}
    base, parent = list(impls["arrays"].dist), list(impls["arrays"].parent)
    heads = [x for x in range(g.n) if parent[x] >= 0]
    rows = []
    for v in rng.sample(heads, min(n_edges, len(heads))):
        u, w = parent[v], g.out[parent[v]][v]
        order = list(impls)
        rng.shuffle(order)
        rec = {}
        for name in order:
            dyn = impls[name]

            def run(dyn=dyn):
                a = dyn.update_edge(u, v, w * BLOCK_FACTOR)
                dyn.update_edge(u, v, w)                    # clear again: state is restored
                return a
            t, _, aff = time_repeated(run, check=lambda _r, dyn=dyn: _same(dyn.dist, base))
            rec[name], rec["affected"] = t, aff
        rows.append(dict(v=v, affected=rec["affected"], t_sets=rec["sets"], t_arrays=rec["arrays"]))
    return pd.DataFrame(rows)


def _same(a, b):
    global N_CHECKS
    assert a == b
    N_CHECKS += 1


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
        stranded_mean=("stranded", "mean"),
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
    ap.add_argument("--closure", choices=CLOSURES, default="factor",
                    help="closure model for blocked roads: x50 weight (factor) or deletion (delete)")
    ap.add_argument("--fleet-size", type=int, default=50, help="vehicles in the fleet experiment")
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "results"))
    a = ap.parse_args()
    if a.quick:
        a.width = a.height = 60
        a.trials = 5
        a.sizes = [1, 5, 20, 100, 400]
        a.fleet_size = min(a.fleet_size, 20)
    os.makedirs(a.out, exist_ok=True)
    plots.style()

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
    print(f"Graph: {g.n:,} nodes, {m:,} directed edges; depot = node {s}; closure = {a.closure}", flush=True)
    sizes = [k for k in a.sizes if k <= m // 4]
    modes = list(MODES)
    methods = list(METHODS)
    out = lambda name: os.path.join(a.out, name)                     # noqa: E731

    gc.disable()
    print("[1/8] main experiment", flush=True)
    df = exp_main(g, s, modes, sizes, a.trials, a.seed, methods, a.closure)
    df.to_csv(out("raw_main.csv"), index=False)
    summ = summarise(df)
    summ.to_csv(out("summary_main.csv"), index=False)

    print("[2/8] scaling experiment (synthetic cities of growing size)", flush=True)
    dims = [30, 50, 80, 110, 140] if not a.quick else [20, 35, 50]
    sc = exp_scaling(dims, max(5, a.trials), a.seed, methods, a.closure)
    sc.to_csv(out("raw_scaling.csv"), index=False)

    print("[3/8] ripple experiment", flush=True)
    rp = exp_ripple(g, s, 300 if not a.quick else 80, a.seed, a.closure)
    rp.to_csv(out("raw_ripple.csv"), index=False)
    case = heatmap_case(g, s, a.seed, a.closure)

    print("[4/8] fleet rerouting experiment", flush=True)
    fl = exp_fleet(g, s, a.fleet_size, [10, 40, 160] if not a.quick else [10, 40],
                   a.trials, a.seed, a.closure)
    fl.to_csv(out("raw_fleet.csv"), index=False)

    print("[5/8] point-to-point experiment (LPA*)", flush=True)
    pp = exp_p2p(g, s, a.trials, a.seed, a.closure)
    pp.to_csv(out("raw_p2p.csv"), index=False)

    print("[6/8] closure model comparison (factor vs delete)", flush=True)
    cl = exp_closure(g, s, ["tree", "cluster"], [1, 10, 100] if not a.quick else [1, 10],
                     max(5, a.trials // 2), a.seed)
    cl.to_csv(out("raw_closure.csv"), index=False)

    print("[7/8] set() vs array marks micro-benchmark", flush=True)
    mk = exp_marks(g, s, 300 if not a.quick else 60, a.seed)
    mk.to_csv(out("raw_marks.csv"), index=False)
    gc.enable()

    print("[8/8] figures", flush=True)
    plots.fig_speedup(summ, out("fig1_speedup_vs_size.png"), g.n, modes, methods)
    plots.fig_runtime(summ, out("fig2_runtime_vs_size.png"), modes, methods)
    plots.fig_affected(summ, out("fig3_affected_fraction.png"), g.n, modes)
    plots.fig_scaling(sc, out("fig4_scaling_with_n.png"), methods)
    plots.fig_ripple(rp, out("fig5_ripple.png"))
    plots.fig_heatmap(g, s, case, out("fig6_heatmap.png"))
    plots.fig_fleet(fl, out("fig7_fleet.png"))
    plots.fig_p2p(pp, out("fig8_point_to_point.png"), P2P_METHODS)

    big = mk[mk["affected"] >= 50]
    meta = dict(graph_source=source, n=g.n, m=m, depot=s, seed=a.seed, trials=a.trials,
                sizes=sizes, modes=modes, methods=methods, closure=a.closure,
                block_factor=BLOCK_FACTOR, fleet_size=a.fleet_size,
                timing=dict(min_total_s=MIN_TOTAL, min_reps=MIN_REPS, max_reps=MAX_REPS,
                            full_reps=3),
                equality_checks_passed=N_CHECKS,
                crossover={col: {method: {mode: crossover(summ, mode, method, col=col)
                                          for mode in modes} for method in methods}
                           for col in ("speedup_med", "speedup_eff_med")},
                marks=dict(n=len(mk), median_us_sets=1e6 * float(mk["t_sets"].median()),
                           median_us_arrays=1e6 * float(mk["t_arrays"].median()),
                           total_ms_sets=1e3 * float(mk["t_sets"].sum()),
                           total_ms_arrays=1e3 * float(mk["t_arrays"].sum()),
                           n_big=len(big), big_threshold=50,
                           total_ms_sets_big=1e3 * float(big["t_sets"].sum()),
                           total_ms_arrays_big=1e3 * float(big["t_arrays"].sum())),
                python=platform.python_version(), platform=platform.platform(),
                runtime_seconds=round(time.time() - t0, 1),
                heatmap_net_changed=case[0],
                heatmap_stranded=sum(1 for b, c in zip(case[1], case[2]) if b < INF and c == INF),
                ripple=dict(n=len(rp), max_affected=int(rp["affected"].max()),
                            median_affected=float(rp["affected"].median()),
                            frac_zero=float((rp["affected"] == 0).mean()),
                            median_subtree=float(rp["subtree"].median())))
    with open(out("meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"Done in {meta['runtime_seconds']} s; {N_CHECKS} repair==Dijkstra checks passed.")
    print(f"Results written to {os.path.abspath(a.out)}")


if __name__ == "__main__":
    main()
