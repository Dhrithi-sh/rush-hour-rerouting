"""LPA*, A* and early-exit Dijkstra must agree with a full Dijkstra after every
change. Run:  python tests/test_lpa.py"""
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from graph import Graph, INF, make_synthetic_city                       # noqa: E402
from sssp import dijkstra                                               # noqa: E402
from lpa import (LPAStar, astar, dijkstra_to, is_consistent,            # noqa: E402
                 straight_line_heuristic)


def path_len(g, p):
    return sum(g.out[a][b] for a, b in zip(p, p[1:]))


def random_geo_graph(rng, n, m, wmax):
    g = Graph(n)
    for i in range(n):
        g.xy[i] = (rng.random(), rng.random())
    for _ in range(m):
        u, v = rng.randrange(n), rng.randrange(n)
        if u != v:
            g.add_edge(u, v, rng.randint(1, wmax))
    return g


class TestLPAStar(unittest.TestCase):
    def check(self, lpa, g, s, t):
        ref = dijkstra(g, s)[t]
        self.assertEqual(lpa.distance(), ref)
        p = lpa.path()
        if ref == INF:
            self.assertEqual(p, [])
        else:
            self.assertEqual((p[0], p[-1]), (s, t))
            self.assertEqual(path_len(g, p), ref)

    def test_random_updates_without_heuristic(self):
        rng = random.Random(1)
        for _ in range(200):
            n = rng.randint(2, 14)
            g = random_geo_graph(rng, n, rng.randint(1, 4 * n), 4)
            pairs = [(u, v) for u in range(n) for v in range(n) if u != v]
            s, t = rng.randrange(n), rng.randrange(n)
            lpa = LPAStar(g, s, t)
            self.check(lpa, g, s, t)
            for _ in range(20):
                ch = [(u, v, INF if rng.random() < .25 else rng.randint(1, 5))
                      for u, v in (rng.choice(pairs) for _ in range(rng.randint(1, 4)))]
                lpa.update_edges(ch)
                self.check(lpa, g, s, t)

    def test_closures_and_restores_with_straight_line_heuristic(self):
        rng = random.Random(2)
        for _ in range(150):
            n = rng.randint(3, 14)
            g = random_geo_graph(rng, n, 4 * n, 4)
            s, t = rng.randrange(n), rng.randrange(n)
            h = straight_line_heuristic(g, t)
            self.assertTrue(is_consistent(g, h, t))
            base = [(u, v, w) for u in range(n) for v, w in g.out[u].items()]
            lpa = LPAStar(g, s, t, h)
            for _ in range(20):           # only slow down / delete / restore: h stays consistent
                ch = [(u, v, rng.choice([INF, w * rng.randint(2, 5), w]))
                      for u, v, w in rng.sample(base, min(3, len(base)))]
                lpa.update_edges(ch)
                self.check(lpa, g, s, t)
                self.assertEqual(astar(g, s, t, h), dijkstra(g, s)[t])

    def test_city_route_blocking_and_clearing(self):
        g = make_synthetic_city(30, 30, seed=3)
        s, t = 0, g.n - 1
        h = straight_line_heuristic(g, t)
        self.assertTrue(is_consistent(g, h, t))
        lpa = LPAStar(g, s, t, h)
        rng = random.Random(4)
        for _ in range(15):
            p = lpa.path()
            u, v = rng.choice(list(zip(p, p[1:])))
            w = g.out[u][v]
            lpa.update_edges([(u, v, w * 50)])
            self.check(lpa, g, s, t)
            self.assertNotIn((u, v), set(zip(lpa.path(), lpa.path()[1:])))
            lpa.update_edges([(u, v, w)])
            self.check(lpa, g, s, t)

    def test_snapshot_restore(self):
        g = make_synthetic_city(15, 15, seed=5)
        lpa = LPAStar(g, 0, g.n - 1)
        snap, d0 = lpa.snapshot(), lpa.distance()
        u, v = lpa.path()[1:3]
        w = g.out[u][v]
        lpa.update_edges([(u, v, INF)])
        g.set_weight(u, v, w)
        lpa.restore(snap)
        self.assertEqual(lpa.distance(), d0)
        self.check(lpa, g, 0, g.n - 1)

    def test_early_exit_dijkstra_and_astar(self):
        g = make_synthetic_city(25, 25, seed=6)
        ref = dijkstra(g, 3)
        rng = random.Random(7)
        for t in rng.sample(range(g.n), 25):
            self.assertEqual(dijkstra_to(g, 3, t), ref[t])
            self.assertEqual(astar(g, 3, t, straight_line_heuristic(g, t)), ref[t])

    def test_unreachable_target(self):
        g = Graph(3)
        g.add_edge(0, 1, 1)
        lpa = LPAStar(g, 0, 2)
        self.assertEqual(lpa.distance(), INF)
        self.assertEqual(lpa.path(), [])
        lpa.update_edges([(1, 2, 4)])
        self.assertEqual(lpa.path(), [0, 1, 2])
        self.assertEqual(astar(g, 0, 2, [0, 0, 0]), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
