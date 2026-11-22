"""Lifelong Planning A* (Koenig, Likhachev & Furcy, 2004) and plain A*.

LPA* maintains one shortest s -> t path while edge weights change. It keeps
  g[x]    - the current distance estimate,
  rhs[x]  - the one-step lookahead min over in-edges (y, x) of g[y] + w(y, x),
and a priority queue of *locally inconsistent* nodes (g != rhs), ordered by
  key(x) = (min(g, rhs) + h(x), min(g, rhs)).
After a change only the inconsistent nodes whose key beats the target's are
processed, so with a good heuristic h the repair stays near the old path.

The heuristic must be consistent: h(t) = 0 and h(u) <= w(u, v) + h(v) for every
edge. `straight_line_heuristic` builds one for road graphs; it stays consistent
as long as no edge becomes *faster* than it was when the heuristic was built
(closures and congestion only slow roads down, and clearing restores them).
"""
import heapq
import math

from graph import INF


def straight_line_heuristic(g, t, slack=1e-9):
    """h(x) = straight-line distance(x, t) / v_max, with v_max the largest
    'distance per unit weight' over all current edges. Using the graph's own
    fastest edge (instead of a nominal speed limit) makes h consistent despite the
    integer rounding of travel times; `slack` keeps a tiny margin for float error.
    Works for any planar coordinates (metres or degrees)."""
    xy = g.xy
    vmax = 0.0
    for u in range(g.n):
        xu, yu = xy[u]
        for v, w in g.out[u].items():
            vmax = max(vmax, math.hypot(xu - xy[v][0], yu - xy[v][1]) / w)
    if vmax == 0:
        return [0.0] * g.n
    vmax *= 1 + slack
    xt, yt = xy[t]
    return [math.hypot(x - xt, y - yt) / vmax for x, y in xy]


def is_consistent(g, h, t):
    """True if h(t) == 0 and h(u) <= w(u, v) + h(v) on every edge."""
    return h[t] == 0 and all(h[u] <= w + h[v] for u in range(g.n) for v, w in g.out[u].items())


def astar(g, s, t, h):
    """Plain A* from scratch; returns the s -> t distance (INF if unreachable)."""
    dist = {s: 0}
    heap = [(h[s], 0, s)]
    out = g.out
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        _, d, x = pop(heap)
        if x == t:
            return d
        if d > dist[x]:
            continue
        for z, w in out[x].items():
            c = d + w
            if c < dist.get(z, INF):
                dist[z] = c
                push(heap, (c + h[z], c, z))
    return INF


def dijkstra_to(g, s, t):
    """Dijkstra from scratch that stops as soon as t is settled."""
    dist = {s: 0}
    heap = [(0, s)]
    out = g.out
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        d, x = pop(heap)
        if x == t:
            return d
        if d > dist[x]:
            continue
        for z, w in out[x].items():
            c = d + w
            if c < dist.get(z, INF):
                dist[z] = c
                push(heap, (c, z))
    return INF


class LPAStar:
    """Incremental point-to-point shortest path from s to t.

    update_edges(changes) applies [(u, v, new_w)] to the graph (INF deletes) and
    repairs; distance() and path() then describe the new shortest s -> t path.
    """

    def __init__(self, g, s, t, h=None):
        self.g, self.s, self.t = g, s, t
        self.h = list(h) if h is not None else [0.0] * g.n
        self.gv = [INF] * g.n
        self.rhs = [INF] * g.n
        self.rhs[s] = 0
        self.heap = []
        self.inq = {}                     # node -> key of its live heap entry
        self._push(s)
        self.compute()

    # ---- queue helpers (lazy deletion) ----------------------------------
    def _key(self, x):
        m = min(self.gv[x], self.rhs[x])
        return (m + self.h[x], m)

    def _push(self, x):
        k = self._key(x)
        self.inq[x] = k
        heapq.heappush(self.heap, (k, x))

    def _top_key(self):
        heap, inq = self.heap, self.inq
        while heap and inq.get(heap[0][1]) != heap[0][0]:
            heapq.heappop(heap)                      # stale entry
        return heap[0][0] if heap else (INF, INF)

    def _update_vertex(self, x):
        if x != self.s:
            best = INF
            gv = self.gv
            for y, w in self.g.inn[x].items():
                c = gv[y] + w
                if c < best:
                    best = c
            self.rhs[x] = best
        if self.gv[x] != self.rhs[x]:
            self._push(x)
        else:
            self.inq.pop(x, None)

    # ---- main loop -------------------------------------------------------
    def compute(self):
        """Process inconsistent nodes until t is consistent and no queued key is
        smaller than t's. Returns the number of node expansions."""
        t, gv, rhs, out = self.t, self.gv, self.rhs, self.g.out
        expanded = 0
        while self._top_key() < self._key(t) or rhs[t] != gv[t]:
            _, x = heapq.heappop(self.heap)
            del self.inq[x]
            expanded += 1
            if gv[x] > rhs[x]:                       # over-consistent: settle
                gv[x] = rhs[x]
                for z in out[x]:
                    self._update_vertex(z)
            else:                                    # under-consistent: reset
                gv[x] = INF
                self._update_vertex(x)
                for z in out[x]:
                    self._update_vertex(z)
        return expanded

    def update_edges(self, changes):
        """Apply weight changes (INF = delete) and repair. Returns expansions."""
        g = self.g
        heads = set()
        for u, v, w in changes:
            g.set_weight(u, v, w)
            heads.add(v)
        for v in heads:
            self._update_vertex(v)
        return self.compute()

    def distance(self):
        return self.gv[self.t]

    def path(self):
        """Shortest s -> t path as a node list ([] if unreachable)."""
        if self.gv[self.t] == INF:
            return []
        x, gv, path = self.t, self.gv, [self.t]
        while x != self.s:                           # move to the best predecessor
            x = min(self.g.inn[x].items(), key=lambda yw: gv[yw[0]] + yw[1])[0]
            path.append(x)
        path.reverse()
        return path

    def snapshot(self):
        return list(self.gv), list(self.rhs), list(self.heap), dict(self.inq)

    def restore(self, snap):
        self.gv[:] = snap[0]
        self.rhs[:] = snap[1]
        self.heap = list(snap[2])
        self.inq = dict(snap[3])
