"""Static Dijkstra and incremental (Ramalingam-Reps style) dynamic SSSP repair."""
import heapq
from graph import INF


def dijkstra(g, s):
    """Single-source shortest paths, O((m + n) log n) with a binary heap."""
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


class DynamicSSSP:
    """Maintains dist[] = shortest distances from `s` while edge weights change.

    update_edge(u, v, new_w) changes one edge weight and repairs `dist`,
    returning the number of nodes whose distance changed (|delta|).
    Requires strictly positive integer weights.
    """

    def __init__(self, g, s):
        self.g, self.s = g, s
        self.dist = dijkstra(g, s)

    def recompute(self):
        self.dist = dijkstra(self.g, self.s)
        return self.dist

    def update_edge(self, u, v, new_w):
        g = self.g
        old = g.out[u][v]
        if new_w == old:
            return 0
        g.set_weight(u, v, new_w)
        if new_w < old:
            return self._decrease(u, v, new_w)
        return self._increase(u, v, old)

    # ---- weight decrease: propagate the improvement outward -------------
    def _decrease(self, u, v, w):
        dist, out = self.dist, self.g.out
        if dist[u] == INF or dist[u] + w >= dist[v]:
            return 0                                   # no shorter path appears
        dist[v] = dist[u] + w
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
                    push(heap, (c, z))
        return changed

    # ---- weight increase: find affected set A, then re-solve inside A ----
    def _increase(self, u, v, old_w):
        dist, out, inn = self.dist, self.g.out, self.g.inn
        if dist[u] == INF or dist[u] + old_w != dist[v]:
            return 0                                   # edge was not tight: nothing changes
        pop, push = heapq.heappop, heapq.heappush

        # Phase 1: affected set A = nodes that lose every tight path from s.
        # Process candidates in increasing OLD distance (weights > 0 so tight
        # parents always have strictly smaller distance and are decided first).
        A = set()
        queued = {v}
        heap = [(dist[v], v)]
        while heap:
            d, x = pop(heap)
            supported = False
            for y, wy in inn[x].items():               # still has a tight parent outside A?
                if y not in A and dist[y] != INF and dist[y] + wy == d:
                    supported = True
                    break
            if supported:
                continue
            A.add(x)
            for z, wz in out[x].items():               # tight children become candidates
                if z not in queued and dist[z] != INF and d + wz == dist[z]:
                    queued.add(z)
                    push(heap, (dist[z], z))

        # Phase 2: new distances inside A, seeded from the unaffected boundary.
        heap = []
        for x in A:
            best = INF
            for y, wy in inn[x].items():
                if y not in A and dist[y] != INF:
                    c = dist[y] + wy
                    if c < best:
                        best = c
            dist[x] = best
            if best < INF:
                heap.append((best, x))
        heapq.heapify(heap)
        while heap:
            d, x = pop(heap)
            if d > dist[x]:
                continue
            for z, wz in out[x].items():
                if z in A:
                    c = d + wz
                    if c < dist[z]:
                        dist[z] = c
                        push(heap, (c, z))
        return len(A)
