"""Build the Word report from results/*.csv, results/meta.json and results/*.png.

    python report/build_report.py [--results results] [--out report/Rush_Hour_Rerouting_Report.docx]

Every number and figure in the report is read from the results folder, so after
re-running the experiments on a different city just run this script again.
"""
import argparse
import json
import os
import shutil
import subprocess

import numpy as np
import pandas as pd
from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = os.path.dirname(os.path.abspath(__file__))
MODE_NAME = {"single": "scattered closures", "cluster": "accident zone",
             "wave": "congestion wave", "tree": "tree-edge closures"}
RANDOM_MODES = ["single", "cluster", "wave"]     # random placement (may hit no shortest path)


# ----------------------------------------------------------------- helpers
def shade(cell_or_par, fill):
    el = cell_or_par._tc if hasattr(cell_or_par, "_tc") else cell_or_par._p
    pr = el.get_or_add_tcPr() if hasattr(cell_or_par, "_tc") else el.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    pr.append(shd)


def add_page_number(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run()
    for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar"); el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText"); el.set(qn("xml:space"), "preserve"); el.text = text
        r._r.append(el)


class Doc:
    def __init__(self):
        self.d = Document()
        s = self.d.sections[0]
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(2.3)
        s.top_margin = s.bottom_margin = Cm(2.2)
        add_page_number(s)
        st = self.d.styles
        st["Normal"].font.name = "Calibri"; st["Normal"].font.size = Pt(11)
        st["Normal"].paragraph_format.space_after = Pt(6)
        st["Normal"].paragraph_format.line_spacing = 1.12
        for name, size, color in (("Heading 1", 16, "1F3864"), ("Heading 2", 13, "2F5496"),
                                  ("Heading 3", 11.5, "2F5496")):
            h = st[name]; h.font.name = "Calibri"; h.font.size = Pt(size); h.font.bold = True
            h.font.color.rgb = RGBColor.from_string(color)
            h.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
            h.paragraph_format.space_after = Pt(4); h.paragraph_format.keep_with_next = True
        self.fig_no = 0
        self.tab_no = 0

    def h(self, text, level=1):
        return self.d.add_heading(text, level)

    def p(self, text="", bold=False, italic=False, align=None, size=None, after=None):
        par = self.d.add_paragraph()
        self._runs(par, text, bold, italic, size)
        if align == "center":
            par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if after is not None:
            par.paragraph_format.space_after = Pt(after)
        return par

    def _runs(self, par, text, bold=False, italic=False, size=None):
        # inline markup: **bold**, *italic*, `code`
        import re
        for tok in re.split(r"(\*\*.+?\*\*|\*[^*\s][^*]*?\*|`[^`]+`)", text):
            if not tok:
                continue
            b, i, code = bold, italic, False
            if tok.startswith("**") and tok.endswith("**") and len(tok) > 4:
                tok, b = tok[2:-2], True
            elif tok.startswith("`") and tok.endswith("`") and len(tok) > 2:
                tok, code = tok[1:-1], True
            elif tok.startswith("*") and tok.endswith("*") and len(tok) > 2:
                tok, i = tok[1:-1], True
            r = par.add_run(tok)
            r.bold, r.italic = b, i
            if code:
                r.font.name = "Consolas"
            if size:
                r.font.size = Pt(size)

    def bullets(self, items, style="List Bullet"):
        for it in items:
            par = self.d.add_paragraph(style=style)
            self._runs(par, it)
            par.paragraph_format.space_after = Pt(2)

    def code(self, text):
        for line in text.strip("\n").split("\n"):
            par = self.d.add_paragraph()
            par.paragraph_format.space_after = Pt(0)
            par.paragraph_format.left_indent = Cm(0.4)
            par.paragraph_format.line_spacing = 1.0
            r = par.add_run(line if line else " ")
            r.font.name = "Courier New"; r.font.size = Pt(8.5)
            r._r.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "Courier New")
            shade(par, "F2F2F2")
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def note(self, text, fill="FFF4CE"):
        t = self.d.add_table(rows=1, cols=1)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        c = t.rows[0].cells[0]
        shade(c, fill)
        c.paragraphs[0].paragraph_format.space_after = Pt(2)
        self._runs(c.paragraphs[0], text, size=10)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def figure(self, path, caption, width_cm=15.5):
        if not os.path.exists(path):
            self.p(f"[missing figure: {os.path.basename(path)}]", italic=True)
            return
        self.fig_no += 1
        par = self.d.add_paragraph(); par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        par.paragraph_format.keep_with_next = True
        par.add_run().add_picture(path, width=Cm(width_cm))
        cp = self.d.add_paragraph(); cp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._runs(cp, f"**Figure {self.fig_no}.** {caption}", size=9.5)

    def table(self, header, rows, caption=None, widths=None, size=9.5):
        if caption:
            self.tab_no += 1
            cp = self.d.add_paragraph(); cp.paragraph_format.keep_with_next = True
            self._runs(cp, f"**Table {self.tab_no}.** {caption}", size=9.5)
        t = self.d.add_table(rows=1, cols=len(header))
        t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, htxt in enumerate(header):
            c = t.rows[0].cells[i]; shade(c, "D9E2F3")
            c.paragraphs[0].paragraph_format.space_after = Pt(0)
            self._runs(c.paragraphs[0], htxt, bold=True, size=size)
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].paragraphs[0].paragraph_format.space_after = Pt(0)
                self._runs(cells[i].paragraphs[0], str(v), size=size)
        if widths:
            for row in t.rows:
                for i, w in enumerate(widths):
                    row.cells[i].width = Cm(w)
        self.d.add_paragraph().paragraph_format.space_after = Pt(2)

    def save(self, path):
        self.d.save(path)


# ----------------------------------------------------------------- numbers
def x(v):
    if v is None or pd.isna(v):
        return "–"
    return f"{v:.0f}×" if v >= 10 else f"{v:.1f}×"


def ms(v):
    return f"{v:.2f} ms" if v < 10 else f"{v:.1f} ms"


def edges(v, hi):
    return f"≈ {v:.0f} edges" if v else f"not reached (> {hi} edges)"


class Results:
    def __init__(self, folder):
        self.f = folder
        self.meta = json.load(open(os.path.join(folder, "meta.json"), encoding="utf-8"))
        self.summ = pd.read_csv(os.path.join(folder, "summary_main.csv"))
        self.raw = pd.read_csv(os.path.join(folder, "raw_main.csv"))
        self.sc = pd.read_csv(os.path.join(folder, "raw_scaling.csv"))
        self.rp = pd.read_csv(os.path.join(folder, "raw_ripple.csv"))
        self.fleet = self.opt("raw_fleet.csv")
        self.p2p = self.opt("raw_p2p.csv")
        self.closure = self.opt("raw_closure.csv")
        self.marks = self.opt("raw_marks.csv")
        self.cross = self.opt("summary_crossgraph.csv")
        self.gstats = self.opt("graph_stats.csv")
        if self.gstats is None or not (self.gstats["source"] == "OpenStreetMap").any():
            self.cross = self.gstats = None      # no real network in this run: report says "not yet generated"
        self.sizes = sorted(self.summ["size"].unique())
        self.methods = list(self.summ["method"].unique())

    def opt(self, name):
        p = os.path.join(self.f, name)
        return pd.read_csv(p) if os.path.exists(p) else None

    def row(self, mode, size, phase="block", method="sequential"):
        r = self.summ[(self.summ["mode"] == mode) & (self.summ["size"] == size)
                      & (self.summ["phase"] == phase) & (self.summ["method"] == method)]
        return r.iloc[0]

    def xo(self, method="sequential", effective=False):
        """Crossover (break-even) points per mode from meta.json; None = not reached."""
        return self.meta["crossover"]["speedup_eff_med" if effective else "speedup_med"][method]

    def near(self, target):
        return min(self.sizes, key=lambda s: abs(np.log(s) - np.log(target)))

    def path(self, name):
        return os.path.join(self.f, name)


