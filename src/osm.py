"""Real street networks from OpenStreetMap (via osmnx) or from cached .graphml files.

osmnx moved several functions between 1.x and 2.x (e.g. `add_edge_speeds` and
`add_edge_travel_times` live in `ox.routing` from 1.9/2.0 on, in `ox.speed` or at
top level before; graphml I/O is in `ox.io` in 2.x). `_ox` looks a function up in
all known locations, so both major versions work.

A cached .graphml can also be read **without osmnx** (plain networkx), so
`--graph-file` works offline on a machine that only has requirements.txt.
"""
import os
import re

from graph import from_networkx


def _ox(name):
    """Find an osmnx function across 1.x / 2.x module layouts."""
    import osmnx as ox
    for mod in ("routing", "speed", "io", "graph", None):
        obj = getattr(ox, mod, None) if mod else ox
        fn = getattr(obj, name, None) if obj is not None else None
        if callable(fn):
            return fn
    raise AttributeError(f"osmnx {getattr(ox, '__version__', '?')} has no function {name!r}")


def slug(place):
    return re.sub(r"[^a-z0-9]+", "_", place.lower()).strip("_")


def download(place, path):
    """Download the drivable network of `place`, add speeds and travel times, and
    save it as .graphml at `path`. Returns the networkx MultiDiGraph."""
    G = _ox("graph_from_place")(place, network_type="drive")
    G = _ox("add_edge_speeds")(G)
    G = _ox("add_edge_travel_times")(G)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _ox("save_graphml")(G, path)
    return G


def read_graphml(path):
    """Read a cached .graphml into a networkx graph, with osmnx if installed
    (typed attributes) and plain networkx otherwise (string attributes, which
    `from_networkx` converts)."""
    try:
        return _ox("load_graphml")(path)
    except ImportError:
        import networkx as nx
        return nx.read_graphml(path)


def load_graph_file(path):
    """Our Graph (largest SCC, deciseconds, local metric coordinates) from a .graphml."""
    return from_networkx(read_graphml(path), lonlat=True)


def load_osm(place, cache_dir="data"):
    """Download (or load the cached copy of) the drivable street network of a place."""
    path = os.path.join(cache_dir, slug(place) + ".graphml")
    if not os.path.exists(path):
        download(place, path)
    return load_graph_file(path)
