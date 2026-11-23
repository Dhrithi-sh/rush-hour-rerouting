"""Property-based tests (hypothesis): random graphs + random sequences of weight
increases, decreases and deletions, applied one by one or in batches. After every
step dist must equal a fresh Dijkstra, parent must be a valid shortest-path tree,
path_to must return a shortest path, and LPA* must agree on its target."""
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from rush_hour.graph import INF, Graph
from rush_hour.lpa import LPAStar
from rush_hour.sssp import DynamicSSSP, check_tree, dijkstra

WEIGHT = st.one_of(st.integers(1, 8), st.just(INF))       # INF = delete the road


@st.composite
def graphs(draw, max_n=12):
    n = draw(st.integers(2, max_n))
    edges = draw(st.lists(st.tuples(st.integers(0, n - 1), st.integers(0, n - 1), st.integers(1, 8)),
                          max_size=4 * n))
    g = Graph(n)
    for i in range(n):
        g.xy[i] = (float(i % 4), float(i // 4))
    for u, v, w in edges:
        if u != v:
            g.add_edge(u, v, w)
    return g


@st.composite
def scenarios(draw):
    g = draw(graphs())
    n = g.n
    s = draw(st.integers(0, n - 1))
    pair = st.tuples(st.integers(0, n - 1), st.integers(0, n - 1)).filter(lambda p: p[0] != p[1])
    change = st.builds(lambda p, w: (p[0], p[1], w), pair, WEIGHT)
    steps = draw(st.lists(st.tuples(st.booleans(), st.lists(change, min_size=1, max_size=6)),
                          min_size=1, max_size=15))
    return g, s, steps


def path_length(g, p):
    return sum(g.out[a][b] for a, b in zip(p, p[1:]))


SETTINGS = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(scenarios())
def test_single_and_batch_repair_match_dijkstra(sc):
    g, s, steps = sc
    dyn = DynamicSSSP(g, s)
    for batch, changes in steps:
        before = list(dyn.dist)
        if batch:
            count = dyn.update_edges(changes)
        else:
            count = sum(dyn.update_edge(u, v, w) for u, v, w in changes[:1])
        assert dyn.dist == dijkstra(g, s)
        check_tree(g, s, dyn.dist, dyn.parent)
        assert count == sum(a != b for a, b in zip(before, dyn.dist))


@SETTINGS
@given(scenarios())
def test_path_to_is_a_shortest_path(sc):
    g, s, steps = sc
    dyn = DynamicSSSP(g, s)
    for _, changes in steps:
        dyn.update_edges(changes)
        for t in range(g.n):
            p = dyn.path_to(t)
            if dyn.dist[t] == INF:
                assert p == []
            else:
                assert p[0] == s and p[-1] == t
                assert path_length(g, p) == dyn.dist[t]


@SETTINGS
@given(scenarios(), st.data())
def test_batch_equals_sequential(sc, data):
    g, s, steps = sc
    g2 = g.copy()
    a, b = DynamicSSSP(g, s), DynamicSSSP(g2, s)
    for _, changes in steps:
        a.update_edges(changes)
        for u, v, w in changes:
            b.update_edge(u, v, w)
        assert a.dist == b.dist


@SETTINGS
@given(scenarios(), st.data())
def test_lpa_star_matches_dijkstra(sc, data):
    g, s, steps = sc
    t = data.draw(st.integers(0, g.n - 1))
    lpa = LPAStar(g, s, t)                       # zero heuristic: valid for any weights
    for _, changes in steps:
        lpa.update_edges(changes)
        ref = dijkstra(g, s)[t]
        assert lpa.distance() == ref
        p = lpa.path()
        assert (p == []) if ref == INF else (p[0] == s and p[-1] == t and path_length(g, p) == ref)