# ----------------------------------------------------------------- report
def build(R, out):
    M = R.meta
    n, m = M["n"], M["m"]
    synthetic = M["graph_source"].startswith("Synthetic")
    D = Doc()
    lo, mid, hi = R.sizes[0], R.near(10), R.sizes[-1]
    big = R.near(100)
    modes = [md for md in MODE_NAME if md in set(R.summ["mode"])]
    rmodes = [md for md in RANDOM_MODES if md in modes]
    has_batch = "batch" in R.methods
    xo, xo_eff = R.xo(), R.xo(effective=True)
    xob = R.xo("batch") if has_batch else {}
    noop1 = {md: R.row(md, lo)["frac_noop"] for md in rmodes}
    tree1 = R.row("tree", lo)
    spm = {md: R.row(md, mid)["speedup_med"] for md in modes}
    closure_delete = M.get("closure") == "delete"
    closure_txt = ("deleting the road (weight ∞)" if closure_delete
                   else f"multiplying its travel time by {M['block_factor']}")

    # ---------- title page
    D.p("", after=60)
    D.p("Rush Hour Rerouting", bold=True, align="center", size=30, after=2)
    D.p("How Fast Can a Map Heal Itself?", align="center", size=18, after=18)
    D.p("Incremental and batch repair of single-source shortest paths versus full recomputation "
        "on a road network under accidents and congestion",
        italic=True, align="center", size=12, after=30)
    D.p("Problem 11: Adaptive Path-Finding in Dynamic Weighted Graphs", align="center", size=12, after=40)
    D.p("Team: [Member A: Graph & Data Lead] · [Member B: Algorithms Lead] · "
        "[Member C: Theory Lead] · [Member D: Experiments & Visualisation Lead]",
        align="center", size=10.5, after=4)
    D.p("[Course / Institution] · [Date]", align="center", size=10.5)
    D.d.add_page_break()

    # ---------- abstract
    D.h("Abstract", 1)
    xo_pairs = []
    for md in modes:
        a, b = xo.get(md), xob.get(md)
        xo_pairs.append(f"{MODE_NAME[md]} {f'≈ {a:.0f}' if a else f'> {hi}'}"
                        + (f" → {f'≈ {b:.0f}' if b else f'> {hi}'}" if has_batch else ""))
    D.p(f"When accidents or congestion change travel times on a road network, a routing service must "
        f"update its shortest-path tree. The textbook response is to rerun Dijkstra’s algorithm from "
        f"scratch; an incremental alternative in the style of Ramalingam and Reps re-examines only the "
        f"nodes whose distance actually changes. We implement per-edge repair, a new *batch repair* that "
        f"handles a whole disruption in one sweep, and LPA* for single-destination rerouting; we prove the "
        f"repair algorithms correct, analyse their output-sensitive cost, and benchmark them on a road graph "
        f"with {n:,} nodes and {m:,} directed edges under four disruption models. Random single-road closures "
        f"are misleading: {100 * min(noop1.values()):.0f}–{100 * max(noop1.values()):.0f}% of them hit no "
        f"shortest path, so repair stops after one comparison; we therefore separate *effective* updates "
        f"(at least one distance changes) from no-ops. Blocking one shortest-path-tree edge, repair was "
        f"{x(tree1['speedup_eff_med'])} faster than full recomputation (median over {M['trials']} trials, each "
        f"itself the median of repeated runs). The advantage shrinks as disruptions grow; the break-even size "
        f"in changed edges, per-edge → batch, is: " + "; ".join(xo_pairs) + ". "
        + (_fleet_abstract(R) if R.fleet is not None else "")
        + (_p2p_abstract(R) if R.p2p is not None else "")
        + (_cross_abstract(R) if R.cross is not None else
           "Real-city results have not been generated yet (Section 5.10). ")
        + f"Every repaired result was checked against a fresh Dijkstra run "
          f"({M['equality_checks_passed']:,} checks, zero mismatches).")

    # ---------- 1 problem statement
    D.h("1. Problem statement", 1)
    D.p("**Setting.** A road network is a directed graph G = (V, E) with n = |V| nodes (intersections), "
        "m = |E| edges (road segments) and a strictly positive integer travel time w(e) on every edge. "
        "A fixed source s (a depot) is given. The routing service maintains d(v), the shortest travel time "
        "from s to every node v, together with a shortest-path tree (a parent pointer per node), from "
        "which the route to any destination can be read off.")
    D.p("**Updates.** A disruption is a batch of k edge-weight changes (u₁,v₁,w′₁), …, (u_k,v_k,w′_k). "
        "Accidents and congestion increase weights; a closed road can either keep a large finite weight or "
        "be deleted (w′ = ∞); clearing a disruption restores the original weights.")
    D.p("**Goal.** After a disruption, restore the exact distances d′(v) and a valid shortest-path tree. "
        "Three strategies are compared:")
    D.bullets(["**Full recomputation:** apply the new weights and run Dijkstra from s, in "
               "O((n + m) log n) time regardless of how little changed.",
               "**Per-edge repair:** process the k updates one by one, each touching only the nodes whose "
               "distance changes.",
               "**Batch repair:** process all k updates together with one affected-set sweep and one "
               "Dijkstra pass."])
    D.p("**Research questions.**")
    D.bullets(["RQ1. How does the speed-up of repair over recomputation depend on disruption size and shape, "
               "once no-op updates are separated out?",
               "RQ2. At what disruption size does recomputing become the better choice (the break-even point), "
               "and how far does batch repair move it?",
               "RQ3. How do the methods scale with the size n of the network?",
               "RQ4. Which road closures cause large ripples, and can the ripple size be predicted?",
               "RQ5. What does a disruption mean for a delivery fleet: how many routes change and by how much?",
               "RQ6. For a single destination, is a goal-directed incremental method (LPA*) better than "
               "repairing the whole tree or than A* from scratch?",
               "RQ7. Do the conclusions hold on real street networks?"])
    D.p("**Scope.** Single static source, strictly positive integer weights, edge deletions and "
        "re-insertions (but no new nodes). Multiple sources, time-dependent weights and lazy repair are left "
        "as future work (Section 8).")

    # ---------- 2 algorithms
    D.h("2. Algorithms", 1)
    D.h("2.1 Baseline: full Dijkstra", 2)
    D.p("The baseline recomputes all distances and parent pointers with Dijkstra’s algorithm using a binary "
        "heap (lazy deletion), in O((n + m) log n) time. A minimal distance-only Dijkstra is also the test oracle.")
    D.h("2.2 Terminology", 2)
    D.p("An edge (a,b) is **tight** if d(a) + w(a,b) = d(b). Because weights are positive, d strictly "
        "increases along tight edges, so the tight edges form a directed acyclic graph (the *tight DAG*) "
        "in which every reachable node v ≠ s has at least one tight in-edge, and every shortest path "
        "consists of tight edges only. Integer weights make the tightness test exact. A **shortest-path tree** "
        "picks one tight in-edge, the parent edge, for every reachable node.")
    D.h("2.3 Per-edge incremental repair", 2)
    D.p("To change the weight of edge e = (u,v) from w to w′ we distinguish two cases.")
    D.p("**Case A: w′ < w (road gets faster, e.g. an accident is cleared or a road re-opens).** Only the "
        "improvement that enters through v can spread. If d(u) + w′ ≥ d(v) nothing changes; otherwise set "
        "d(v) = d(u) + w′ and run a Dijkstra-style propagation from v that relaxes outgoing edges, stops "
        "wherever no improvement occurs, and sets the parent of every improved node to the node that improved it.")
    D.code("""
DECREASE(u, v, w'):
    if d[u] + w' >= d[v]: return 0
    d[v] <- d[u] + w';  parent[v] <- u;  H <- heap{(d[v], v)};  changed <- 0
    while H not empty:
        (dx, x) <- pop-min(H);  if dx > d[x]: continue
        changed++
        for each edge (x, z, wz):
            if dx + wz < d[z]:  d[z] <- dx + wz;  parent[z] <- x;  push(H, (d[z], z))
    return changed""")
    D.p("**Case B: w′ > w (road gets slower or is deleted).** If e was not tight, no shortest path used "
        "it and nothing changes. Otherwise the repair has two phases: (1) find the **affected set A**, the "
        "nodes that lose every tight path from s, by scanning candidates in increasing order of old "
        "distance; a candidate that keeps a tight parent outside A keeps its distance and its parent pointer "
        "is moved to that parent; (2) recompute distances inside A with a Dijkstra run seeded from the "
        "unaffected boundary.")
    D.code("""
INCREASE(u, v, w_old):                      // new weight already in G (inf = deleted)
    if e was not tight: return 0
    A <- AFFECTED({v});  RESOLVE(A);  return |A|

AFFECTED(seeds):                            // Phase 1
    A <- {};  H <- heap{(d[x], x) : x in seeds};  queued <- seeds
    while H not empty:
        (dx, x) <- pop-min(H)
        if exists in-edge (y, x, wy) with y not in A and d[y] + wy = dx:
            parent[x] <- y;  continue                          // still supported
        A <- A + {x}
        for each out-edge (x, z, wz) with dx + wz = d[z] and z not queued:
            queued <- queued + {z};  push(H, (d[z], z))
    return A

RESOLVE(A):                                 // Phase 2
    for x in A:  (d[x], parent[x]) <- best in-edge (y,x) with y not in A   // (inf, -1) if none
    H <- heap of {(d[x], x) : x in A, d[x] < inf}
    while H not empty:
        (dx, x) <- pop-min(H);  if dx > d[x]: continue
        for each out-edge (x, z, wz) with z in A:
            if dx + wz < d[z]:  d[z] <- dx + wz;  parent[z] <- x;  push(H, (d[z], z))""")
    D.p("A disruption with k edge changes is repaired by calling the appropriate routine k times. Both "
        "routines return the exact number of nodes whose distance changed, the quantity |δ| used in the "
        "analysis. `path_to(t)` follows parent pointers from t back to s in O(path length).")
    D.h("2.4 Batch repair", 2)
    D.p("Per-edge repair handles the k changes of an accident zone one at a time, so a node that lies below "
        "several blocked roads is re-solved several times, and intermediate distances that are immediately "
        "overwritten still cost work. **Batch repair** (`update_edges`) handles the whole batch at once:")
    D.code("""
UPDATE-EDGES(changes):
    split changes into increases INC (w' > w) and decreases DEC (w' < w)
    apply INC to G                                            // G1 = old weights + increases
    seeds <- { v : (u, v) in INC and d[u] + w_old(u,v) = d[v] }   // heads of tight increased edges
    A <- AFFECTED(seeds)                                      // one Phase-1 sweep, union of affected sets
    apply DEC to G                                            // G2 = final weights
    for x in A:  (d[x], parent[x]) <- best in-edge (y,x) with y not in A;  push finite ones
    for (u, v, w') in DEC:  if d[u] + w' < d[v]:  d[v] <- d[u] + w';  parent[v] <- u;  push v
    run Dijkstra from the heap, relaxing ALL out-edges (not only those into A)
    return number of nodes whose final d differs from the old d""")
    D.p("The order matters: the affected set is computed on G1, before the decreases are applied, so that "
        "tightness is judged with the old weights of decreased edges; and A is re-seeded before decreased "
        "edges are relaxed, because the stale (too small) old labels inside A must never be propagated. "
        "The correctness argument is Theorem 2 in Section 3.")
    D.h("2.5 Road closures as deletions", 2)
    D.p("A closure can be modelled as a large finite weight or as a true deletion. Deletion is supported "
        "throughout: `Graph.set_weight(u, v, ∞)` removes the edge from both adjacency maps, and a later "
        "finite weight re-inserts it. For the repair this is just an increase to ∞: the deleted edge no "
        "longer appears among in-edges, so it can never support a node, and nodes of A with no remaining "
        "in-edge from outside A get d = ∞ and parent −1 (they are unreachable). Re-opening is a decrease from "
        f"∞. The experiments in this report use the **{M.get('closure', 'factor')}** model "
        f"(a blocked road is handled by {closure_txt}); Section 5.9 compares both models on identical disruptions.")
    D.h("2.6 Point-to-point rerouting: A* and LPA*", 2)
    D.p("A single vehicle only needs the route to its own destination t. Two goal-directed methods use a "
        "heuristic h(x) that never overestimates the remaining travel time: **A\\*** recomputes from scratch, "
        "and **LPA\\*** (Lifelong Planning A*, Koenig, Likhachev and Furcy) keeps its search state between "
        "changes and re-expands only *locally inconsistent* nodes (whose estimate g differs from the one-step "
        "lookahead rhs) whose key beats the target’s. Our heuristic is the straight-line distance to t divided "
        "by the fastest ‘distance per unit travel time’ of any edge in the network, i.e. distance / maximum speed. "
        "Taking the maximum over the graph’s own edges (rather than a nominal speed limit) makes h exactly "
        "consistent despite the rounding of travel times to deciseconds; it stays consistent under closures "
        "and congestion because they only make roads slower. LPA* is implemented in its own module "
        "(`src/lpa.py`) with separate tests.")
    D.h("2.7 Disruption models", 2)
    D.bullets(["**Scattered closures:** k independent random edges are blocked.",
               "**Accident zone:** k connected edges around a random point (BFS order) are blocked.",
               "**Congestion wave:** k connected edges around a random epicentre are slowed by a factor "
               "1 + 9·e^(−h/2), where h is the hop distance from the epicentre, so the effect fades with distance.",
               "**Tree-edge closures:** k edges of the current shortest-path tree are blocked. Every such road "
               "carries at least one shortest path, so these updates are almost never no-ops; this is the "
               "worst-case-relevant curve for random closures.",
               "Every disruption is followed by a **clearing phase** that restores the original weights "
               "(weight decreases), so both repair cases are measured."])
    D.h("2.8 Implementation", 2)
    D.p("Pure Python (adjacency dictionaries in both directions, `heapq` as priority queue); numpy and pandas "
        "are used only for analysis. Travel times are integer deciseconds. Membership of the affected set is "
        "recorded with generation-stamped arrays instead of a fresh Python `set()` per call (Section 5.11 "
        "measures the difference). Source: `src/sssp.py` (Dijkstra, per-edge and batch repair), `src/lpa.py` "
        "(A*, LPA*), `src/disruptions.py`, `src/graph.py`.")

    # ---------- 3 proof
    D.h("3. Proof of correctness", 1)
    D.p("Notation: d is the distance function before an update and d′ after it; "
        "e = (u,v) is the changed edge, with old weight w and new weight w′ (possibly ∞). All finite weights "
        "are positive integers. Distances are ∞ for unreachable nodes.")
    D.p("**Fact 1 (Bellman characterisation).** With positive weights, d is the shortest-distance function "
        "iff d(s) = 0 and d(x) = min over in-edges (y,x) of d(y) + w(y,x) for all x ≠ s. "
        "*Proof sketch.* Such a d is an upper bound on shortest distances (follow minimising in-edges backwards; "
        "d strictly decreases, so the walk ends at s and is a path of length d(x)); and for any path "
        "P from s to x, induction along P with d(b) ≤ d(a) + w(a,b) gives d(x) ≤ |P|. ∎")
    D.p("**Lemma 1 (decrease).** For w′ < w, DECREASE leaves d equal to d′.")
    D.p("*Proof.* First, d′(u) = d(u): a shortest path to u that used e would contain a cycle through u of "
        "positive length. If d(u) + w′ ≥ d(v), then no path through e beats d(v), so d′ = d and the early "
        "return is correct. Otherwise the only violated inequality is on e. Let the heap-based loop run; "
        "we claim every node popped with a valid entry carries its final distance d′. Suppose not and let "
        "x be the first such node, popped with label ℓ(x) > d′(x). A shortest new path P to x must use e "
        "(otherwise d′(x) = |P| ≥ d(x) ≥ ℓ(x)). Let y be the first node on P after u whose label has not "
        "been finalised. Its predecessor on P is either u (with d′(u) = d(u), so ℓ(v) ≤ d(u) + w′) or an "
        "already-correct node that relaxed y, hence ℓ(y) ≤ d′(y) ≤ d′(x) < ℓ(x). Thus y is in the heap with a "
        "smaller key than x and would be popped first, contradicting the choice of x (or y = x, contradicting "
        "ℓ(x) > d′(x)). Finally, a node never reached by the loop has d′(x) = d(x): otherwise its shortest "
        "new path would use e, and by the same induction along that path every node on it, including x, "
        "would have been improved. ∎")
    D.p("**Lemma 2 (non-tight increase).** If w′ > w and e is not tight, d′ = d.")
    D.p("*Proof.* Every d(x) is realised by a path of tight edges, none of which is e, so its length is "
        "unchanged: d′(x) ≤ d(x). Weights only grew, so d′(x) ≥ d(x). ∎")
    D.p("**Lemma 3 (unaffected nodes).** Let a set I of edges be made heavier (possibly deleted), let T be "
        "the set of edges that are tight with respect to d *and not in I* (with unchanged weight), and call x "
        "*T-reachable* if x = s or x is reachable from s along T. Then d′(x) = d(x) if and only if x is T-reachable.")
    D.p("*Proof.* (⇐) A T-path has the same length d(x) under the new weights, and d′ ≥ d. (⇒) If d′(x) = d(x) "
        "< ∞, take a new shortest path P of length d(x). Since d(b) ≤ d(a) + w(a,b) ≤ d(a) + w′(a,b) for every "
        "edge and the sum telescopes to d(x), every edge of P is tight with respect to d and has w′ = w; so "
        "P ⊆ T. ∎  (With I = {e} this is the single-edge case.)")
    D.p("Define the **affected set** A = {x : d(x) < ∞ and x is not T-reachable}. By Lemma 3 these are exactly "
        "the nodes whose distance changes, and for them d′(x) > d(x) (possibly ∞).")
    D.p("**Lemma 4 (Phase 1 computes A).** If the heads of all tight edges in I are the seeds, AFFECTED returns exactly A.")
    D.p("*Proof.* We process candidates in nondecreasing old distance. Because weights are positive, every tight "
        "parent of x has strictly smaller old distance. By induction on this order, when x is popped all nodes "
        "with smaller distance have been classified correctly. A node x ≠ s is T-reachable iff it has a T-edge "
        "(y,x) from a T-reachable y, i.e. a tight in-edge with unchanged weight from a node outside A; edges in I "
        "fail the test because d(y) + w′ > d(x) (a deleted edge is not in the adjacency at all). This is exactly "
        "the test in the loop, so popped nodes are classified correctly. It remains to show that every node of "
        "A is pushed. Take x ∈ A with minimal distance among unpushed members of A and any tight in-edge (p,x). "
        "If (p,x) ∈ I, x is a seed. Otherwise (p,x) ∈ T, so p ∉ A would make x T-reachable; hence p ∈ A has "
        "smaller distance, was pushed and classified into A, and its classification pushed x as a tight child — "
        "contradiction. ∎")
    D.p("**Lemma 5 (Phase 2 computes d′ on A).** After RESOLVE, d(x) = d′(x) for all x.")
    D.p("*Proof.* Nodes outside A keep d′ = d (Lemma 3). For x ∈ A, consider a new shortest path to x and its "
        "last node y outside A (it exists since s ∉ A); the rest of the path lies inside A. Hence d′(x) is the "
        "shortest distance in the subgraph induced by A with initial labels min over y ∉ A of d(y) + w′(y,x), "
        "a multi-source Dijkstra with positive weights. If no such path exists, d′(x) = ∞, which is what the "
        "seeding assigns and no relaxation changes. ∎")
    D.p("**Lemma 6 (parent pointers).** After every update, each reachable x ≠ s has a parent p with "
        "d(p) + w(p,x) = d(x), and unreachable nodes have parent −1.")
    D.p("*Proof.* Decrease: every improved node gets the node that improved it, which is tight at the end by "
        "Lemma 1; a node whose parent improved has itself improved (otherwise its parent edge would be violated "
        "after the propagation). Increase: a node whose parent is in A, or whose parent edge was increased, is "
        "pushed in Phase 1 (it is a tight child of a node of A, or a seed); if it is supported it is re-pointed "
        "to the supporting node, which keeps its distance; if it joins A it gets a new parent in Phase 2, which "
        "is tight because labels only shrink to final values along relaxed edges. All other parent pointers "
        "point to nodes outside A along unchanged tight edges. ∎")
    D.p("**Theorem 1.** After any single edge-weight update, `update_edge` leaves `dist` equal to the "
        "shortest-path distances of the new graph and `parent` a valid shortest-path tree; by induction the same "
        "holds after any sequence of updates. *Proof.* Lemma 1 covers decreases, Lemmas 2–5 increases (including "
        "deletions), Lemma 6 the parent pointers; equal weights are no-ops. ∎")
    D.p("**Theorem 2 (batch repair).** `update_edges` leaves `dist` equal to the distances d₂ of the final graph G2.")
    D.p("*Proof.* Let G1 be the old graph with only the increases applied, and d₁ its distances. Step 1: by "
        "Lemmas 3 and 4 with I = all increased edges, AFFECTED returns exactly the set A of nodes with "
        "d₁(x) > d(x); all other nodes have d(x) = d₁(x). Step 2 applies the decreases, so every edge now has "
        "w₂ ≤ w₁. Labels: outside A the label d₁(x) is the length of a real walk in G1 that uses no "
        "decreased edge at a larger weight than in G2, so it is ≥ d₂(x); inside A the seeded label is "
        "d(y) + w₂(y,x) for a node y outside A, again the length of a walk in G2. Relaxations only ever set a "
        "label to (label of a node) + (edge weight). Hence **(i) every label is always an upper bound on d₂**. "
        "Now call an edge (y,x) *violated* if label(y) + w₂(y,x) < label(x). When the final Dijkstra starts, "
        "a violated edge (y,x) must (a) end in A with y ∈ A — then y has a finite label and is in the heap; or "
        "(b) start in A and leave it — impossible for an unchanged or increased edge, because d₁(x) ≤ d₁(y) + w₁ "
        "and label(y) ≥ d₁(y) — so it is a decreased edge, and y is in the heap; or (c) lie outside A — then "
        "d₁(x) ≤ d₁(y) + w₁(y,x), so it is a decreased edge, and it has just been relaxed; (d) edges entering A "
        "from outside are not violated by the choice of seeds. So **(ii) every violated edge has its tail in "
        "the heap**, and popping a node and relaxing all of its out-edges preserves (ii). When the heap is empty "
        "no edge is violated, so by induction along any shortest path of G2 (from s, whose label is 0) every "
        "label is at most d₂. With (i), label = d₂ everywhere. Because heap keys never decrease (positive "
        "weights), each node is settled at most once, as in Dijkstra. Parent pointers are maintained exactly as "
        "in Lemma 6. ∎")
    D.p("The count returned by `update_edges` compares each touched node’s final distance with its value before "
        "the batch, so a node that is first delayed by an increase and then restored by a decrease of the same "
        "batch is (correctly) not counted.")
    D.p(f"**Empirical validation.** The test suite compares every repair method with Dijkstra after every "
        f"update on hundreds of random graphs (including unreachable nodes, deletions, heavy ties and mixed "
        f"batches), property-based tests generate further random graphs and update sequences, and the benchmark "
        f"harness asserts equality after every one of its {M['equality_checks_passed']:,} repairs and validates "
        f"the parent array. No mismatch was ever observed.")

    # ---------- 4 complexity
    D.h("4. Complexity analysis", 1)
    D.p("Let δ be the set of nodes whose distance changes (δ = A for increases, the improved nodes for "
        "decreases) and let Δ be the maximum degree. Road networks have small Δ (typically ≤ 8–10).")
    D.bullets([
        "**Full recomputation:** O((n + m) log n) per disruption with a binary heap (O(m + n log n) with a Fibonacci heap).",
        "**Decrease repair:** each improved node is finalised once and scans its out-edges: O(Δ|δ| log(Δ|δ|)).",
        "**Increase repair, Phase 1:** each node of A and each of its tight children (the *boundary*, at most Δ|A| nodes) "
        "is popped once and scans at most Δ edges: O(Δ²|A| log |A|).",
        "**Increase repair, Phase 2:** heap operations are bounded by the edges incident to A: O(Δ|A| log |A|).",
        "**Batch repair:** one Phase-1 sweep over the union A = ∪Aᵢ plus one Dijkstra over the nodes whose final "
        "distance changes and their out-edges: O(Δ²|A| log |A| + Δ|δ| log(Δ|δ|) + k). Per-edge repair instead "
        "pays Σᵢ |Aᵢ| (and the transient changes of every intermediate state), which can be up to k times more "
        "when the affected sets overlap — exactly the situation in an accident zone.",
        "**Extra space:** O(n) for the generation-stamped marks (allocated once), O(|A|) for the heap.",
    ])
    D.p("So repair is **output-sensitive**: it costs Õ(|δ|) for bounded-degree graphs and does not depend "
        "on n, whereas recomputation always pays Θ(n log n). This is the notion of boundedness studied by "
        "Ramalingam and Reps.")
    D.p("**Worst case.** Repair has no better worst case than recomputation. Let s have one cheap edge e "
        "to the rest of the graph (weight 1) and an expensive alternative (weight 100). Raising w(e) changes "
        "all n − 1 distances, so |δ| = Θ(n) and repair costs Θ(n log n), with larger constants than a plain "
        "Dijkstra. For k per-edge updates the total cost is Σᵢ|δᵢ| log n versus one Dijkstra run, so the "
        "break-even occurs roughly when the summed affected sizes reach a constant fraction of n; batch repair "
        "replaces the sum by the size of the union.")
    D.p("**Expected case on road-like graphs.** For a tree edge (p,v) of the shortest-path tree, the subtree "
        "below v is an upper bound on |A|, and Σ_v subtree(v) equals the sum of node depths in the tree. "
        "Hence the *average* subtree size is the average hop-depth of the tree, which is Θ(√n) for planar, "
        "grid-like networks of diameter Θ(√n). A random closure that hits the tree thus costs about "
        "Θ(√n log n), versus Θ(n log n) for recomputation, so the advantage should grow roughly like √n. "
        "This is a heuristic estimate, not a theorem; Section 5.4 tests it.")
    D.p("**LPA\\*.** Each expansion costs O(Δ log n) (its rhs recomputation scans in-edges). After a change it "
        "expands the inconsistent nodes whose key is below the target’s; with a perfect heuristic that is close "
        "to the nodes near the new route, but under-consistent nodes (whose distance grew) are expanded twice, "
        "and a closure near the source can invalidate a large part of the search tree.")

    # ---------- 5 experiments
    D.h("5. Experiments and results", 1)
    D.h("5.1 Setup", 2)
    D.p(f"**Graph.** {M['graph_source']}; after restricting to the largest strongly connected component the "
        f"graph has n = {n:,} nodes and m = {m:,} directed edges. Weights are travel times in integer deciseconds. "
        f"The source is the node closest to the map centroid (depot). Blocked roads are handled by {closure_txt}.")
    if synthetic:
        D.note("**Data note.** The main experiments (Sections 5.2–5.9) use a *synthetic* city (perturbed street "
               "grid with arterial roads, one-way streets and a river crossed by four bridges), so that every run is "
               "reproducible offline. Section 5.10 repeats the core experiment on real OpenStreetMap networks"
               + (" ." if R.cross is not None else "; those results still need to be generated (see Appendix B)."))
    D.p(f"**Protocol.** For each disruption model and each size k in {{{', '.join(map(str, R.sizes))}}} we ran "
        f"{M['trials']} independent trials with random disruption locations. In each trial we (1) timed a full "
        f"Dijkstra on the disrupted graph, (2) applied the disruption with each repair method and timed it, "
        f"(3) asserted that every method’s distance array equals Dijkstra’s and that its parent array is a valid "
        f"shortest-path tree, then repeated this for the clearing phase. Short operations are noisy, so every "
        f"timing is repeated: repair runs until it has accumulated at least {1e3 * M['timing']['min_total_s']:.0f} ms "
        f"({M['timing']['min_reps']}–{M['timing']['max_reps']} runs), Dijkstra {M['timing']['full_reps']} times, and "
        f"the per-trial time is the median of those runs. Between repeats the graph and the distance and parent "
        f"arrays are restored to the exact pre-disruption state (asserted). We report medians and inter-quartile "
        f"ranges (IQR) over trials of the per-trial speed-up t_Dijkstra / t_repair, over *all* trials and over "
        f"*effective* trials only (at least one distance changed), together with the fraction of no-op trials. "
        f"Garbage collection was disabled during timing. Python {M['python']} on a single core.")
    D.note("**Reading the numbers.** Absolute times come from a pure-Python implementation and will differ in "
           "C++ or Rust; the *ratios* and the shape of the curves are what matters (see Section 6).", fill="E8F1FA")

    # 5.2
    D.h("5.2 Speed-up versus disruption size; effective versus no-op updates (RQ1)", 2)
    sizes_show = sorted({lo, R.near(5), mid, R.near(50), big, hi})

    def cell(rr):
        return f"{x(rr['speedup_med'])} / {x(rr['speedup_eff_med'])}  ({100 * rr['frac_noop']:.0f}%)"

    rows = [[k] + [cell(R.row(md, k)) for md in modes] for k in sizes_show]
    D.table(["Edges changed"] + [MODE_NAME[md].capitalize() for md in modes], rows,
            caption="Median speed-up of per-edge repair over full Dijkstra when blocking roads: all trials / "
                    "effective trials only (percentage of no-op trials in brackets; “–” = no effective trial).",
            widths=[2.4] + [3.6] * len(modes), size=8.5)
    eff_from = next((k for k in R.sizes if all(R.row(md, k)["frac_noop"] < 0.05 for md in rmodes)), None)
    noop_sp = [f"{x(R.row(md, lo)['speedup_noop_med'])} for {MODE_NAME[md]}" for md in rmodes
               if not pd.isna(R.row(md, lo)["speedup_noop_med"])]
    D.p("**Effective versus no-op updates.** At size "
        + f"{lo}, " + ", ".join(f"{100 * noop1[md]:.0f}% of the trials with {MODE_NAME[md]}" for md in rmodes)
        + " changed no distance at all: the blocked road was not on any shortest path, so repair "
        "correctly stopped after one comparison. Such trials take microseconds and inflate the median "
        "speed-up enormously" + (f" (median speed-up of the no-op trials alone: {', '.join(noop_sp)})" if noop_sp else "")
        + ". " + (f"The no-op fraction drops quickly with size (Table 1): from {eff_from} edges on, fewer than 5% of "
                  "the trials of every random model are no-ops and the two numbers agree. " if eff_from else
                  "Even at the largest tested size some random trials were no-ops (Table 1). ")
        + "The *tree-edge closures* avoid the problem by construction (no-op fraction at size "
        f"{lo}: {100 * tree1['frac_noop']:.0f}%); they are the honest curve for “a road that matters is blocked”, "
        f"and there a single closure was repaired {x(tree1['speedup_eff_med'])} faster than recomputation.")
    D.figure(R.path("fig1_speedup_vs_size.png"),
             "Median speed-up versus disruption size, one panel per disruption model (blocking phase). "
             "Blue: per-edge repair, red: batch repair. Solid: all trials (band = IQR); dotted: effective trials "
             "only. Above the black line repair is faster than full Dijkstra.")
    parts = []
    for md in modes:
        a, b, c = R.row(md, lo)["speedup_med"], R.row(md, big)["speedup_med"], R.row(md, hi)["speedup_med"]
        parts.append(f"for the {MODE_NAME[md]} {x(a)} at {lo} edge{'s' if lo > 1 else ''}, {x(b)} at {big} edges and "
                     f"{x(c)} at {hi} edges")
    D.p("With per-edge repair the speed-up falls steadily as more edges change: " + "; ".join(parts) + ".")
    cl_hi = R.row("cluster", hi, "clear")["speedup_med"]
    bl_hi = R.row("cluster", hi, "block")["speedup_med"]
    faster = sum(R.row(md, k, "clear")["speedup_med"] > R.row(md, k, "block")["speedup_med"]
                 for md in modes for k in R.sizes)
    total = len(modes) * len(R.sizes)
    if faster >= 0.6 * total:
        D.p(f"The **clearing phase** shows a higher speed-up than the blocking phase in {faster} of "
            f"{total} settings (accident zone at {hi} edges: {x(cl_hi)} vs {x(bl_hi)}). This is plausible because weight "
            f"decreases only propagate improvements, while increases must first identify the affected set and "
            f"then re-solve it.")
    else:
        D.p(f"The **clearing phase** did not show a consistent advantage over the blocking phase "
            f"(higher speed-up in {faster} of {total} settings; accident zone at {hi} edges: {x(cl_hi)} vs {x(bl_hi)}).")
    D.figure(R.path("fig2_runtime_vs_size.png"),
             "Median time per disruption (bands = IQR over trials; dotted = effective trials only). Dijkstra’s cost "
             "is flat; repair cost grows with the size of the disruption.")
    D.figure(R.path("fig3_affected_fraction.png"),
             "Mean percentage of nodes whose shortest-path distance changes. Repair work is proportional to this quantity.", 12.5)

    # 5.3 batch
    D.h("5.3 Break-even points and batch repair (RQ2)", 2)
    if has_batch:
        rows = []
        xbe = R.xo("batch", effective=True)
        for md in modes:
            rows.append([MODE_NAME[md].capitalize(), edges(xo.get(md), hi), edges(xo_eff.get(md), hi),
                         edges(xob.get(md), hi), edges(xbe.get(md), hi)])
        D.table(["Disruption model", "Per-edge: all", "Per-edge: effective", "Batch: all", "Batch: effective"], rows,
                caption="Break-even disruption size (median speed-up = 1, log–log interpolation) for per-edge and "
                        "batch repair, counting all trials or only effective ones.",
                widths=[3.6, 3.1, 3.1, 3.1, 3.1], size=8.5)
        ratio = {md: R.row(md, hi, method="sequential")["t_repair_ms"] / R.row(md, hi, method="batch")["t_repair_ms"]
                 for md in modes}
        ratio_lo = {md: R.row(md, lo, method="sequential")["t_repair_ms"] / R.row(md, lo, method="batch")["t_repair_ms"]
                    for md in modes}
        best = max(modes, key=lambda md: ratio[md])
        D.p(f"At {hi} changed edges, batch repair was "
            + ", ".join(f"{x(ratio[md])} faster than per-edge repair for the {MODE_NAME[md]}" for md in modes)
            + f" (median times). The gain is largest for the {MODE_NAME[best]}. "
            + ("Connected disruptions block many edges above the same few shortest-path subtrees, so per-edge "
               "repair re-solves the same region again and again, while batch repair computes the union of the "
               "affected sets once. "
               if best in ("cluster", "wave") else
               "Whenever affected sets overlap, per-edge repair re-solves the same region repeatedly, while batch "
               "repair computes their union once. ")
            + ("For scattered closures the affected sets rarely overlap and the gain is smallest. "
               if min(modes, key=lambda md: ratio[md]) == "single" else "")
            + "For single-edge disruptions the batch routine only adds bookkeeping (median time ratio per-edge / "
            "batch at size " + f"{lo}: " + ", ".join(f"{MODE_NAME[md]} {ratio_lo[md]:.2f}" for md in modes)
            + (", i.e. per-edge repair is faster there), so a system would call the per-edge routine for isolated "
               "incidents and the batch routine for multi-edge ones."
               if all(ratio_lo[md] < 1 for md in modes) else ")."))
        D.p("The no-op split barely moves the break-even points (compare the ‘all’ and ‘effective’ columns), "
            "because no-op trials have disappeared long before the break-even sizes; it matters for the headline "
            "speed-ups at small sizes, not for the crossover.")
    D.p("Beyond the break-even point it is cheaper to recompute from scratch; a system could switch strategy "
        "based on the number of changed edges, or on a running estimate of |A|.")

    # 5.4 scaling
    D.h("5.4 Scaling with network size (RQ3)", 2)
    sc = R.sc[R.sc["method"] == "sequential"] if "method" in R.sc else R.sc
    one = sc[sc["scenario"] == "single tree-edge closure"].groupby("n").median(numeric_only=True).sort_index()
    mean_net = sc[sc["scenario"] == "single tree-edge closure"].groupby("n")["net"].mean().sort_index()
    n0, n1 = int(one.index[0]), int(one.index[-1])
    rf = one["t_full"].iloc[-1] / one["t_full"].iloc[0]
    rr_ = one["t_repair"].iloc[-1] / max(one["t_repair"].iloc[0], 1e-9)
    a0, a1 = float(mean_net.iloc[0]), float(mean_net.iloc[-1])
    D.p(f"Using synthetic cities of {n0:,} to {n1:,} nodes (a {n1 / n0:.0f}-fold increase), the median time of full "
        f"Dijkstra for a single-road disruption (blocking a shortest-path-tree edge) grew by a factor of {rf:.0f}, "
        f"whereas the median repair time changed by a factor of {rr_:.1f}: the typical tree edge lies close to a "
        f"leaf, so a typical ripple touches only a handful of nodes whatever the size of the map. The *mean* number "
        f"of nodes whose distance changed went from {a0:.0f} to {a1:.0f} (×{a1 / max(a0, 1e-9):.1f}) while n grew "
        f"×{n1 / n0:.0f}, "
        + ("which is sub-linear in n and in line with the heuristic of Section 4 that the expected ripple tracks the "
           "average tree depth (Θ(√n)) rather than n. "
           if a1 / max(a0, 1e-9) < 0.8 * n1 / n0 else
           "which does not support the sub-linear heuristic of Section 4 in this run. ")
        + "(The mean is dominated by rare large ripples and is noisy with this many trials, so treat it as indicative.) "
        "The advantage of repair over recomputation therefore widens with the size of the map.")
    D.figure(R.path("fig4_scaling_with_n.png"),
             "Median time versus network size when blocking one shortest-path-tree edge (left) and a 20-edge "
             "accident zone (right), for per-edge repair, batch repair and full Dijkstra.")

    # 5.5 ripple
    D.h("5.5 Which closures cause big ripples? (RQ4)", 2)
    rp = R.rp
    ratio_r = (rp["affected"] / rp["subtree"]).clip(upper=1)
    frac_close = float((ratio_r >= 0.9).mean())
    med = rp.groupby("cls")["affected"].median()
    med_txt = ", ".join(f"{c}: {int(v)}" for c, v in med.items())
    big_cls = [c for c in ("arterial", "bridge") if c in med.index and "local" in med.index and med[c] > med["local"]]
    cls_sentence = (" Edges that carry many shortest paths (" + " and ".join(big_cls) + ") produced larger median "
                    "ripples than ordinary local streets, so a few structurally important closures dominate repair cost."
                    if big_cls else " Road class alone was not a clear predictor of ripple size in this run.")
    D.p(f"We blocked {len(rp)} different shortest-path-tree edges one at a time (a random sample plus every bridge "
        f"edge on the tree) and recorded how many distances changed. In every case the number of changed "
        f"distances was at most the size of the shortest-path-tree subtree below the edge, as predicted by "
        f"Lemma 4 (the harness asserts this). In {100 * frac_close:.0f}% of cases it was within 10% of that "
        f"bound, so **the subtree size below an edge is an excellent predictor of the ripple**. The median "
        f"number of affected nodes by road class was: {med_txt}.{cls_sentence}")
    D.figure(R.path("fig5_ripple.png"),
             "Left: ripple size versus subtree size (dashed line = upper bound). Right: ripple size by road class.")

    # 5.6 heatmap
    D.h("5.6 Anatomy of one accident", 2)
    hs = M.get("heatmap_stranded", 0)
    D.p(f"Figure 6 shows an accident zone of 80 blocked edges, chosen as the worst of 40 random placements. "
        f"{M['heatmap_net_changed']:,} of {n:,} nodes ({100 * M['heatmap_net_changed'] / n:.0f}%) need a new route"
        + (f" ({hs:,} of them become unreachable)" if hs else "")
        + ", and they form a contiguous region around and beyond the blocked area, which is exactly the "
        "set the repair algorithm touches.")
    D.figure(R.path("fig6_heatmap.png"),
             "Nodes whose travel time from the depot increases after an 80-edge accident zone (red edges).", 11.5)

    # 5.7 fleet
    if R.fleet is not None:
        _fleet_section(D, R)
    # 5.8 p2p
    if R.p2p is not None:
        _p2p_section(D, R)
    # 5.9 closure
    if R.closure is not None:
        _closure_section(D, R)
    # 5.10 real
    _cross_section(D, R)
    # 5.11 marks
    if R.marks is not None:
        mk = M["marks"]
        D.h("5.11 Implementation detail: set() objects versus generation-stamped arrays", 2)
        gain = 100 * (1 - mk["total_ms_arrays"] / mk["total_ms_sets"])
        D.p(f"The original increase repair allocated two Python `set()` objects per call (the affected set and "
            f"the queued set). We replaced them by two integer arrays allocated once, where a node is ‘in the set’ "
            f"iff its entry equals the current generation number, so clearing is O(1). On {mk['n']} single "
            f"shortest-path-tree closures (each timed with the repetition policy above, both versions interleaved "
            f"in random order) the median time per closure went from {mk['median_us_sets']:.1f} µs to "
            f"{mk['median_us_arrays']:.1f} µs, and the total from {mk['total_ms_sets']:.1f} ms to "
            f"{mk['total_ms_arrays']:.1f} ms ({abs(gain):.0f}% {'less' if gain > 0 else 'more'}); on the "
            f"{mk['n_big']} closures with at least {mk['big_threshold']} affected nodes, "
            f"{mk['total_ms_sets_big']:.1f} ms → {mk['total_ms_arrays_big']:.1f} ms. "
            + ("The gain is modest but consistent, and the code stays readable, so the arrays were kept."
               if gain > 0 else "The arrays did not help in this run."))

    # ---------- 6 threats
    D.h("6. Threats to validity", 1)
    D.bullets([
        "**Pure-Python constant factors.** Both Dijkstra and the repair routines are interpreted Python; relative "
        "costs of heap operations, dictionary look-ups and function calls differ in compiled code, so absolute "
        "times and the exact break-even sizes would move (in either direction) in C++ or Rust. The asymptotic "
        "trends and the comparison between methods implemented in the same style are what this study supports.",
        ("**Synthetic versus real data.** The main experiments use a synthetic grid city. Real networks have "
         "different degree distributions, hierarchy and one-way structure; Section 5.10 checks the core results "
         "on real OpenStreetMap networks" + ("" if R.cross is not None else ", but those runs have not been done yet")
         + ". Results are for one depot per city."),
        f"**Closure model.** The headline experiments model a closure by {closure_txt}. A ×{M['block_factor']} "
        "weight keeps every node reachable; deletion can disconnect parts of the network. Section 5.9 shows how "
        "much this matters.",
        "**Single source.** Everything is measured for one depot. A fleet with many depots (or all-pairs routing) "
        "would multiply the repair work by the number of sources, and shared structure between sources is not exploited.",
        "**Disruption models** are random, not calibrated on real incident or speed data.",
        "**Timing.** Timings are medians of repeated runs on one machine with garbage collection disabled; other "
        "background load, CPU frequency scaling and Python versions add noise that the medians and IQRs only partly hide.",
        "**Heuristic for LPA\\*/A\\*.** The straight-line heuristic is weak on networks where travel speed varies "
        "a lot (it is calibrated to the fastest road); a better heuristic (landmarks/ALT) would help both.",
    ])

    # ---------- 7 conclusion
    D.h("7. Conclusion", 1)
    D.p(f"Incremental shortest-path repair is a clear win when only a few roads change: on a {n:,}-node map, "
        f"blocking a single road that carries shortest paths was repaired {x(tree1['speedup_eff_med'])} faster "
        f"than rerunning Dijkstra, and disruptions of {mid} edges {x(min(spm.values()))}–{x(max(spm.values()))} faster. "
        f"Headline speed-ups for random single closures (up to {x(max(R.row(md, lo)['speedup_med'] for md in rmodes))}) "
        f"mostly measure the early exit for roads that no shortest path uses, so they should not be quoted "
        f"without the no-op fraction. The cost of repair is governed by how many distances actually change rather "
        f"than by the size of the map, and the advantage grows with the map. "
        + (f"Per-edge repair loses to recomputation once a disruption touches on the order of "
           f"{min(v for v in xo.values() if v):.0f}–{max(v for v in xo.values() if v):.0f} edges (depending on its "
           f"shape); " if any(xo.values()) else "")
        + ("batch repair, which handles a whole disruption in one sweep, " + _batch_conclusion(R, hi) if has_batch else "")
        + "Large ripples are caused by a small number of structurally important edges, and their size is almost "
          "exactly the shortest-path-tree subtree below the edge. "
        + (_fleet_conclusion(R) if R.fleet is not None else "")
        + (_p2p_conclusion(R) if R.p2p is not None else "")
        + "The algorithms were proven correct and validated against Dijkstra on every test.")
    D.p("**Practical recommendation:** keep the shortest-path tree up to date by incremental repair, use batch "
        "repair for multi-edge incidents, and fall back to a full recomputation when a disruption is larger than "
        "the break-even size.")

    # ---------- 8 gaps
    D.h("8. Gaps and future directions", 1)
    D.bullets([
        "**Better worst-case guarantees.** One update can change Θ(n) distances (Section 4), so per-update "
        "output-sensitive bounds are the best possible; improving amortised bounds for road-like graphs is open.",
        "**Adaptive strategy.** Predict |A| cheaply (e.g. from subtree sizes, Section 5.5) and choose between "
        "per-edge repair, batch repair and recomputation per disruption.",
        "**Multiple sources and all-pairs.** Delivery fleets need many depots; extending to all-pairs or "
        "landmark-based schemes (ALT, contraction hierarchies) and keeping their preprocessing valid under updates is open.",
        "**Lazy repair.** Repair only the part of the tree needed by incoming queries instead of the whole tree; "
        "LPA*/D* Lite are one point in that design space.",
        "**Time-dependent and stochastic weights.** Traffic forecasts need time-dependent edge functions, which "
        "break the simple tight-edge arguments used here.",
        "**Realistic data.** Calibrate the disruption models with real incident feeds and speed data, and "
        "test on many cities and with a compiled implementation.",
        "**Zero weights.** The proofs assume strictly positive weights; zero-weight edges (as in the original "
        "Ramalingam–Reps algorithm) need an additional ordering argument.",
    ])

    # ---------- appendices
    D.h("Appendix A. Team contributions", 1)
    D.table(["Member", "Role", "Contribution"],
            [["[Name A]", "Graph & Data Lead", "Graph loading (OSMnx/synthetic), weights, disruption simulator; Section 1"],
             ["[Name B]", "Algorithms Lead", "Dijkstra baseline, incremental and batch repair, LPA*, tests; Section 2"],
             ["[Name C]", "Theory Lead", "Proofs of correctness and complexity analysis; Sections 3–4"],
             ["[Name D]", "Experiments Lead", "Benchmarks, figures, report assembly; Sections 5–7"],
             ["All", "", "Section 8; peer review of one other section each"]],
            widths=[2.5, 3.5, 10.0])
    D.h("Appendix B. Reproducing the results", 1)
    D.code("""
pip install -r requirements.txt
python run_all.py                                  # synthetic city, full run (+ cached real cities in data/)
python run_all.py --quick                          # smoke test
python run_all.py --closure delete                 # closures delete the road
pip install -r requirements-osm.txt                # optional: real cities
python scripts/fetch_cities.py                     # download + cache the two real networks into data/""")
    commit = M.get("git_commit")
    D.p(f"The reported run used seed {M['seed']}, {M['trials']} trials per setting and took "
        f"{M['runtime_seconds']:.0f} s on {M['platform']} (Python {M['python']})"
        + (f", at git commit `{commit[:12]}`" if commit else "")
        + (f", with command `{M['command']}`" if M.get("command") else "")
        + ". `results/meta.json` records all parameters.")
    D.h("References", 1)
    refs = [
        "G. Ramalingam and T. Reps. An incremental algorithm for a generalization of the shortest-path problem. "
        "Journal of Algorithms 21(2):267–305, 1996.",
        "G. Ramalingam and T. Reps. On the computational complexity of dynamic graph problems. "
        "Theoretical Computer Science 158(1–2):233–277, 1996.",
        "E. W. Dijkstra. A note on two problems in connexion with graphs. Numerische Mathematik 1:269–271, 1959.",
        "M. L. Fredman and R. E. Tarjan. Fibonacci heaps and their uses in improved network optimization "
        "algorithms. Journal of the ACM 34(3):596–615, 1987.",
        "D. Frigioni, A. Marchetti-Spaccamela and U. Nanni. Fully dynamic algorithms for maintaining shortest "
        "paths trees. Journal of Algorithms 34(2):251–281, 2000.",
        "S. Koenig, M. Likhachev and D. Furcy. Lifelong Planning A*. Artificial Intelligence 155(1–2):93–146, 2004.",
        "P. E. Hart, N. J. Nilsson and B. Raphael. A formal basis for the heuristic determination of minimum cost "
        "paths. IEEE Transactions on Systems Science and Cybernetics 4(2):100–107, 1968.",
        "G. Boeing. OSMnx: New methods for acquiring, constructing, analyzing, and visualizing complex street "
        "networks. Computers, Environment and Urban Systems 65:126–139, 2017.",
        "M. Okabe and K. Ito. Color Universal Design (CUD): how to make figures and presentations that are "
        "friendly to colorblind people. J*FLY, 2008.",
    ]
    D.bullets(refs, style="List Number")
    D.p("(Please verify bibliographic details against the original sources before submission.)", italic=True, size=9.5)
    D.save(out)


