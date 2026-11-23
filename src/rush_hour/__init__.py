"""Rush Hour Rerouting: dynamic single-source shortest paths on road networks.

Modules
  graph        Graph container, synthetic city, networkx/OSM conversion
  sssp         Dijkstra, DynamicSSSP (per-edge and batch repair, parent tree)
  lpa          A*, early-exit Dijkstra, Lifelong Planning A*
  disruptions  closure / accident / congestion generators
  osm          OpenStreetMap download and cached .graphml loading
  stats        structural graph statistics
"""
__version__ = "1.0.0"
