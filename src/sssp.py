"""Static Dijkstra and incremental (Ramalingam-Reps style) dynamic SSSP repair.

`DynamicSSSP` maintains, for a fixed source s,
  * dist[x]   - shortest travel time from s to x (INF if unreachable), and
  * parent[x] - the predecessor of x on one shortest path (-1 for s / unreachable),
while edge weights change. Weights are strictly positive integers; INF means the
road is closed (the edge is deleted from the graph).

Invariant after every public call (checked by `check_tree` in the tests and the
experiments): dist equals a from-scratch Dijkstra, and every parent edge
(parent[x], x) exists and is tight, i.e. dist[parent[x]] + w = dist[x].
"""
import heapq

from graph import INF


def dijkstra(g, s):
    """Single-source shortest distances, O((m + n) log n) with a binary heap.
    Used as the test oracle (kept deliberately minimal)."""
    dist = [INF] * g.n
    dist[s] = 0
    heap = [(0, s)]
    out = g.out
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        d, x = pop(heap)
        if d > dist[x]:
            continue
        for z, w in out[x].items():
            c = d + w
            if c < dist[z]:
                dist[z] = c
                push(heap, (c, z))
    return dist


def dijkstra_tree(g, s):
    """Dijkstra returning (dist, parent): the full-recomputation baseline."""
    dist = [INF] * g.n
    parent = [-1] * g.n
    dist[s] = 0
    heap = [(0, s)]
    out = g.out
    pop, push = heapq.heappop, heapq.heappush
    while heap:
        d, x = pop(heap)
        if d > dist[x]:
            continue
        for z, w in out[x].items():
            c = d + w
            if c < dist[z]:
                dist[z] = c
                parent[z] = x
                push(heap, (c, z))
    return dist, parent


def check_tree(g, s, dist, parent):
    """Raise AssertionError unless `parent` is a valid shortest-path tree for `dist`."""
    assert parent[s] == -1 and dist[s] == 0
    for x in range(g.n):
        if x == s:
            continue
        p = parent[x]
        if dist[x] == INF:
            assert p == -1, f"unreachable node {x} has parent {p}"
        else:
            assert p >= 0 and x in g.out[p], f"node {x}: parent edge ({p},{x}) missing"
            assert dist[p] + g.out[p][x] == dist[x], f"node {x}: parent edge not tight"