# ----------------------------------------------------------------- section helpers
def _fleet_stats(R):
    fl = R.fleet.copy()
    g = fl.groupby(["placement", "size"])
    st = g.agg(changed=("routes_changed", "mean"), delayed=("delayed", "mean"),
               used=("used_closed", "mean"), stranded=("stranded", "mean"),
               same=("delayed_same_route", "mean"), trials=("trial", "count"),
               t_rep=("t_repair", "median"), t_full=("t_full", "median")).reset_index()
    d = fl[fl["delayed"] > 0].groupby(["placement", "size"])["extra_min_mean"].median()
    st["extra_med"] = [d.get((p, k), 0.0) for p, k in zip(st["placement"], st["size"])]
    return st


def _fleet_abstract(R):
    st = _fleet_stats(R)
    r = st[st["placement"] == "on a route"].sort_values("size").iloc[-1]
    v = int(R.fleet["vehicles"].iloc[0])
    return (f"For a fleet of {v} delivery vehicles, an accident zone of {int(r['size'])} edges on a vehicle’s route "
            f"changed {r['changed']:.1f} routes and delayed {r['delayed']:.1f} vehicles on average, with a "
            f"median delay of {r['extra_med']:.1f} minutes per delayed vehicle. ")


def _fleet_conclusion(R):
    st = _fleet_stats(R)
    any_ = st[st["placement"] == "anywhere"]
    return (f"For a delivery fleet, a randomly placed accident affects few vehicles (on average at most "
            f"{any_['delayed'].max():.1f} delayed), but an accident on a route reroutes several and costs minutes, "
            f"and the parent array produces the new routes at no extra cost. ")


