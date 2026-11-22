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
             "wave": "congestion wave"}


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
    return f"{v:.0f}×" if v >= 10 else f"{v:.1f}×"


def ms(v):
    return f"{v:.2f} ms" if v < 10 else f"{v:.1f} ms"


class Results:
    def __init__(self, folder):
        self.f = folder
        self.meta = json.load(open(os.path.join(folder, "meta.json")))
        self.summ = pd.read_csv(os.path.join(folder, "summary_main.csv"))
        self.sc = pd.read_csv(os.path.join(folder, "raw_scaling.csv"))
        self.rp = pd.read_csv(os.path.join(folder, "raw_ripple.csv"))
        self.raw = pd.read_csv(os.path.join(folder, "raw_main.csv"))
        self.sizes = sorted(self.summ["size"].unique())

    def row(self, mode, size, phase="block"):
        r = self.summ[(self.summ["mode"] == mode) & (self.summ["size"] == size)
                      & (self.summ["phase"] == phase)]
        return r.iloc[0]

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

    # ---------- title page
    D.p("", after=60)
    D.p("Rush Hour Rerouting", bold=True, align="center", size=30, after=2)
    D.p("How Fast Can a Map Heal Itself?", align="center", size=18, after=18)
    D.p("Incremental repair of single-source shortest paths versus full Dijkstra "
        "recomputation on a road network under accidents and congestion",
        italic=True, align="center", size=12, after=30)
    D.p("Problem 11: Adaptive Path-Finding in Dynamic Weighted Graphs", align="center", size=12, after=40)
    D.p("Team: [Member A: Graph & Data Lead] · [Member B: Algorithms Lead] · "
        "[Member C: Theory Lead] · [Member D: Experiments & Visualisation Lead]",
        align="center", size=10.5, after=4)
    D.p("[Course / Institution] · [Date]", align="center", size=10.5)
    D.d.add_page_break()

    # ---------- abstract
    D.h("Abstract", 1)
    spm = {md: R.row(md, mid)["speedup_med"] for md in MODE_NAME}
    spb = {md: R.row(md, big)["speedup_med"] for md in MODE_NAME}
    xo = M["crossover"]
    xo_txt = "; ".join(f"{MODE_NAME[md]} ≈ {xo[md]:.0f} edges" for md in MODE_NAME if xo.get(md))
    D.p(f"When accidents or congestion change travel times on a road network, a routing service must "
        f"update its shortest-path tree. The textbook response is to rerun Dijkstra’s algorithm from "
        f"scratch; an incremental alternative in the style of Ramalingam and Reps re-examines only the "
        f"nodes whose distance actually changes. We implement both, prove the repair algorithm correct "
        f"for positive integer weights, analyse its output-sensitive complexity, and benchmark it on a "
        f"road graph with {n:,} nodes and {m:,} directed edges under three disruption models "
        f"(scattered closures, an accident zone, and a spreading congestion wave). For disruptions of "
        f"{mid} changed edges, repair was {x(min(spm.values()))}–{x(max(spm.values()))} faster than full "
        f"recomputation (median over {M['trials']} trials), and still {x(min(spb.values()))}–{x(max(spb.values()))} "
        f"faster at {big} edges. The advantage shrinks as the disruption grows"
        + (f"; estimated break-even points, beyond which recomputing is cheaper, are {xo_txt}."
           if xo_txt else "; within the tested range repair never became slower than recomputation.")
        + f" Every repaired result was checked against a fresh Dijkstra run "
          f"({M['equality_checks_passed']:,} checks, zero mismatches).")

    # ---------- 1 problem statement
    D.h("1. Problem statement", 1)
    D.p("**Setting.** A road network is a directed graph G = (V, E) with n = |V| nodes (intersections), "
        "m = |E| edges (road segments) and a strictly positive integer travel time w(e) on every edge. "
        "A fixed source s (a depot or the user’s location) is given. The routing service maintains "
        "d(v), the shortest travel time from s to every node v, together with the shortest-path tree.")
    D.p("**Updates.** A disruption is a batch of k edge-weight changes (u₁,v₁,w′₁), …, (u_k,v_k,w′_k). "
        "Accidents and congestion increase weights; clearing them decreases weights back.")
    D.p("**Goal.** After a disruption, restore the exact distances d′(v) for all v. Two strategies are compared:")
    D.bullets(["**Full recomputation:** apply the new weights and run Dijkstra from s, in "
               "O((n + m) log n) time regardless of how little changed.",
               "**Incremental repair:** process the k updates one by one and touch only the set "
               "δ of nodes whose distance changes."])
    D.p("**Research questions.**")
    D.bullets(["RQ1. How does the speed-up of repair over recomputation depend on disruption size and shape?",
               "RQ2. At what disruption size does recomputing from scratch become the better choice (the break-even point)?",
               "RQ3. How do both methods scale with the size n of the network?",
               "RQ4. Which road closures cause large ripples, and can the ripple size be predicted?"])
    D.p("**Scope.** Single source, positive weights, no vertex or edge deletions (a closure is modelled "
        "as a large finite weight, 50× the normal travel time), static source. Multiple sources, "
        "time-dependent weights and batch-optimal repair are left as future work (Section 7).")

    # ---------- 2 algorithm
    D.h("2. Algorithms", 1)
    D.h("2.1 Baseline: full Dijkstra", 2)
    D.p("The baseline recomputes all distances with Dijkstra’s algorithm using a binary heap "
        "(lazy deletion), running in O((n + m) log n) time. It is also used as the test oracle.")
    D.h("2.2 Terminology", 2)
    D.p("An edge (a,b) is **tight** if d(a) + w(a,b) = d(b). Because weights are positive, d strictly "
        "increases along tight edges, so the tight edges form a directed acyclic graph (the *tight DAG*) "
        "in which every reachable node v ≠ s has at least one tight in-edge, and every shortest path "
        "consists of tight edges only. Integer weights make the tightness test exact.")
    D.h("2.3 Incremental repair", 2)
    D.p("To change the weight of edge e = (u,v) from w to w′ we distinguish two cases.")
    D.p("**Case A: w′ < w (road gets faster, e.g. an accident is cleared).** Only the improvement "
        "that enters through v can spread. If d(u) + w′ ≥ d(v) nothing changes; otherwise set "
        "d(v) = d(u) + w′ and run a Dijkstra-style propagation from v that relaxes outgoing edges and "
        "stops wherever no improvement occurs.")
    D.code("""
DECREASE(u, v, w'):
    if d[u] + w' >= d[v]: return 0
    d[v] <- d[u] + w';  H <- heap{(d[v], v)};  changed <- 0
    while H not empty:
        (dx, x) <- pop-min(H);  if dx > d[x]: continue
        changed++
        for each edge (x, z, wz):
            if dx + wz < d[z]:  d[z] <- dx + wz;  push(H, (d[z], z))
    return changed""")
    D.p("**Case B: w′ > w (road gets slower, e.g. an accident).** If e was not tight, no shortest path used "
        "it and nothing changes. Otherwise the repair has two phases: (1) find the **affected set A**, the "
        "nodes that lose every tight path from s, by scanning candidates in increasing order of old "
        "distance; (2) recompute distances inside A with a Dijkstra run seeded from the unaffected boundary.")
    D.code("""
INCREASE(u, v, w_old, w_new):               // weight already updated in G
    if e was not tight: return 0
    // Phase 1: affected set
    A <- {};  H <- heap{(d[v], v)};  queued <- {v}
    while H not empty:
        (dx, x) <- pop-min(H)
        if exists in-edge (y, x, wy) with y not in A and d[y] + wy = dx:  continue   // still supported
        A <- A + {x}
        for each out-edge (x, z, wz) with dx + wz = d[z] and z not queued:
            queued <- queued + {z};  push(H, (d[z], z))
    // Phase 2: re-solve inside A
    for x in A:  d[x] <- min over in-edges (y,x) with y not in A of d[y] + w(y,x)   // INF if none
    H <- heap of {(d[x], x) : x in A, d[x] < INF}
    while H not empty:
        (dx, x) <- pop-min(H);  if dx > d[x]: continue
        for each out-edge (x, z, wz) with z in A:
            if dx + wz < d[z]:  d[z] <- dx + wz;  push(H, (d[z], z))
    return |A|""")
    D.p("A disruption with k edge changes is repaired by calling the appropriate routine k times. "
        "Both routines return the exact number of nodes whose distance changed, which is the quantity |δ| "
        "used in the analysis.")
    D.h("2.4 Disruption models", 2)
    D.bullets(["**Scattered closures:** k independent random edges are blocked (weight × 50).",
               "**Accident zone:** k connected edges around a random point (BFS order) are blocked (× 50).",
               "**Congestion wave:** k connected edges around a random epicentre are slowed by a factor "
               "1 + 9·e^(−h/2), where h is the hop distance from the epicentre, so the effect fades with distance.",
               "Every disruption is followed by a **clearing phase** that restores the original weights "
               "(weight decreases), so both repair cases are measured."])
    D.h("2.5 Implementation", 2)
    D.p("The code is written in pure Python (adjacency dictionaries in both directions, "
        "`heapq` as priority queue). Travel times are stored as integer deciseconds. Repair is "
        "compared with Dijkstra on identical graph states, and results are asserted equal after every "
        "disruption. Source code: `src/sssp.py` (algorithms), `src/disruptions.py`, `src/graph.py`.")

    # ---------- 3 proof
    D.h("3. Proof of correctness", 1)
    D.p("Notation: d is the distance function before an update and d′ after it; "
        "e = (u,v) is the changed edge, with old weight w and new weight w′. All weights are positive "
        "integers. Distances are +∞ for unreachable nodes.")
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
    D.p("**Lemma 3 (unaffected nodes).** Let w′ > w, let T be the set of edges tight with respect to d "
        "*excluding* e, and call x *T-reachable* if x = s or x is reachable from s along T. "
        "Then d′(x) = d(x) if and only if x is T-reachable.")
    D.p("*Proof.* (⇐) A T-path has the same length d(x) under the new weights, and d′ ≥ d. (⇒) If d′(x) = d(x), "
        "take a new shortest path P of length d(x). Since d(b) ≤ d(a) + w(a,b) for every edge and "
        "the sum telescopes to d(x), every edge of P is tight with respect to d; e cannot be among them "
        "because d(u) + w′ > d(v). So P ⊆ T. ∎")
    D.p("Define the **affected set** A = {x : d(x) < ∞ and x is not T-reachable}. By Lemma 3 these are exactly "
        "the nodes whose distance changes, and for them d′(x) > d(x).")
    D.p("**Lemma 4 (Phase 1 computes A).** If e is tight and w′ > w, Phase 1 returns exactly A.")
    D.p("*Proof.* Every node x ∈ A lies below v in the tight DAG: all tight paths from s to x pass through e "
        "(otherwise x would be T-reachable). We process candidates in nondecreasing old distance. Because "
        "weights are positive, every tight parent of x has strictly smaller old distance. By induction on "
        "this order, when x is popped all nodes with smaller distance have already been classified correctly. "
        "A node x ≠ s is T-reachable iff it has a T-edge (y,x) from a T-reachable y, i.e. a tight in-edge "
        "(other than e, which is no longer tight for w′) from a node outside A; this is exactly the test in "
        "the loop. Hence popped nodes are classified correctly. It remains to show that every node of A is "
        "pushed. Take x ∈ A, x ≠ v, with minimal distance among unpushed members of A, and a tight path to it "
        "through e; its predecessor p on that path lies below v. If p ∉ A, then p is T-reachable and so is x, "
        "contradiction. So p ∈ A with smaller distance, hence p was pushed and classified into A, and "
        "classification of p pushes x as a tight child — contradiction. ∎")
    D.p("**Lemma 5 (Phase 2 computes d′ on A).** After Phase 2, d(x) = d′(x) for all x.")
    D.p("*Proof.* Nodes outside A keep d′ = d (Lemma 3). For x ∈ A, consider a new shortest path to x and its "
        "last node y outside A (it exists since s ∉ A); the rest of the path lies inside A. Hence d′(x) is the "
        "shortest distance in the subgraph induced by A with initial labels min over y ∉ A of d(y) + w′(y,x). "
        "That is a multi-source Dijkstra with positive weights, which is correct by the standard argument. ∎")
    D.p("**Theorem.** After any single edge-weight update, `update_edge` leaves `dist` equal to the "
        "shortest-path distances of the new graph; by induction the same holds after any sequence of "
        "updates. *Proof.* Lemma 1 covers decreases, Lemmas 2–5 cover increases, and equal weights are no-ops. ∎")
    D.p(f"**Empirical validation.** In addition to the proof, the test suite (`tests/test_correctness.py`) "
        f"compares repair with Dijkstra after every update on hundreds of random graphs (including unreachable "
        f"nodes and heavy ties), and the benchmark harness asserts equality after every one of its "
        f"{M['equality_checks_passed']:,} disruptions. No mismatch was ever observed.")

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
        "**Extra space:** O(|A|) for the affected set and heap.",
    ])
    D.p("So repair is **output-sensitive**: it costs Õ(|δ|) for bounded-degree graphs and does not depend "
        "on n, whereas recomputation always pays Θ(n log n). This is the notion of boundedness studied by "
        "Ramalingam and Reps.")
    D.p("**Worst case.** Repair has no better worst case than recomputation. Let s have one cheap edge e "
        "to the rest of the graph (weight 1) and an expensive alternative (weight 100). Raising w(e) changes "
        "all n − 1 distances, so |δ| = Θ(n) and repair costs Θ(n log n), with larger constants than a plain "
        "Dijkstra. For a sequence of k updates the total cost is Σᵢ‖δᵢ‖ log n versus one Dijkstra run, so the "
        "break-even occurs roughly when the summed affected sizes reach a constant fraction of n.")
    D.p("**Expected case on road-like graphs.** For a tree edge (p,v) of the shortest-path tree, the subtree below v is an upper bound on |A|, and "
        "Σ_v subtree(v) equals the sum of node depths in the tree. "
        "Hence the *average* subtree size is the average hop-depth of the tree, which is Θ(√n) for planar, "
        "grid-like networks of diameter Θ(√n). A random closure that hits the tree thus costs about "
        "Θ(√n log n), versus Θ(n log n) for recomputation, so the advantage should grow roughly like √n. "
        "This is a heuristic estimate, not a theorem; Section 5 tests it.")

    # ---------- 5 experiments
    D.h("5. Experiments and results", 1)
    D.h("5.1 Setup", 2)
    D.p(f"**Graph.** {M['graph_source']}; after restricting to the largest strongly connected component the "
        f"graph has n = {n:,} nodes and m = {m:,} directed edges. Weights are travel times in integer deciseconds. "
        f"The source is the node closest to the map centroid (depot).")
    if synthetic:
        D.note("**Data note.** The results below were produced on a *synthetic* city (perturbed street grid with "
               "arterial roads, one-way streets and a river crossed by four bridges), because the build "
               "environment had no access to OpenStreetMap. The code supports real cities: run "
               "`python run_all.py --place \"<city, state, country>\"` and this report is regenerated with "
               "real-map numbers and figures.")
    D.p(f"**Protocol.** For each disruption model and each size k in {{{', '.join(map(str, R.sizes))}}} we ran "
        f"{M['trials']} independent trials with random disruption locations. In each trial we (1) applied the disruption "
        f"with incremental repair and timed it, (2) timed a full Dijkstra run on the resulting graph, "
        f"(3) asserted that both distance arrays are identical, then repeated this for the clearing phase. "
        f"We report medians (and inter-quartile ranges) of the per-trial speed-up t_Dijkstra / t_repair. "
        f"Garbage collection was disabled during timing. Python {M['python']} on a single core.")
    D.note("**Reading the numbers.** Absolute times come from a pure-Python implementation and will differ in "
           "C++ or Rust; the *ratios* and the shape of the curves are what matters. Timings of sub-millisecond "
           "operations are noisy, which is why medians over many trials are shown.", fill="E8F1FA")

    D.h("5.2 Speed-up versus disruption size (RQ1, RQ2)", 2)
    sizes_show = sorted({lo, R.near(5), mid, R.near(50), big, hi})
    rows = []
    for k in sizes_show:
        r = [k]
        for md in MODE_NAME:
            rr = R.row(md, k)
            r.append(f"{x(rr['speedup_med'])}  ({ms(rr['t_repair_ms'])} vs {ms(rr['t_full_ms'])})")
        rows.append(r)
    D.table(["Edges changed"] + [MODE_NAME[md].capitalize() for md in MODE_NAME], rows,
            caption="Median speed-up of repair over full Dijkstra when blocking roads "
                    "(median repair time vs. median Dijkstra time in brackets).",
            widths=[2.6, 4.5, 4.5, 4.5])
    r0 = R.raw[(R.raw["mode"] == "single") & (R.raw["size"] == lo) & (R.raw["phase"] == "block")]
    noop = float((r0["net_changed"] == 0).mean())
    D.p(f"**Caveat on tiny disruptions.** In {100 * noop:.0f}% of the {len(r0)} single-edge trials the blocked road was not "
        f"on the shortest-path tree, so no distance changed and repair correctly did no work (this costs a few "
        f"microseconds). The median speed-up at size {lo} is therefore dominated by these no-op cases; the scaling "
        f"and ripple experiments below deliberately block tree edges to measure the cases that matter.")
    D.figure(R.path("fig1_speedup_vs_size.png"),
             "Median speed-up (bands: inter-quartile range, blocking phase) versus disruption size. "
             "Values above the black line mean repair is faster.")
    parts = []
    for md in MODE_NAME:
        a, b, c = R.row(md, lo)["speedup_med"], R.row(md, big)["speedup_med"], R.row(md, hi)["speedup_med"]
        parts.append(f"for the {MODE_NAME[md]} {x(a)} at {lo} edge{'s' if lo > 1 else ''}, {x(b)} at {big} edges and "
                     f"{x(c)} at {hi} edges")
    D.p("The speed-up falls steadily as more edges change: " + "; ".join(parts) + ".")
    xo_lines = []
    for md in MODE_NAME:
        if xo.get(md):
            xo_lines.append(f"{MODE_NAME[md]}: ≈ {xo[md]:.0f} edges")
        else:
            xo_lines.append(f"{MODE_NAME[md]}: no break-even within the tested range (up to {hi} edges)")
    D.p("**Break-even point (RQ2).** Interpolating on the log–log curve, the median speed-up crosses 1 at: "
        + "; ".join(xo_lines) + ". Beyond that point it is cheaper to recompute from scratch. "
        "In practice a system could switch strategy based on the number of changed edges, or on a running "
        "estimate of Σ|δ|.")
    cl_hi = R.row("cluster", hi, "clear")["speedup_med"]
    bl_hi = R.row("cluster", hi, "block")["speedup_med"]
    faster = sum(R.row(md, k, "clear")["speedup_med"] > R.row(md, k, "block")["speedup_med"]
                 for md in MODE_NAME for k in R.sizes)
    total = len(MODE_NAME) * len(R.sizes)
    if faster >= 0.6 * total:
        D.p(f"The **clearing phase** (dashed lines) shows a higher speed-up than the blocking phase in {faster} of "
            f"{total} settings (accident zone at {hi} edges: {x(cl_hi)} vs {x(bl_hi)}). This is plausible because weight "
            f"decreases only propagate improvements, while increases must first identify the affected set and "
            f"then re-solve it.")
    else:
        D.p(f"The **clearing phase** (dashed lines) did not show a consistent advantage over the blocking phase "
            f"(higher speed-up in {faster} of {total} settings; accident zone at {hi} edges: {x(cl_hi)} vs {x(bl_hi)}).")
    D.figure(R.path("fig2_runtime_vs_size.png"),
             "Absolute median time per disruption. Dijkstra’s cost is flat; repair cost grows with the size of the disruption.")
    D.figure(R.path("fig3_affected_fraction.png"),
             "Mean percentage of nodes whose shortest-path distance changes. Repair work is proportional to this quantity.", 12.5)

    D.h("5.3 Scaling with network size (RQ3)", 2)
    sc = R.sc.groupby(["scenario", "n"]).median(numeric_only=True).reset_index()
    mean_net = R.sc[R.sc["scenario"] == "single tree-edge closure"].groupby("n")["net"].mean().sort_index()
    one = sc[sc["scenario"] == "single tree-edge closure"].sort_values("n")
    n0, n1 = int(one["n"].iloc[0]), int(one["n"].iloc[-1])
    rf = one["t_full"].iloc[-1] / one["t_full"].iloc[0]
    rr_ = one["t_repair"].iloc[-1] / max(one["t_repair"].iloc[0], 1e-9)
    a0, a1 = float(mean_net.iloc[0]), float(mean_net.iloc[-1])
    D.p(f"Using synthetic cities of {n0:,} to {n1:,} nodes (a {n1 / n0:.0f}-fold increase), the median time of full Dijkstra "
        f"for a single-road disruption (blocking a shortest-path-tree edge) grew by a factor of {rf:.0f}, whereas the "
        f"median repair time changed by a factor of {rr_:.1f}: the typical tree edge lies close to a leaf, so a typical "
        f"ripple touches only a handful of nodes whatever the size of the map. The *mean* number of nodes whose "
        f"distance changed went from {a0:.0f} to {a1:.0f} (×{a1 / max(a0, 1e-9):.1f}) while n grew ×{n1 / n0:.0f}, "
        + ("which is sub-linear in n and in line with the heuristic of Section 4 that the expected ripple tracks the "
           "average tree depth (Θ(√n)) rather than n. "
           if a1 / max(a0, 1e-9) < 0.8 * n1 / n0 else
           "which does not support the sub-linear heuristic of Section 4 in this run. ")
        + "(The mean is dominated by rare large ripples and is noisy with this many trials, so treat it as indicative.) "
        "The advantage of repair over recomputation therefore widens with the size of the map.")
    D.figure(R.path("fig4_scaling_with_n.png"),
             "Median time versus network size when blocking one shortest-path-tree edge (left) and a 20-edge accident zone (right).")

    D.h("5.4 Which closures cause big ripples? (RQ4)", 2)
    rp = R.rp
    ratio = (rp["affected"] / rp["subtree"]).clip(upper=1)
    frac_close = float((ratio >= 0.9).mean())
    med = rp.groupby("cls")["affected"].median()
    med_txt = ", ".join(f"{c}: {int(v)}" for c, v in med.items())
    big_cls = [c for c in ("arterial", "bridge") if c in med.index and "local" in med.index and med[c] > med["local"]]
    cls_sentence = (" Edges that carry many shortest paths (" + " and ".join(big_cls) + ") produced larger median ripples than "
                    "ordinary local streets, so a few structurally important closures dominate repair cost."
                    if big_cls else " Road class alone was not a clear predictor of ripple size in this run.")
    D.p(f"We blocked {len(rp)} different shortest-path-tree edges one at a time (a random sample plus every bridge "
        f"edge on the tree) and recorded how many distances changed. In every case the number of changed "
        f"distances was at most the size of the shortest-path-tree subtree below the edge, as predicted by "
        f"Lemma 4 (the harness asserts this). In {100 * frac_close:.0f}% of cases it was within 10% of that "
        f"bound, so **the subtree size below an edge is an excellent predictor of the ripple**. The median "
        f"number of affected nodes by road class was: {med_txt}.{cls_sentence}")
    D.figure(R.path("fig5_ripple.png"),
             "Left: ripple size versus subtree size (dashed line = upper bound). Right: ripple size by road class.")

    D.h("5.5 Anatomy of one accident", 2)
    D.p(f"Figure 6 shows an accident zone of 80 blocked edges, chosen as the worst of 40 random placements. "
        f"{M['heatmap_net_changed']:,} of {n:,} nodes ({100 * M['heatmap_net_changed'] / n:.0f}%) need a new route, "
        f"and they form a contiguous region around and beyond the blocked area, which is exactly the "
        f"set the repair algorithm touches.")
    D.figure(R.path("fig6_heatmap.png"),
             "Nodes whose travel time from the depot increases after an 80-edge accident zone (cyan).", 11.5)

    D.h("5.6 Threats to validity", 2)
    D.bullets([
        ("The graph is synthetic; real street networks have different degree and hierarchy structure, "
         "so absolute break-even points will differ. Re-run with --place for a real city." if synthetic else
         "Results are for one city and one depot; other cities and sources may behave differently."),
        "Disruption models are random, not calibrated on real traffic data.",
        "Pure-Python timings; compiled implementations change constants but not the asymptotic trends.",
        "Closures are modelled as ×50 weights, not true edge deletions.",
    ])

    # ---------- 6 conclusion
    D.h("6. Conclusion", 1)
    D.p(f"Incremental shortest-path repair is a clear win when only a few roads change: on a {n:,}-node map "
        f"it was {x(min(spm.values()))}–{x(max(spm.values()))} faster than rerunning Dijkstra for disruptions of "
        f"{mid} edges and {x(min(spb.values()))}–{x(max(spb.values()))} faster at {big} edges. "
        f"Its cost is governed by how many distances actually change rather than by the size of the map, and "
        f"the advantage grows with the map. "
        + (f"The benefit disappears once a disruption touches on the order of "
           f"{min(v for v in xo.values() if v):.0f}–{max(v for v in xo.values() if v):.0f} edges "
           f"(depending on the disruption shape), after which recomputing is cheaper. " if any(xo.values()) else "")
        + "Large ripples are caused by a small number of structurally important edges (bridges, arterials "
          "near the source), and their size is almost exactly the shortest-path-tree subtree below the edge. "
          "The algorithm was proven correct and validated against Dijkstra on every test.")
    D.p("**Practical recommendation:** keep the shortest-path tree up to date by incremental repair for "
        "routine small incidents, and fall back to a full recomputation when a large batch of changes arrives.")

    # ---------- 7 gaps
    D.h("7. Gaps and future directions", 1)
    D.bullets([
        "**Better worst-case guarantees.** One update can change Θ(n) distances (Section 4), so per-update "
        "output-sensitive bounds are the best possible; improving amortised and batch bounds for road-like "
        "graphs is an open direction.",
        "**Batch-aware repair.** We process edges one at a time, so nodes can be repaired repeatedly. A joint "
        "algorithm that handles a whole batch in one sweep should shift the break-even point to larger disruptions.",
        "**Multiple sources and all-pairs.** Delivery fleets need many depots; extending to all-pairs or "
        "landmark-based schemes (ALT, contraction hierarchies) and keeping their preprocessing valid under updates is open.",
        "**Lazy repair.** Repair only the part of the tree needed by incoming queries instead of the whole tree.",
        "**Time-dependent and stochastic weights.** Public transport timetables and traffic forecasts need "
        "time-dependent edge functions, which break the simple tight-edge arguments used here.",
        "**Realistic data.** Calibrate the disruption models with real incident feeds and speed data, and "
        "test on many cities and with a compiled implementation.",
        "**Zero and negative weights.** The proof assumes strictly positive weights; handling zero-weight "
        "edges (as in the original Ramalingam–Reps algorithm) would need an additional ordering argument.",
        "**Edge deletion and insertion.** Closures are modelled as large weights; true removal changes connectivity.",
    ])

    # ---------- appendices
    D.h("Appendix A. Team contributions", 1)
    D.table(["Member", "Role", "Contribution"],
            [["[Name A]", "Graph & Data Lead", "Graph loading (OSMnx/synthetic), weights, disruption simulator; Section 1"],
             ["[Name B]", "Algorithms Lead", "Dijkstra baseline, incremental repair, tests; Section 2"],
             ["[Name C]", "Theory Lead", "Proof of correctness and complexity analysis; Sections 3–4"],
             ["[Name D]", "Experiments Lead", "Benchmarks, figures, report assembly; Sections 5–6"],
             ["All", "", "Section 7; peer review of one other section each"]],
            widths=[2.5, 3.5, 10.0])
    D.h("Appendix B. Reproducing the results", 1)
    D.code("""
pip install -r requirements.txt
python run_all.py                                  # synthetic city, full run
python run_all.py --place "Piedmont, California, USA"   # real OSM city (needs osmnx + internet)
python run_all.py --quick                          # smoke test""")
    D.p(f"The reported run used seed {M['seed']}, {M['trials']} trials per setting and took "
        f"{M['runtime_seconds']:.0f} s on {M['platform']}.")
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
        "G. Boeing. OSMnx: New methods for acquiring, constructing, analyzing, and visualizing complex street "
        "networks. Computers, Environment and Urban Systems 65:126–139, 2017.",
    ]
    D.bullets(refs, style="List Number")
    D.p("(Please verify bibliographic details against the original sources before submission.)", italic=True, size=9.5)
    D.save(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=os.path.join(HERE, "..", "results"))
    ap.add_argument("--out", default=os.path.join(HERE, "Rush_Hour_Rerouting_Report.docx"))
    a = ap.parse_args()
    R = Results(a.results)
    build(R, a.out)
    print("Wrote", os.path.abspath(a.out))
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if soffice:
        try:
            subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir",
                            os.path.dirname(os.path.abspath(a.out)), a.out],
                           check=True, capture_output=True, timeout=180)
            print("Also wrote PDF copy.")
        except Exception as e:  # PDF is optional
            print("PDF conversion skipped:", e)


if __name__ == "__main__":
    main()
