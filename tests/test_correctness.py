"""Randomised correctness tests: after EVERY update the incremental repair must
equal a from-scratch Dijkstra. Run:  python tests/test_correctness.py"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from graph import Graph, INF, make_synthetic_city, from_networkx  # noqa: E402
from sssp import DynamicSSSP, dijkstra                              # noqa: E402


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
