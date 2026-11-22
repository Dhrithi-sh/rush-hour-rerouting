"""Disruption simulators. Each returns a list of (u, v, old_w, new_w).

A road 'closure' is modelled as a large finite weight multiplier (BLOCK_FACTOR)
because the algorithms need finite positive integer weights.
"""
import math
from collections import deque

BLOCK_FACTOR = 50     # blocked road: 50x travel time
WAVE_PEAK = 10        # congestion multiplier at the epicentre
WAVE_DECAY = 2.0      # hops over which congestion decays by 1/e


def _bfs_edges(g, center, k):
    """First k distinct edges (either direction) in BFS order around `center`,
    each tagged with its hop depth."""
    seen_nodes, seen_edges, found = {center}, set(), []
    q = deque([(center, 0)])
    while q and len(found) < k:
        x, d = q.popleft()
        incident = [((x, y), y) for y in g.out[x]] + [((y, x), y) for y in g.inn[x]]
        for e, y in incident:
            if e not in seen_edges:
                seen_edges.add(e)
                found.append((e, d))
            if y not in seen_nodes:
                seen_nodes.add(y)
                q.append((y, d + 1))
    return found[:k]


def single_block(g, rng, k=1):
    """k independent random road closures scattered over the city."""
    edges = rng.sample(g.edges(), k)
    return [(u, v, w, w * BLOCK_FACTOR) for u, v, w in edges]


def cluster_block(g, rng, k):
    """Accident zone: k connected edges around a random point are all blocked."""
    center = rng.randrange(g.n)
    return [(u, v, g.out[u][v], g.out[u][v] * BLOCK_FACTOR)
            for (u, v), _ in _bfs_edges(g, center, k)]


def congestion_wave(g, rng, k):
    """Congestion spreading from an epicentre: weight multiplier decays with hop distance."""
    center = rng.randrange(g.n)
    res = []
    for (u, v), depth in _bfs_edges(g, center, k):
        w = g.out[u][v]
        f = 1 + (WAVE_PEAK - 1) * math.exp(-depth / WAVE_DECAY)
        res.append((u, v, w, max(w + 1, round(w * f))))
    return res


MODES = {"single": single_block, "cluster": cluster_block, "wave": congestion_wave}
