"""Download and cache the real street networks used in the cross-graph comparison.

    pip install -r requirements-osm.txt
    python scripts/fetch_cities.py                       # the default two cities
    python scripts/fetch_cities.py "Bologna, Italy" ...  # or any OSM place names

Each network is saved to data/<slug>.graphml (drivable roads, travel times added
by osmnx). `run_all.py` then picks up every data/*.graphml automatically, and
`--graph-file data/<slug>.graphml` uses one as the main graph, offline.
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))
from osm import download, load_graph_file, slug  # noqa: E402

# A small grid-like US city and an irregular European one (5k-30k nodes each).
DEFAULT_PLACES = ["Fargo, North Dakota, USA", "Bologna, Italy"]


def main(places):
    for place in places:
        path = os.path.join(ROOT, "data", slug(place) + ".graphml")
        if os.path.exists(path):
            print(f"cached: {path}")
        else:
            print(f"downloading {place!r} ...", flush=True)
            download(place, path)
        g = load_graph_file(path)
        print(f"  {place}: {g.n:,} nodes, {g.m:,} directed edges (largest SCC)")


if __name__ == "__main__":
    main(sys.argv[1:] or DEFAULT_PLACES)