def _fleet_section(D, R):
    st = _fleet_stats(R)
    v = int(R.fleet["vehicles"].iloc[0])
    D.h("5.7 Fleet rerouting (RQ5)", 2)
    D.p(f"The routing service keeps the shortest-path tree from the depot, so the route of every vehicle can be "
        f"read off with `path_to(t)`. We sent a fleet of {v} vehicles to random destinations and, after each "
        f"accident zone (batch repair), compared every vehicle’s route and travel time with those before. Accident "
        f"zones were placed either anywhere in the city or centred on a random node of a random vehicle’s current "
        f"route, with {int(st['trials'].iloc[0])} trials per setting.")
    rows = [[p, int(k), f"{u:.1f}", f"{c:.1f}", f"{d:.1f}", f"{sm:.1f}", f"{e:.1f}", f"{s:.1f}"]
            for p, k, u, c, d, sm, e, s in zip(st["placement"], st["size"], st["used"], st["changed"], st["delayed"],
                                               st["same"], st["extra_med"], st["stranded"])]
    D.table(["Accident placed", "Edges", "Route used a closed road", "Route changed", "Delayed",
             "Delayed, no detour", "Extra min. (median)", "Stranded"], rows,
            caption=f"Effect of one accident zone on a fleet of {v} vehicles (means over trials; extra minutes = "
                    f"median over trials of the mean delay of the delayed vehicles).",
            widths=[2.6, 1.3, 2.3, 1.8, 1.6, 2.0, 2.0, 1.6], size=8.5)
    r = st[st["placement"] == "on a route"].sort_values("size").iloc[-1]
    D.p(f"A randomly placed accident rarely touches any of the {v} routes. An accident on a route is different: "
        f"at {int(r['size'])} edges it hit {r['used']:.1f} routes on average, {r['changed']:.1f} vehicles were "
        f"re-routed and {r['delayed']:.1f} were delayed, by a median of {r['extra_med']:.1f} minutes. "
        + (f"Some delayed vehicles keep their route ({r['same']:.1f} on average in that setting): with the "
           f"×-factor closure model a blocked road is still usable at a high cost, and for destinations inside or "
           f"just behind the zone it remains the best option — the closure model matters for this statistic "
           f"(Section 5.9). " if r["same"] > 0 else "")
        + f"Repairing the "
        f"tree took a median of {1e3 * r['t_rep']:.2f} ms versus {1e3 * r['t_full']:.1f} ms for a full Dijkstra, "
        f"and all {v} new routes then come for free from the parent array.")
    D.figure(R.path("fig7_fleet.png"),
             "Fleet rerouting: number of vehicles whose route changed (left) and mean extra travel time of the "
             "delayed vehicles (right), per accident-zone size and placement.")


