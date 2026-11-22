"""Disruption simulators. Each returns a list of (u, v, old_w, new_w).

Two closure models are supported:
  * "factor": a blocked road keeps a large finite weight (BLOCK_FACTOR x travel
    time), so the network stays strongly connected;
  * "delete": a blocked road is removed (new weight INF); nodes may become
    unreachable from the source.
Congestion waves only slow roads down and never delete them.
"""
import math
from collections import deque

from graph import INF

BLOCK_FACTOR = 50     # blocked road ("factor" model): 50x travel time
WAVE_PEAK = 10        # congestion multiplier at the epicentre
WAVE_DECAY = 2.0      # hops over which congestion decays by 1/e
CLOSURES = ("factor", "delete")


def blocked(w, closure="factor"):
    """New weight of a road with weight w after it is blocked."""
    if closure == "delete":
        return INF
    if closure == "factor":
        return w * BLOCK_FACTOR
    raise ValueError(f"unknown closure model {closure!r}")


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


def single_block(g, rng, k=1, closure="factor"):
    """k independent random road closures scattered over the city."""
    edges = rng.sample(g.edges(), k)
    return [(u, v, w, blocked(w, closure)) for u, v, w in edges]


def cluster_block(g, rng, k, closure="factor"):
    """Accident zone: k connected edges around a random point are all blocked."""
    center = rng.randrange(g.n)
    return [(u, v, g.out[u][v], blocked(g.out[u][v], closure))
            for (u, v), _ in _bfs_edges(g, center, k)]


def congestion_wave(g, rng, k, closure="factor"):
    """Congestion spreading from an epicentre: weight multiplier decays with hop
    distance. (`closure` is accepted for a uniform signature but unused.)"""
    center = rng.randrange(g.n)
    res = []
    for (u, v), depth in _bfs_edges(g, center, k):
        w = g.out[u][v]
        f = 1 + (WAVE_PEAK - 1) * math.exp(-depth / WAVE_DECAY)
        res.append((u, v, w, max(w + 1, round(w * f))))
    return res


def tree_block(g, rng, k, parent, closure="factor"):
    """k closures on random edges of the current shortest-path tree `parent`
    (worst-case-relevant: every blocked road carries a shortest path)."""
    heads = [x for x in range(g.n) if parent[x] >= 0]
    return [(parent[v], v, g.out[parent[v]][v], blocked(g.out[parent[v]][v], closure))
            for v in rng.sample(heads, min(k, len(heads)))]


MODES = {"single": single_block, "cluster": cluster_block, "wave": congestion_wave,
         "tree": tree_block}
TREE_MODES = {"tree"}   # generators that also need the current shortest-path tree


def generate(mode, g, rng, k, parent=None, closure="factor"):
    """Uniform entry point: a disruption of `mode` with k edges."""
    if mode in TREE_MODES:
        return MODES[mode](g, rng, k, parent, closure)
    return MODES[mode](g, rng, k, closure)
