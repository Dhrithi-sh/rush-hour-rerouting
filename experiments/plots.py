"""All figures. One colour per method in every figure (Okabe-Ito colourblind-safe
palette); disruption models get their own, separate colours/markers."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

INF = float("inf")

# Okabe & Ito (2008) palette
OI = {"black": "#000000", "orange": "#E69F00", "sky": "#56B4E9", "green": "#009E73",
      "yellow": "#F0E442", "blue": "#0072B2", "vermillion": "#D55E00", "purple": "#CC79A7"}
GREY = "#999999"

METHOD_COLORS = {"dijkstra": OI["black"], "full Dijkstra": OI["black"],
                 "Dijkstra to t": GREY, "A*": OI["orange"],
                 "sequential": OI["blue"], "batch": OI["vermillion"], "batch repair": OI["vermillion"],
                 "LPA*": OI["green"]}
METHOD_LABELS = {"dijkstra": "full Dijkstra", "sequential": "repair, edge by edge",
                 "batch": "batch repair"}
MODE_COLORS = {"single": OI["sky"], "cluster": OI["purple"], "wave": OI["orange"], "tree": OI["black"]}
MODE_MARKERS = {"single": "o", "cluster": "s", "wave": "D", "tree": "^"}
LABELS = {"single": "Scattered closures", "cluster": "Accident zone",
          "wave": "Congestion wave", "tree": "Tree-edge closures"}


def style():
    plt.rcParams.update({"figure.dpi": 150, "savefig.bbox": "tight", "axes.grid": True,
                         "grid.alpha": .3, "axes.spines.top": False,
                         "axes.spines.right": False, "font.size": 10})


def _sel(summ, mode, method, phase="block"):
    return summ[(summ["mode"] == mode) & (summ["phase"] == phase)
                & (summ["method"] == method)].sort_values("size")


def fig_speedup(summ, path, n, modes, methods):
    fig, axes = plt.subplots(1, len(modes), figsize=(3.2 * len(modes), 3.7), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, mode in zip(axes, modes):
        for method in methods:
            s = _sel(summ, mode, method)
            c = METHOD_COLORS[method]
            ax.plot(s["size"], s["speedup_med"], "-", marker="o", ms=3, color=c,
                    label=f"{METHOD_LABELS[method]}: all")
            ax.fill_between(s["size"], s["speedup_q25"], s["speedup_q75"], color=c, alpha=.12)
            e = s.dropna(subset=["speedup_eff_med"])
            ax.plot(e["size"], e["speedup_eff_med"], ":", marker="^", ms=3, color=c,
                    label=f"{METHOD_LABELS[method]}: effective only")
        ax.axhline(1, color="k", lw=1)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_title(LABELS[mode], fontsize=10)
        ax.set_xlabel("disruption size (edges)")
    axes[0].set_ylabel("speed-up over full Dijkstra (×)")
    axes[0].legend(fontsize=7, loc="lower left")
    fig.suptitle(f"Repair vs. full Dijkstra when blocking roads (n = {n:,} nodes; "
                 "line = median, band = IQR, black line = break-even)", fontsize=10)
    fig.savefig(path); plt.close(fig)


def fig_runtime(summ, path, modes, methods):
    fig, axes = plt.subplots(1, len(modes), figsize=(3.2 * len(modes), 3.5), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, mode in zip(axes, modes):
        for method in methods:
            s = _sel(summ, mode, method)
            c = METHOD_COLORS[method]
            ax.plot(s["size"], s["t_repair_ms"], "o-", ms=3, color=c, label=f"{METHOD_LABELS[method]}")
            ax.fill_between(s["size"], s["t_repair_ms_q25"], s["t_repair_ms_q75"], color=c, alpha=.12)
            e = s.dropna(subset=["t_repair_eff_ms"])
            ax.plot(e["size"], e["t_repair_eff_ms"], ":", ms=3, color=c)
        s = _sel(summ, mode, methods[0])
        ax.plot(s["size"], s["t_full_ms"], "s--", ms=3, color=METHOD_COLORS["dijkstra"],
                label=METHOD_LABELS["dijkstra"])
        ax.fill_between(s["size"], s["t_full_ms_q25"], s["t_full_ms_q75"],
                        color=METHOD_COLORS["dijkstra"], alpha=.1)
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_title(LABELS[mode], fontsize=10)
        ax.set_xlabel("disruption size (edges)")
    axes[0].set_ylabel("median time per disruption (ms)")
    axes[0].legend(fontsize=7)
    fig.suptitle("Time per disruption (solid = all trials with IQR band, dotted = effective only)",
                 fontsize=10)
    fig.savefig(path); plt.close(fig)


def fig_affected(summ, path, n, modes):
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    for mode in modes:
        s = _sel(summ, mode, "batch")
        ax.plot(s["size"], 100 * s["net_changed_mean"] / n, "-", marker=MODE_MARKERS[mode], ms=3,
                color=MODE_COLORS[mode], label=LABELS[mode])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("disruption size (edges)")
    ax.set_ylabel("mean % of nodes whose distance changed")
    ax.set_title("How much of the map is affected?")
    ax.legend()
    fig.savefig(path); plt.close(fig)


def fig_scaling(sc, path, methods):
    scen = list(sc["scenario"].unique())
    fig, axes = plt.subplots(1, len(scen), figsize=(4.5 * len(scen), 3.6), sharey=True)
    for ax, sn in zip(np.atleast_1d(axes), scen):
        d = sc[sc["scenario"] == sn]
        full = d.groupby("n")["t_full"].median()
        for method in methods:
            s = d[d["method"] == method].groupby("n")["t_repair"].median()
            ax.plot(s.index, s.values * 1e3, "o-", color=METHOD_COLORS[method], label=METHOD_LABELS[method])
        ax.plot(full.index, full.values * 1e3, "s--", color=METHOD_COLORS["dijkstra"],
                label=METHOD_LABELS["dijkstra"])
        ax.set_xscale("log"); ax.set_yscale("log"); ax.set_title(sn)
        ax.set_xlabel("number of nodes n")
    np.atleast_1d(axes)[0].set_ylabel("median time (ms)")
    np.atleast_1d(axes)[0].legend(fontsize=8)
    fig.savefig(path); plt.close(fig)


def fig_ripple(rp, path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
    ax = axes[0]
    cols = {"local": OI["sky"], "arterial": OI["orange"], "bridge": OI["vermillion"]}
    for cls, grp in rp.groupby("cls"):
        ax.scatter(grp["subtree"], grp["affected"].clip(lower=.8), s=14, alpha=.7,
                   color=cols.get(cls, "k"), label=f"{cls} ({len(grp)})")
    mx = rp["subtree"].max()
    ax.plot([1, mx], [1, mx], "k--", lw=1, label="upper bound: y = x")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("shortest-path-tree subtree size below the edge (nodes)")
    ax.set_ylabel("nodes whose distance changed")
    ax.set_title("Ripple size vs. subtree size"); ax.legend(fontsize=8)
    ax = axes[1]
    classes = [c for c in ("local", "arterial", "bridge") if c in set(rp["cls"])]
    data = [rp[rp["cls"] == c]["affected"].values for c in classes]
    # No `labels=`/`tick_labels=` keyword: its name changed in matplotlib 3.9, so the
    # tick labels are set separately (works on every supported version).
    ax.boxplot(data, showfliers=True)
    ax.set_xticks(range(1, len(classes) + 1))
    ax.set_xticklabels([f"{c}\n(n={len(d)})" for c, d in zip(classes, data)])
    ax.set_yscale("symlog", linthresh=1)
    ax.set_ylabel("nodes whose distance changed")
    ax.set_title("Effect of blocking one tree edge, by road class")
    fig.savefig(path); plt.close(fig)


def fig_heatmap(g, s, case, path):
    net, before, after, ch = case
    xs = np.array([p[0] for p in g.xy]); ys = np.array([p[1] for p in g.xy])
    delta = np.array([(a - b) / 600 if a != INF and b != INF else 0
                      for a, b in zip(after, before)])          # deciseconds -> minutes
    lost = np.array([b != INF and a == INF for a, b in zip(after, before)])
    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    ax.scatter(xs, ys, s=1, color="#d0d0d0", linewidths=0)
    mask = delta > 0
    sc = ax.scatter(xs[mask], ys[mask], c=delta[mask], s=3, cmap="viridis", linewidths=0)
    if lost.any():
        ax.scatter(xs[lost], ys[lost], s=6, marker="x", color=OI["vermillion"], linewidths=.6,
                   label=f"unreachable ({lost.sum():,})")
        ax.legend(fontsize=8, loc="lower right")
    for u, v, _, _ in ch:
        ax.plot([g.xy[u][0], g.xy[v][0]], [g.xy[u][1], g.xy[v][1]], color=OI["vermillion"], lw=1.4)
    ax.scatter([g.xy[s][0]], [g.xy[s][1]], marker="*", s=140, color="white", edgecolor="k", zorder=5)
    ax.set_aspect("equal"); ax.grid(False)
    ax.set_title(f"Accident zone ({len(ch)} blocked edges, red): {net:,} of {g.n:,} nodes re-routed\n"
                 "colour = added travel time from the depot (★)", fontsize=9)
    ax.set_xticks([]); ax.set_yticks([])
    if mask.any():
        fig.colorbar(sc, ax=ax, shrink=.7, label="extra travel time (minutes)")
    fig.savefig(path); plt.close(fig)


def fig_fleet(fl, path):
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    placements = list(fl["placement"].unique())
    sizes = sorted(fl["size"].unique())
    width = 0.8 / len(placements)
    colors = [OI["sky"], OI["purple"]]
    for j, pl in enumerate(placements):
        d = fl[fl["placement"] == pl]
        pos = np.arange(len(sizes)) + (j - (len(placements) - 1) / 2) * width
        for ax, col in zip(axes, ("routes_changed", "extra_min_mean")):
            data = [d[d["size"] == k][col].values for k in sizes]
            bp = ax.boxplot(data, positions=pos, widths=width * .9, patch_artist=True, showfliers=False)
            for b in bp["boxes"]:
                b.set_facecolor(colors[j % 2]); b.set_alpha(.7)
            ax.plot([], [], "s", color=colors[j % 2], label=f"accident {pl}")
    vehicles = int(fl["vehicles"].iloc[0])
    for ax, ylab, title in ((axes[0], "vehicles whose route changed", f"Rerouted vehicles (fleet of {vehicles})"),
                            (axes[1], "mean extra minutes per delayed vehicle", "Delay of affected vehicles")):
        ax.set_xticks(range(len(sizes)))
        ax.set_xticklabels([str(k) for k in sizes])
        ax.set_xlabel("accident zone size (edges)")
        ax.set_ylabel(ylab); ax.set_title(title, fontsize=10)
        ax.legend(fontsize=8)
    fig.savefig(path); plt.close(fig)


def fig_p2p(pp, path, methods):
    scen = list(pp["scenario"].unique())
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
    width = 0.8 / len(methods)
    for ax, phase in zip(axes, ("block", "clear")):
        d = pp[pp["phase"] == phase]
        for j, mth in enumerate(methods):
            med = [d[(d["scenario"] == sc) & (d["method"] == mth)]["time"].median() * 1e3 for sc in scen]
            q1 = [d[(d["scenario"] == sc) & (d["method"] == mth)]["time"].quantile(.25) * 1e3 for sc in scen]
            q3 = [d[(d["scenario"] == sc) & (d["method"] == mth)]["time"].quantile(.75) * 1e3 for sc in scen]
            pos = np.arange(len(scen)) + (j - (len(methods) - 1) / 2) * width
            ax.bar(pos, med, width * .9, color=METHOD_COLORS[mth], label=mth,
                   yerr=[np.subtract(med, q1), np.subtract(q3, med)], capsize=2, error_kw={"lw": .8})
        ax.set_yscale("log")
        ax.set_xticks(range(len(scen)))
        ax.set_xticklabels([sc.replace(" on the route", "\non the route") for sc in scen], fontsize=8)
        ax.set_title("blocking" if phase == "block" else "clearing", fontsize=10)
    axes[0].set_ylabel("median time to update the route (ms)")
    axes[0].legend(fontsize=7, ncol=2)
    fig.suptitle("Point-to-point rerouting depot → destination (bars = median, whiskers = IQR)", fontsize=10)
    fig.savefig(path); plt.close(fig)


def fig_cross_graph(xsum, path, graphs, methods, modes=("tree", "cluster")):
    """Speed-up vs disruption size per network (columns) and disruption model (rows)."""
    fig, axes = plt.subplots(len(modes), len(graphs), figsize=(3.3 * len(graphs), 2.9 * len(modes)),
                             sharey=True, squeeze=False)
    for i, mode in enumerate(modes):
        for j, name in enumerate(graphs):
            ax = axes[i][j]
            d = xsum[(xsum["graph"] == name) & (xsum["mode"] == mode) & (xsum["phase"] == "block")]
            for method in methods:
                s = d[d["method"] == method].sort_values("size")
                c = METHOD_COLORS[method]
                ax.plot(s["size"], s["speedup_med"], "o-", ms=3, color=c, label=METHOD_LABELS[method])
                ax.fill_between(s["size"], s["speedup_q25"], s["speedup_q75"], color=c, alpha=.12)
            ax.axhline(1, color="k", lw=1)
            ax.set_xscale("log"); ax.set_yscale("log")
            if i == 0:
                ax.set_title(name.replace("_", " "), fontsize=9)
            if i == len(modes) - 1:
                ax.set_xlabel("disruption size (edges)")
            if j == 0:
                ax.set_ylabel(f"{LABELS[mode]}\nspeed-up (×)", fontsize=9)
    axes[0][0].legend(fontsize=7, loc="lower left")
    fig.suptitle("Speed-up over full Dijkstra on each network (median, band = IQR, black line = break-even)",
                 fontsize=10)
    fig.savefig(path); plt.close(fig)