def _p2p_stats(R):
    pp = R.p2p
    return pp.groupby(["scenario", "phase", "method"])["time"].median().unstack() * 1e3


def _p2p_abstract(R):
    t = _p2p_stats(R)
    blk = t.xs("block", level="phase")
    wins = (blk["LPA*"] < blk["A*"]).sum()
    rb = (blk["batch repair"] / blk["A*"]).median()
    return (f"For rerouting a single vehicle after closures on its own route, LPA* beat A* from scratch in {wins} of "
            f"{len(blk)} blocking scenarios, and repairing the whole tree took {rb:.1f}× the time of A* (median). ")


def _p2p_conclusion(R):
    t = _p2p_stats(R)
    blk, clr = t.xs("block", level="phase"), t.xs("clear", level="phase")
    return (f"For a single destination, A* from scratch is a strong baseline: LPA* was faster than A* in "
            f"{(blk['LPA*'] < blk['A*']).sum()} of {len(blk)} blocking and {(clr['LPA*'] < clr['A*']).sum()} of "
            f"{len(clr)} clearing scenarios, and repairing the full tree (which serves every destination at once) "
            f"took {(blk['batch repair'] / blk['A*']).median():.1f}× the time of A* when blocking. ")


def _p2p_section(D, R):
    t = _p2p_stats(R)
    pp = R.p2p
    exp = pp.groupby(["scenario", "phase"])["lpa_expansions"].median()
    methods = ["full Dijkstra", "Dijkstra to t", "A*", "batch repair", "LPA*"]
    D.h("5.8 Point-to-point rerouting: LPA* versus A* and repair (RQ6)", 2)
    D.p(f"For {pp['pair'].nunique()} destinations in the farther half of the map (by travel time from the depot) we "
        "blocked roads on the vehicle’s current route — one road, three roads, or a 20-edge accident zone centred on "
        "a route node — and then cleared them. We timed five ways to obtain the new route: full Dijkstra, Dijkstra "
        "stopping at t, A* from scratch, batch repair of the whole tree, and LPA* (both incremental methods keep "
        "their state between disruptions). All five returned the same travel time in every case (asserted).")
    rows = []
    for (scen, phase), r in t.iterrows():
        rows.append([scen, "blocking" if phase == "block" else "clearing"]
                    + [ms(r[mth]) for mth in methods] + [f"{exp[(scen, phase)]:.0f}"])
    D.table(["Disruption", "Phase"] + methods + ["LPA* expansions"], rows,
            caption="Median time to obtain the new depot → destination route, and median number of LPA* node expansions.",
            widths=[3.0, 1.6, 1.7, 1.7, 1.4, 1.7, 1.4, 1.7], size=8)
    blk = t.xs("block", level="phase")
    clr = t.xs("clear", level="phase")
    D.p(f"A* from scratch is already {x((blk['full Dijkstra'] / blk['A*']).median())} faster than a full Dijkstra "
        f"(median over blocking scenarios), because the heuristic focuses the search on the corridor towards t. "
        f"LPA* was faster than A* in {(blk['LPA*'] < blk['A*']).sum()} of {len(blk)} blocking scenarios and "
        f"{(clr['LPA*'] < clr['A*']).sum()} of {len(clr)} clearing scenarios. When a road on the route is blocked, "
        f"every node of the old search tree beyond it becomes under-consistent: LPA* must first raise their "
        f"estimates to ∞ and then lower them again (two expansions each), and each expansion recomputes rhs over "
        f"all in-edges. In pure Python this overhead is comparable to simply searching again. Clearing (a "
        f"decrease) only produces over-consistent nodes and is LPA*’s favourable case. Batch repair maintains the "
        f"whole tree — useful for a fleet — and took {(blk['batch repair'] / blk['A*']).median():.1f}× the time "
        f"of A* when blocking and {(clr['batch repair'] / clr['A*']).median():.1f}× when clearing (medians over "
        f"scenarios).")
    D.figure(R.path("fig8_point_to_point.png"),
             "Point-to-point rerouting: median time per method (whiskers = IQR) when blocking roads on the route "
             "(left) and clearing them (right).")


