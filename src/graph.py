"""Weighted directed road-graph container + graph builders.

Travel times are stored as POSITIVE INTEGERS (deciseconds = 0.1 s). Integer
weights make the "tight edge" test  dist[u] + w == dist[v]  exact (no float
round-off) and positivity is required by the repair algorithm's correctness
proof (see report, Section 3).
"""
import math
import random

INF = float("inf")


class Graph:
    """Simple directed graph with adjacency dicts in both directions."""

    def __init__(self, n):
        self.n = n
        self.out = [dict() for _ in range(n)]   # out[u][v] = w
        self.inn = [dict() for _ in range(n)]   # inn[v][u] = w
        self.xy = [(0.0, 0.0)] * n              # coordinates (for plots)
        self.edge_class = {}                    # (u,v) -> 'local'|'arterial'|'bridge'

    # -- construction -------------------------------------------------
    def add_edge(self, u, v, w, cls="local"):
        if u == v:
            return
        w = int(w)
        if w < 1:
            raise ValueError("weights must be positive integers")
        old = self.out[u].get(v)
        if old is not None and old <= w:
            return                                # keep cheapest parallel edge
        self.out[u][v] = w
        self.inn[v][u] = w
        self.edge_class[(u, v)] = cls

    def set_weight(self, u, v, w):
        if w < 1:
            raise ValueError("weights must be positive integers")
        self.out[u][v] = w
        self.inn[v][u] = w

    # -- queries ------------------------------------------------------
    def weight(self, u, v):
        return self.out[u][v]

    def edges(self):
        return [(u, v, w) for u in range(self.n) for v, w in self.out[u].items()]

    @property
    def m(self):
        return sum(len(d) for d in self.out)

    def copy(self):
        g = Graph(self.n)
        g.out = [dict(d) for d in self.out]
        g.inn = [dict(d) for d in self.inn]
        g.xy = list(self.xy)
        g.edge_class = dict(self.edge_class)
        return g


def _largest_scc_graph(n, edge_list, xy):
    """Keep only the largest strongly connected component and relabel 0..n'-1.
    edge_list: iterable of (u, v, w, cls)."""
    import networkx as nx
    D = nx.DiGraph()
    D.add_nodes_from(range(n))
    D.add_edges_from((u, v) for u, v, _, _ in edge_list)
    comp = max(nx.strongly_connected_components(D), key=len)
    idx = {old: new for new, old in enumerate(sorted(comp))}
    g = Graph(len(idx))
    for old, new in idx.items():
        g.xy[new] = xy[old]
    for u, v, w, cls in edge_list:
        if u in idx and v in idx:
            g.add_edge(idx[u], idx[v], w, cls)
    return g


# ---------------------------------------------------------------------
# Synthetic city (offline fallback; same data structure as a real OSM graph)
# ---------------------------------------------------------------------
def make_synthetic_city(width=140, height=140, seed=0, remove_frac=0.08,
                        oneway_frac=0.12, arterial_every=12, n_bridges=4):
    """Perturbed street grid with arterial roads, one-way streets and a 'river'
    that can only be crossed at a few bridges (so topology matters)."""
    rng = random.Random(seed)
    W, H = width, height

    def nid(i, j):
        return i * W + j

    cell = 100.0  # metres
    xy = [None] * (W * H)
    for i in range(H):
        for j in range(W):
            xy[nid(i, j)] = ((j + rng.uniform(-.3, .3)) * cell,
                             (i + rng.uniform(-.3, .3)) * cell)
    speed = {"local": 30 / 3.6, "arterial": 60 / 3.6, "bridge": 50 / 3.6}  # m/s

    def tt(a, b, cls):
        L = math.hypot(xy[a][0] - xy[b][0], xy[a][1] - xy[b][1])
        return max(1, round(L / speed[cls] * 10))

    river_col = W // 2 - 1          # edges between col river_col and river_col+1
    bridge_rows = {int((k + 0.5) * H / n_bridges + rng.randint(-3, 3)) % H
                   for k in range(n_bridges)}
    edges = []
    for i in range(H):
        for j in range(W):
            for di, dj in ((0, 1), (1, 0)):
                ii, jj = i + di, j + dj
                if ii >= H or jj >= W:
                    continue
                a, b = nid(i, j), nid(ii, jj)
                arterial = (i % arterial_every == 0 and di == 0) or \
                           (j % arterial_every == 0 and dj == 0)
                cls = "arterial" if arterial else "local"
                if di == 0 and j == river_col:           # crossing the river
                    if i not in bridge_rows:
                        continue
                    cls = "bridge"
                    edges += [(a, b, tt(a, b, cls), cls), (b, a, tt(b, a, cls), cls)]
                    continue
                if cls == "local" and rng.random() < remove_frac:
                    continue
                if cls == "local" and rng.random() < oneway_frac:
                    if rng.random() < .5:
                        a, b = b, a
                    edges.append((a, b, tt(a, b, cls), cls))
                else:
                    edges += [(a, b, tt(a, b, cls), cls), (b, a, tt(b, a, cls), cls)]
    return _largest_scc_graph(W * H, edges, xy)


# ---------------------------------------------------------------------
# Real city via OSMnx
# ---------------------------------------------------------------------
def from_networkx(G, weight="travel_time", scale=10):
    """Convert an OSMnx / networkx (Multi)DiGraph into our Graph.
    `weight` is travel time in seconds; stored as integer deciseconds."""
    nodes = list(G.nodes)
    index = {u: i for i, u in enumerate(nodes)}
    xy = [(float(G.nodes[u].get("x", 0.0)), float(G.nodes[u].get("y", 0.0)))
          for u in nodes]
    arterial_tags = {"motorway", "trunk", "primary", "secondary",
                     "motorway_link", "trunk_link", "primary_link", "secondary_link"}
    edge_list = []
    for u, v, data in G.edges(data=True):
        t = data.get(weight)
        if t is None:
            t = float(data.get("length", 100.0)) / (50 / 3.6)
        hw = data.get("highway", "")
        hw = hw[0] if isinstance(hw, list) and hw else hw
        br = data.get("bridge", None)
        br = br[0] if isinstance(br, list) and br else br
        cls = "bridge" if (br and str(br).lower() not in ("no", "false", "nan")) \
            else ("arterial" if hw in arterial_tags else "local")
        edge_list.append((index[u], index[v], max(1, round(float(t) * scale)), cls))
    return _largest_scc_graph(len(nodes), edge_list, xy)


def load_osm(place, cache_dir="data"):
    """Download (or load cached) drivable street network for a place name."""
    import os
    import re
    import osmnx as ox
    slug = re.sub(r"[^a-z0-9]+", "_", place.lower()).strip("_")
    path = os.path.join(cache_dir, slug + ".graphml")
    if os.path.exists(path):
        G = ox.load_graphml(path)
    else:
        G = ox.graph_from_place(place, network_type="drive")
        G = ox.add_edge_speeds(G)
        G = ox.add_edge_travel_times(G)
        os.makedirs(cache_dir, exist_ok=True)
        ox.save_graphml(G, path)
    return from_networkx(G)