class DynamicSSSP:
    """Maintains dist[] and parent[] from source `s` while edge weights change.

    update_edge(u, v, w)   one change, repaired immediately (per-edge repair);
    update_edges(changes)  a batch of changes, repaired in one sweep (batch repair).
    Both return the number of nodes whose distance changed (|delta|). A weight of
    INF closes (deletes) the road; a finite weight on a missing edge (re)opens it.
    """

    def __init__(self, g, s):
        self.g, self.s = g, s
        self.dist, self.parent = dijkstra_tree(g, s)
        # Generation-stamped marks instead of per-call set() objects: node x is in
        # the current affected set A iff _in_a[x] == _gen (and queued iff
        # _queued[x] == _gen). Bumping _gen clears both in O(1).
        self._in_a = [0] * g.n
        self._queued = [0] * g.n
        self._gen = 0

    def recompute(self):
        self.dist, self.parent = dijkstra_tree(self.g, self.s)
        return self.dist

    def path_to(self, t):
        """Current shortest path s -> t as a list of nodes ([] if t is unreachable)."""
        if self.dist[t] == INF:
            return []
        path = [t]
        parent = self.parent
        while t != self.s:
            t = parent[t]
            path.append(t)
        path.reverse()
        return path

    def snapshot(self):
        return list(self.dist), list(self.parent)

    def restore(self, snap):
        self.dist[:] = snap[0]
        self.parent[:] = snap[1]

    # ================================================================ per edge
    def update_edge(self, u, v, new_w):
        g = self.g
        old = g.out[u].get(v, INF)
        if new_w == old:
            return 0
        g.set_weight(u, v, new_w)
        if new_w < old:
            return self._decrease(u, v, new_w)
        return self._increase(u, v, old)

    # ---- weight decrease: propagate the improvement outward -------------
    def _decrease(self, u, v, w):
        dist, parent, out = self.dist, self.parent, self.g.out
        if dist[u] == INF or dist[u] + w >= dist[v]:
            return 0                                   # no shorter path appears
        dist[v] = dist[u] + w
        parent[v] = u
        heap = [(dist[v], v)]
        changed = 0
        pop, push = heapq.heappop, heapq.heappush
        while heap:
            d, x = pop(heap)
            if d > dist[x]:
                continue
            changed += 1
            for z, wz in out[x].items():
                c = d + wz
                if c < dist[z]:
                    dist[z] = c
                    parent[z] = x
                    push(heap, (c, z))
        return changed

    # ---- weight increase: find affected set A, then re-solve inside A ----
    def _increase(self, u, v, old_w):
        dist = self.dist
        if dist[u] == INF or dist[u] + old_w != dist[v]:
            return 0                                   # edge was not tight: nothing changes
        A = self._affected([v])
        self._resolve(A)
        return len(A)

    # ================================================================ shared
    def _affected(self, seeds):
        """Phase 1. Return the list A of nodes that lose every tight
        path from s, given that the in-edges of `seeds` were the only edges made
        heavier (already applied to the graph). Candidates are processed in
        increasing OLD distance; with positive weights every tight parent has a
        strictly smaller distance and is therefore classified first. A candidate
        that still has a tight parent outside A keeps its distance, and its parent
        pointer is moved to that parent (the old one may be in A).
        Membership of A is recorded in self._in_a under a fresh generation."""
        dist, parent, out, inn = self.dist, self.parent, self.g.out, self.g.inn
        pop, push = heapq.heappop, heapq.heappush
        self._gen += 1
        gen, in_a, queued = self._gen, self._in_a, self._queued
        A, heap = [], []
        for x in seeds:
            if queued[x] != gen:
                queued[x] = gen
                heap.append((dist[x], x))
        heapq.heapify(heap)
        while heap:
            d, x = pop(heap)
            support = -1
            for y, wy in inn[x].items():               # still has a tight parent outside A?
                if in_a[y] != gen and dist[y] + wy == d:
                    support = y
                    break
            if support >= 0:
                parent[x] = support
                continue
            A.append(x)
            in_a[x] = gen
            for z, wz in out[x].items():               # tight children become candidates
                if queued[z] != gen and d + wz == dist[z]:
                    queued[z] = gen
                    push(heap, (dist[z], z))
        return A

    def _seed(self, A):
        """Phase 2 start: label every x in A with its best edge from outside A."""
        dist, parent, inn = self.dist, self.parent, self.g.inn
        gen, in_a = self._gen, self._in_a
        heap = []
        for x in A:
            best, arg = INF, -1
            for y, wy in inn[x].items():
                if in_a[y] != gen:
                    c = dist[y] + wy
                    if c < best:
                        best, arg = c, y
            dist[x], parent[x] = best, arg
            if best < INF:
                heap.append((best, x))
        heapq.heapify(heap)
        return heap

    def _resolve(self, A):
        """Phase 2 for a single increase: multi-source Dijkstra inside A."""
        dist, parent, out = self.dist, self.parent, self.g.out
        gen, in_a = self._gen, self._in_a
        heap = self._seed(A)
        pop, push = heapq.heappop, heapq.heappush
        while heap:
            d, x = pop(heap)
            if d > dist[x]:
                continue
            for z, wz in out[x].items():
                if in_a[z] == gen:
                    c = d + wz
                    if c < dist[z]:
                        dist[z] = c
                        parent[z] = x
                        push(heap, (c, z))

    # ================================================================ batch
    def update_edges(self, changes):
        """Apply a batch of weight changes [(u, v, new_w), ...] and repair once.

        1. Apply all increases. Phase 1 (`_affected`) from every head of an
           increased edge that was tight finds the union A of affected sets with
           respect to G1 = old weights + all increases.
        2. Apply all decreases (the graph is now G2 = final weights).
        3. One Dijkstra: seed every x in A with its best edge from outside A, and
           relax every decreased edge (u, v) whose head improves; then propagate
           improvements anywhere in the graph (not only inside A).

        Why this is correct (full argument in the report, Section 3):
        after step 1 every node outside A still has dist = d1 (exact in G1;
        Lemma 3 with several increased edges), so every label is the length of a
        real walk in G2, i.e. an upper bound on d2. When step 3 starts, every
        *violated* edge (label[y] + w < label[x]) has either just been relaxed (a
        decreased edge) or has its tail in the heap (a node of A with a finite
        label), and Dijkstra preserves that invariant. When the heap is empty no
        edge is violated, so the labels are also lower bounds: dist = d2.
        Returns the number of nodes whose distance changed.
        """
        g, dist, parent, out = self.g, self.dist, self.parent, self.g.out
        final = {}
        for u, v, w in changes:                        # last write wins per edge
            final[(u, v)] = w
        inc, dec = [], []
        for (u, v), w in final.items():
            old = out[u].get(v, INF)
            if w > old:
                inc.append((u, v, old, w))
            elif w < old:
                dec.append((u, v, w))

        # 1. increases + union of affected sets
        for u, v, _, w in inc:
            g.set_weight(u, v, w)
        seeds = [v for u, v, old, _ in inc if dist[u] != INF and dist[u] + old == dist[v]]
        A = self._affected(seeds)
        # 2. decreases
        for u, v, w in dec:
            g.set_weight(u, v, w)
        # 3. one Dijkstra (seed A first: its stale old labels are too small)
        old_val = {x: dist[x] for x in A}
        heap = self._seed(A)
        push, pop = heapq.heappush, heapq.heappop
        for u, v, w in dec:
            c = dist[u] + w
            if c < dist[v]:
                if v not in old_val:
                    old_val[v] = dist[v]
                dist[v], parent[v] = c, u
                push(heap, (c, v))
        while heap:
            d, x = pop(heap)
            if d > dist[x]:
                continue
            for z, wz in out[x].items():
                c = d + wz
                if c < dist[z]:
                    if z not in old_val:
                        old_val[z] = dist[z]
                    dist[z], parent[z] = c, x
                    push(heap, (c, z))
        return sum(1 for x, o in old_val.items() if dist[x] != o)