def _closure_section(D, R):
    cl = R.closure.copy()
    cl["speedup"] = cl["t_full"] / cl["t_repair"]
    st = cl[cl["method"] == "batch"].groupby(["closure", "mode", "size"]).agg(
        net=("net_changed", "mean"), stranded=("stranded", "mean"), any_str=("stranded", lambda s: (s > 0).mean()),
        sp=("speedup", "median")).reset_index()
    D.h("5.9 Closure model: ×-factor versus deletion", 2)
    rows = []
    for (md, k), grp in st.groupby(["mode", "size"]):
        f = grp[grp["closure"] == "factor"].iloc[0]
        d = grp[grp["closure"] == "delete"].iloc[0]
        rows.append([MODE_NAME[md].capitalize(), int(k), f"{f['net']:.1f}", f"{d['net']:.1f}",
                     f"{d['stranded']:.1f} ({100 * d['any_str']:.0f}%)", x(f["sp"]), x(d["sp"])])
    D.table(["Disruption", "Edges", "Changed (×factor)", "Changed (delete)", "Stranded (delete; % of trials)",
             "Speed-up (×factor)", "Speed-up (delete)"], rows,
            caption="The same disruption locations under both closure models (batch repair; means over trials, "
                    "speed-up = median).", widths=[3.0, 1.3, 2.2, 2.2, 2.8, 2.0, 2.0], size=8.5)
    diff = st.pivot_table(index=["mode", "size"], columns="closure", values="net")
    spv = st.pivot_table(index=["mode", "size"], columns="closure", values="sp")
    sp_ratio = float(np.maximum(spv["delete"] / spv["factor"], spv["factor"] / spv["delete"]).max())
    same = bool(((diff["delete"] - diff["factor"]).abs() <= 0.05 * diff["factor"].clip(lower=1)).all())
    D.p("With the same random seed both models block exactly the same roads. "
        + ("The number of nodes whose distance changes is almost identical: a ×50 detour is essentially never "
           "worth taking, so a heavily penalised road behaves like a deleted one for the shortest-path tree. "
           if same else
           "The number of changed distances differs noticeably between the models, so the closure model affects "
           "the results. ")
        + "The difference is in **connectivity**: under deletion some nodes become unreachable (dead ends behind "
        "a closure, or one-way pockets), which the ×-factor model hides by keeping a very slow but finite path. "
        + (f"Repair speed-ups differ by at most a factor of {sp_ratio:.1f} between the models (table above)."
           if sp_ratio < 1.5 else
           f"Repair speed-ups differ by up to a factor of {sp_ratio:.1f} between the models."))


