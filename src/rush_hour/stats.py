"""Structural statistics of a road graph (for the cross-graph comparison table)."""
from __future__ import annotations

from collections import deque

from .graph import Graph


def bfs_hops(g: Graph, s: int) -> list[int]:
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


def hop_diameter_lower_bound(g: Graph, start: int = 0, sweeps: int = 6) -> int:
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


def oneway_fraction(g: Graph) -> float:
    """Fraction of directed edges (u, v) whose reverse (v, u) does not exist."""
    m = g.m
    if m == 0:
        return 0.0
    return sum(1 for u in range(g.n) for v in g.out[u] if u not in g.out[v]) / m


def graph_stats(g: Graph, name: str, source: str = "") -> dict:
    """Dictionary with n, m, average out-degree, hop-diameter lower bound and
    the fraction of one-way edges."""
    return dict(graph=name, source=source, n=g.n, m=g.m, avg_out_degree=g.m / g.n,
                hop_diameter=hop_diameter_lower_bound(g), oneway_frac=oneway_fraction(g))
