"""Structural statistics of a road graph (for the cross-graph comparison table)."""
from collections import deque


def bfs_hops(g, s):
    """Hop distance from s to every node along out-edges (-1 if unreachable)."""
    hops = [-1] * g.n
    hops[s] = 0
    q = deque([s])
    while q:
        x = q.popleft()
        for z in g.out[x]:
            if hops[z] < 0:
                hops[z] = hops[x] + 1
                q.append(z)
    return hops


def hop_diameter_lower_bound(g, start=0, sweeps=6):
    """Lower bound on the directed hop diameter by repeated BFS sweeps: start
    anywhere, jump to the farthest node found, repeat. Exact all-pairs BFS would
    cost n * (n + m) steps, which is too slow in pure Python for 20k-node graphs;
    on road networks the sweep bound is usually tight or nearly so."""
    best, x = 0, start
    for _ in range(sweeps):
        hops = bfs_hops(g, x)
        far = max(range(g.n), key=lambda i: hops[i])
        if hops[far] <= best and _ > 0:
            break
        best, x = max(best, hops[far]), far
    return best


def oneway_fraction(g):
    """Fraction of directed edges (u, v) whose reverse (v, u) does not exist."""
    m = g.m
    if m == 0:
        return 0.0
    return sum(1 for u in range(g.n) for v in g.out[u] if u not in g.out[v]) / m


def graph_stats(g, name, source=""):
    """Dictionary with n, m, average out-degree, hop-diameter lower bound and
    the fraction of one-way edges."""
    return dict(graph=name, source=source, n=g.n, m=g.m, avg_out_degree=g.m / g.n,
                hop_diameter=hop_diameter_lower_bound(g), oneway_frac=oneway_fraction(g))