def _cross_abstract(R):
    cs = R.cross
    real = [gname for gname in cs["graph"].unique() if gname != "synthetic"]
    return f"The core experiment was repeated on {len(real)} real street networks ({', '.join(real)}). "


def _cross_section(D, R):
    D.h("5.10 Real road networks (RQ7)", 2)
    if R.cross is None or R.gstats is None:
        D.note("**Not yet generated.** The pipeline supports real OpenStreetMap networks (`--place`, "
               "`--graph-file`, `scripts/fetch_cities.py`, osmnx 1.x and 2.x), but no cached real network was "
               "available when these results were produced, so this section has no data. Run "
               "`python scripts/fetch_cities.py` followed by `python run_all.py` to fill it in.")
        return
    gs = R.gstats
    rows = [[r["graph"], f"{int(r['n']):,}", f"{int(r['m']):,}", f"{r['avg_out_degree']:.2f}",
             f"{int(r['hop_diameter'])}", f"{100 * r['oneway_frac']:.0f}%"] for _, r in gs.iterrows()]
    D.table(["Network", "n", "m", "Avg. out-degree", "Hop diameter (≥)", "One-way edges"], rows,
            caption="Graph statistics (largest strongly connected component). The hop diameter is a lower bound "
                    "from repeated BFS sweeps from the farthest node found so far.",
            widths=[4.6, 1.8, 1.8, 2.3, 2.4, 2.2], size=9)
    cs = R.cross
    rows = []
    for gname in gs["graph"]:
        d = cs[cs["graph"] == gname]
        for md in ("tree", "cluster"):
            dd = d[(d["mode"] == md) & (d["phase"] == "block")]
            if dd.empty:
                continue
            k1 = dd["size"].min()
            r_seq = dd[(dd["size"] == k1) & (dd["method"] == "sequential")].iloc[0]
            rows.append([gname, MODE_NAME[md], x(r_seq["speedup_eff_med"]),
                         edges(R.meta.get("crossgraph", {}).get(gname, {}).get("sequential", {}).get(md), dd["size"].max()),
                         edges(R.meta.get("crossgraph", {}).get(gname, {}).get("batch", {}).get(md), dd["size"].max())])
    D.table(["Network", "Disruption", "Speed-up, 1 edge (effective)", "Break-even per-edge", "Break-even batch"], rows,
            caption="Core results per network (blocking phase, median over trials).",
            widths=[4.2, 3.2, 3.0, 2.8, 2.8], size=9)
    xg = R.meta.get("crossgraph", {})
    one = {gname: cs[(cs["graph"] == gname) & (cs["mode"] == "tree") & (cs["phase"] == "block")
                     & (cs["method"] == "sequential")].sort_values("size").iloc[0]["speedup_eff_med"]
           for gname in gs["graph"]}

    def later(gname, md):          # batch break-even later than (or not reached where) per-edge breaks even
        a_, b_ = xg.get(gname, {}).get("sequential", {}).get(md), xg.get(gname, {}).get("batch", {}).get(md)
        return a_ is not None and (b_ is None or b_ >= a_)
    pairs = [(gname, md) for gname in gs["graph"] for md in ("tree", "cluster")
             if xg.get(gname, {}).get("sequential", {}).get(md) is not None]
    n_later = sum(later(gname, md) for gname, md in pairs)
    D.p("On every network a single blocked tree edge was repaired far faster than a recomputation ("
        + ", ".join(f"{gname.replace('_', ' ')}: {x(v)}" for gname, v in one.items())
        + "), and the speed-up fell as disruptions grew. "
        + (f"Where per-edge repair reached a break-even point ({len(pairs)} network/model combinations), batch repair "
           f"broke even at the same or a larger size, or not at all, in {n_later} of them. " if pairs else
           "Within the tested sizes no break-even point was reached on these networks. ")
        + (lambda r: f"Structurally the networks differ most in one-way streets and degree: {r['graph'].replace('_', ' ')} "
           f"has the highest share of one-way edges ({100 * r['oneway_frac']:.0f}%) and an average out-degree of "
           f"{r['avg_out_degree']:.2f}, which leaves fewer alternative routes around a closure.")(
            gs.sort_values("oneway_frac").iloc[-1]))
    D.figure(R.path("fig9_cross_graph.png"),
             "Speed-up over full Dijkstra versus disruption size on the synthetic city and the real networks "
             "(tree-edge closures and accident zones; solid = per-edge repair, dashed = batch repair).")


