"""Randomised correctness tests: after EVERY update the incremental repair must
equal a from-scratch Dijkstra. Run:  python tests/test_correctness.py"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from graph import Graph, INF, make_synthetic_city, from_networkx  # noqa: E402
from sssp import DynamicSSSP, dijkstra, check_tree                  # noqa: E402
from disruptions import MODES, CLOSURES, BLOCK_FACTOR, blocked, generate  # noqa: E402


def random_graph(rng, n, m, wmax):
    g = Graph(n)
    for _ in range(m):
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            g.add_edge(u, v, rng.randint(1, wmax))
    return g


class TestRepair(unittest.TestCase):
    def check_sequence(self, g, s, rng, steps, wmax):
        dyn = DynamicSSSP(g, s)
        for _ in range(steps):
            u, v, _ = rng.choice(g.edges())
            dyn.update_edge(u, v, rng.randint(1, wmax))
            self.assertEqual(dyn.dist, dijkstra(g, s))

    def test_random_sparse_graphs_with_unreachable_nodes(self):
        rng = random.Random(1)
        for _ in range(150):
            n = rng.randint(2, 25)
            g = random_graph(rng, n, rng.randint(1, 4 * n), rng.choice([1, 3, 10]))
            if not g.edges():
                continue
            self.check_sequence(g, rng.randrange(n), rng, 40, 12)

    def test_many_equal_weights_and_ties(self):
        rng = random.Random(2)
        for _ in range(100):
            n = rng.randint(3, 30)
            g = random_graph(rng, n, 5 * n, 2)           # weights in {1,2}: lots of ties
            if g.edges():
                self.check_sequence(g, 0, rng, 60, 3)

    def test_synthetic_city_block_and_clear(self):
        g = make_synthetic_city(30, 30, seed=3)
        rng = random.Random(4)
        s = rng.randrange(g.n)
        dyn = DynamicSSSP(g, s)
        base = list(dyn.dist)
        for _ in range(60):
            u, v, w = rng.choice(g.edges())
            dyn.update_edge(u, v, w * 50)
            self.assertEqual(dyn.dist, dijkstra(g, s))
            dyn.update_edge(u, v, w)
            self.assertEqual(dyn.dist, base)

    def test_returned_count_is_exact_number_of_changed_nodes(self):
        g = make_synthetic_city(25, 25, seed=5)
        rng = random.Random(6)
        dyn = DynamicSSSP(g, 0)
        for _ in range(80):
            u, v, w = rng.choice(g.edges())
            before = list(dyn.dist)
            c = dyn.update_edge(u, v, max(1, int(w * rng.choice([0.3, 2, 40]))))
            self.assertEqual(c, sum(a != b for a, b in zip(before, dyn.dist)))

    def test_from_networkx_roundtrip(self):
        import networkx as nx
        G = nx.MultiDiGraph()
        for i in range(5):
            G.add_node(i, x=float(i), y=0.0)
        for i in range(5):
            G.add_edge(i, (i + 1) % 5, travel_time=3.2, highway="residential")
            G.add_edge((i + 1) % 5, i, travel_time=4.0, highway="primary")
        G.add_edge(0, 1, travel_time=1.0, highway="primary", bridge="yes")   # parallel, cheaper
        G.add_node(99, x=9.0, y=9.0)                                        # isolated -> dropped
        g = from_networkx(G)
        self.assertEqual(g.n, 5)
        self.assertEqual(g.out[0][1], 10)
        self.assertEqual(g.edge_class[(0, 1)], "bridge")
        self.assertTrue(all(d < INF for d in dijkstra(g, 0)))


class TestTreeBatchAndDeletion(unittest.TestCase):
    """Parent array, batch repair and true deletions (weight = INF)."""

    def check(self, dyn, g, s):
        self.assertEqual(dyn.dist, dijkstra(g, s))
        check_tree(g, s, dyn.dist, dyn.parent)

    def test_single_and_batch_with_deletions_on_random_graphs(self):
        rng = random.Random(7)
        for _ in range(200):
            n = rng.randint(2, 15)
            g = random_graph(rng, n, rng.randint(1, 4 * n), 4)
            pairs = [(u, v) for u in range(n) for v in range(n) if u != v]
            s = rng.randrange(n)
            dyn = DynamicSSSP(g, s)
            for _ in range(25):
                ch = [(u, v, INF if rng.random() < .3 else rng.randint(1, 5))
                      for u, v in (rng.choice(pairs) for _ in range(rng.randint(1, 5)))]
                before = list(dyn.dist)
                if rng.random() < .5:
                    c = dyn.update_edges(ch)
                else:
                    c = sum(dyn.update_edge(u, v, w) for u, v, w in ch[:1])
                self.check(dyn, g, s)
                self.assertEqual(c, sum(a != b for a, b in zip(before, dyn.dist)))

    def test_batch_equals_sequential_on_city(self):
        g1 = make_synthetic_city(30, 30, seed=8)
        g2 = g1.copy()
        rng = random.Random(9)
        a, b = DynamicSSSP(g1, 0), DynamicSSSP(g2, 0)
        for _ in range(30):
            ch = [(u, v, w * rng.choice([2, 50]) if rng.random() < .7 else max(1, w // 2))
                  for u, v, w in rng.sample(g1.edges(), 25)]
            a.update_edges(ch)
            for u, v, w in ch:
                b.update_edge(u, v, w)
            self.assertEqual(a.dist, b.dist)
            self.check(a, g1, 0)

    def test_deleting_the_only_bridge_strands_nodes(self):
        g = Graph(4)
        g.add_edge(0, 1, 2); g.add_edge(1, 2, 3); g.add_edge(2, 3, 1); g.add_edge(3, 2, 1)
        dyn = DynamicSSSP(g, 0)
        self.assertEqual(dyn.path_to(3), [0, 1, 2, 3])
        self.assertEqual(dyn.update_edge(1, 2, INF), 2)          # nodes 2 and 3 lost
        self.assertNotIn(2, g.out[1])
        self.assertEqual(dyn.dist[2:], [INF, INF])
        self.assertEqual(dyn.path_to(3), [])
        self.check(dyn, g, 0)
        self.assertEqual(dyn.update_edge(1, 2, 3), 2)            # re-open the road
        self.assertEqual(dyn.path_to(3), [0, 1, 2, 3])
        self.check(dyn, g, 0)

    def test_path_to_follows_parents_and_has_shortest_length(self):
        g = make_synthetic_city(20, 20, seed=10)
        dyn = DynamicSSSP(g, 5)
        rng = random.Random(11)
        for _ in range(20):
            dyn.update_edges([(u, v, w * 50) for u, v, w in rng.sample(g.edges(), 10)])
            for t in rng.sample(range(g.n), 10):
                p = dyn.path_to(t)
                self.assertEqual(p[0], 5)
                self.assertEqual(p[-1], t)
                self.assertEqual(sum(g.out[a][b] for a, b in zip(p, p[1:])), dyn.dist[t])

    def test_set_weight_validation(self):
        g = Graph(2)
        with self.assertRaises(ValueError):
            g.set_weight(0, 1, 0)
        with self.assertRaises(ValueError):
            g.set_weight(0, 1, 2.5)
        g.set_weight(0, 1, INF)                                    # deleting a missing edge is a no-op
        self.assertEqual(g.weight(0, 1), INF)


class TestDisruptions(unittest.TestCase):
    def setUp(self):
        self.g = make_synthetic_city(25, 25, seed=12)
        self.dyn = DynamicSSSP(self.g, 0)

    def test_generators_return_existing_edges_with_heavier_weights(self):
        for closure in CLOSURES:
            for mode in MODES:
                rng = random.Random(13)
                ch = generate(mode, self.g, rng, 15, self.dyn.parent, closure)
                self.assertEqual(len(ch), 15)
                self.assertEqual(len({(u, v) for u, v, _, _ in ch}), 15, "edges must be distinct")
                for u, v, old, new in ch:
                    self.assertEqual(self.g.out[u][v], old)
                    self.assertGreater(new, old)
                    if mode != "wave":
                        self.assertEqual(new, INF if closure == "delete" else old * BLOCK_FACTOR)

    def test_tree_mode_only_blocks_tree_edges(self):
        ch = generate("tree", self.g, random.Random(14), 30, self.dyn.parent)
        for u, v, _, _ in ch:
            self.assertEqual(self.dyn.parent[v], u)

    def test_cluster_is_connected_and_wave_decays(self):
        rng = random.Random(15)
        ch = generate("cluster", self.g, rng, 40)
        nodes = {u for u, v, _, _ in ch} | {v for u, v, _, _ in ch}
        adj = {x: set() for x in nodes}
        for u, v, _, _ in ch:
            adj[u].add(v); adj[v].add(u)
        seen, stack = set(), [next(iter(nodes))]
        while stack:
            x = stack.pop()
            if x not in seen:
                seen.add(x); stack.extend(adj[x] - seen)
        self.assertEqual(seen, nodes)
        wave = generate("wave", self.g, random.Random(16), 200)
        ratios = [new / old for _, _, old, new in wave]
        self.assertGreater(ratios[0], ratios[-1])

    def test_generators_are_reproducible(self):
        for mode in MODES:
            a = generate(mode, self.g, random.Random(17), 10, self.dyn.parent)
            b = generate(mode, self.g, random.Random(17), 10, self.dyn.parent)
            self.assertEqual(a, b)

    def test_unknown_closure_rejected(self):
        with self.assertRaises(ValueError):
            blocked(5, "teleport")


if __name__ == "__main__":
    unittest.main(verbosity=2)