def _batch_conclusion(R, hi):
    xob = R.xo("batch")
    vals = [v for v in xob.values() if v]
    not_reached = [MODE_NAME[md] for md, v in xob.items() if not v]
    return ((f"breaks even only at about {min(vals):.0f}–{max(vals):.0f} edges" if vals else "")
            + (" and " if vals and not_reached else "")
            + (f"never lost to recomputation within the tested range (up to {hi} edges) for the "
               + " and ".join(not_reached) if not_reached else "")
            + ". ")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "..", "results"))
    ap.add_argument("--out", default=os.path.join(HERE, "Rush_Hour_Rerouting_Report.docx"))
    a = ap.parse_args()
    R = Results(a.results)
    build(R, a.out)
    print("Wrote", os.path.abspath(a.out))
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    pdf = os.path.splitext(os.path.abspath(a.out))[0] + ".pdf"
    if soffice:
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir",
                            os.path.dirname(os.path.abspath(a.out)), a.out],
                           check=True, capture_output=True, timeout=180)
            print("Also wrote PDF copy.")
            return
        except Exception as e:  # PDF is optional
            print("PDF conversion failed:", e)
    if os.path.exists(pdf):
        os.remove(pdf)           # never leave a PDF that no longer matches the .docx
        print("Removed stale PDF (no LibreOffice found to regenerate it).")
    else:
        print("PDF skipped (LibreOffice not found).")


if __name__ == "__main__":
    main()
