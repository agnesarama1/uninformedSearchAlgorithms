"""Landscape analysis for the three CSPs.

"Landscape" = the search space together with the objective function f defined on it.
We measure it three ways:

1. Analytic size  - |S| for the naive representation and for the representation we
                    actually search (constraints built into the encoding).
2. Distribution of f on uniformly random complete configurations (how far a random
   point is from feasibility; how rare f=0 is).
3. Ruggedness     - random walk under a 1-move neighbourhood; autocorrelation
   rho(1) of f along the walk and correlation length  l = -1 / ln|rho(1)|
   (Weinberger 1990).  Large l = smooth landscape, small l = rugged.

Plus 4. the *search-tree* profile of the uninformed algorithms (nodes per depth /
per IDDFS iteration) which is the landscape the tree searches actually see.

Run:  python landscape.py            -> results/landscape.json + results/fig_*.png
"""

from __future__ import annotations

import json
import math
import random
from collections import Counter
from itertools import combinations
from math import comb, factorial, log10
from pathlib import Path

from problems import golfers as G
from problems import latin as L
from problems import sudoku as SD
from search.core import Budget, breadth_first_search, iterative_deepening_dfs

OUT = Path(__file__).parent / "results"
RNG = random.Random(2026)


# ---------------------------------------------------------------------------
# objective functions on complete configurations
# ---------------------------------------------------------------------------
UNITS = ([[r * 9 + c for c in range(9)] for r in range(9)] +
         [[r * 9 + c for r in range(9)] for c in range(9)] +
         [[(br * 3 + r) * 9 + bc * 3 + c for r in range(3) for c in range(3)]
          for br in range(3) for bc in range(3)])


def f_sudoku(cells):
    """number of conflicting pairs over the 27 units"""
    return sum(sum(v * (v - 1) // 2 for v in Counter(cells[i] for i in u).values()) for u in UNITS)


def f_latin(grid):
    n = len(grid)
    s = 0
    for k in range(n):
        s += n - len(set(grid[k]))
        s += n - len({grid[r][k] for r in range(n)})
    return s


# ---------------------------------------------------------------------------
# random configurations, two representations each
# ---------------------------------------------------------------------------
def rand_sudoku_naive(givens):
    return [g or RNG.randint(1, 9) for g in givens]


def rand_sudoku_rowperm(givens):
    """each row is a permutation that respects the row's clues (row constraint built in)"""
    cells = []
    for r in range(9):
        row = givens[r * 9:(r + 1) * 9]
        missing = [d for d in range(1, 10) if d not in row]
        RNG.shuffle(missing)
        it = iter(missing)
        cells += [v or next(it) for v in row]
    return cells


def rand_latin_naive(n):
    return [[RNG.randint(1, n) for _ in range(n)] for _ in range(n)]


def rand_latin_rowperm(n):
    rows = []
    for _ in range(n):
        p = list(range(1, n + 1))
        RNG.shuffle(p)
        rows.append(p)
    return rows


def rand_golf_week(n=32, p=4):
    x = list(range(n))
    RNG.shuffle(x)
    return [x[i:i + p] for i in range(0, n, p)]


def rand_golf_naive(n=32, p=4, w=10):
    """each slot any golfer (week partition not enforced) -> f counts both C1 and C2"""
    weeks = [[[RNG.randrange(n) for _ in range(p)] for _ in range(n // p)] for _ in range(w)]
    c1 = sum(n - len({x for g in wk for x in g}) for wk in weeks)
    return c1 + G.objective(weeks)


def rand_golf_partition(n=32, p=4, w=10):
    return G.objective([rand_golf_week(n, p) for _ in range(w)])


# ---------------------------------------------------------------------------
# random walks (ruggedness)
# ---------------------------------------------------------------------------
def autocorr(series, lag=1):
    m = sum(series) / len(series)
    var = sum((x - m) ** 2 for x in series)
    if var == 0:
        return 1.0
    return sum((series[i] - m) * (series[i + lag] - m) for i in range(len(series) - lag)) / var


def walk_sudoku(givens, steps=3000):
    cells = rand_sudoku_rowperm(givens)
    free = [[c for c in range(9) if givens[r * 9 + c] == 0] for r in range(9)]
    fs = []
    for _ in range(steps):
        r = RNG.randrange(9)
        if len(free[r]) >= 2:
            a, b = RNG.sample(free[r], 2)
            i, j = r * 9 + a, r * 9 + b
            cells[i], cells[j] = cells[j], cells[i]       # swap inside row
        fs.append(f_sudoku(cells))
    return fs


def walk_latin(n, steps=3000):
    g = rand_latin_rowperm(n)
    fs = []
    for _ in range(steps):
        r = RNG.randrange(n)
        a, b = RNG.sample(range(n), 2)
        g[r][a], g[r][b] = g[r][b], g[r][a]
        fs.append(f_latin(g))
    return fs


def walk_golf(w=10, steps=3000):
    weeks = [rand_golf_week() for _ in range(w)]
    fs = []
    for _ in range(steps):
        wk = weeks[RNG.randrange(w)]
        g1, g2 = RNG.sample(range(len(wk)), 2)
        a, b = RNG.randrange(4), RNG.randrange(4)
        wk[g1][a], wk[g2][b] = wk[g2][b], wk[g1][a]      # swap golfers between groups
        fs.append(G.objective(weeks))
    return fs


def corr_length(rho):
    return float("inf") if abs(rho) >= 1 else (-1 / math.log(abs(rho)) if rho else 0.0)


# ---------------------------------------------------------------------------
LATIN_SQUARES = {5: 161280, 8: 108776032459082956800}      # OEIS A002860


def sudoku_sizes(puzzle):
    givens = SD.parse(puzzle)
    e = givens.count(0)
    rows = [givens[r * 9:(r + 1) * 9] for r in range(9)]
    st = SD.Sudoku(puzzle).initial_state()
    return {"empty": e, "naive_9^e": round(e * log10(9), 2),
            "product_of_domains": round(sum(log10(SD.Sudoku.candidates(st, i).bit_count())
                                            for i in range(81) if givens[i] == 0), 2),
            "row_permutations": round(sum(log10(factorial(row.count(0))) for row in rows), 2),
            "valid_sudoku_grids_total": 21.82}                  # 6.67e21 (Felgenhauer & Jarvis)


def latin_sizes(n):
    return {"naive_n^(n^2)": round(n * n * log10(n), 2),
            "row_permutations_(n!)^n": round(n * log10(factorial(n)), 2),
            "reduced_cells_n^((n-1)^2)": round((n - 1) ** 2 * log10(n), 2),
            "latin_squares_L(n)": round(log10(LATIN_SQUARES[n]), 2)}


def analytic():
    """log10 of space sizes."""
    part = factorial(32) // (factorial(4) ** 8 * factorial(8))
    return {
        **{f"sudoku_{lvl}": sudoku_sizes(p) for lvl, p in SD.PUZZLES.items()},
        **{f"latin_n{n}": latin_sizes(n) for n in LATIN_SQUARES},
        "golfers_8_4_10": {"naive_32^(320)": round(320 * log10(32), 2),
                           "partition_per_week": round(log10(part), 2),
                           "partitions^10": round(10 * log10(part), 2),
                           "after_S1_S4": round(9 * log10(part) - log10(factorial(9)), 2),
                           "subspace_model_C(155,10)": round(log10(comb(155, 10)), 2)},
    }


def sample_f(samples=4000):
    data = {}
    for lvl, puzzle in SD.PUZZLES.items():
        givens = SD.parse(puzzle)
        data[f"Sudoku ({lvl})"] = ([f_sudoku(rand_sudoku_naive(givens)) for _ in range(samples)],
                                   [f_sudoku(rand_sudoku_rowperm(givens)) for _ in range(samples)])
    for n in LATIN_SQUARES:
        data[f"Latin square (n={n})"] = ([f_latin(rand_latin_naive(n)) for _ in range(samples)],
                                         [f_latin(rand_latin_rowperm(n)) for _ in range(samples)])
    data["Social golfers (8-4-10)"] = ([rand_golf_naive() for _ in range(samples // 4)],
                                       [rand_golf_partition() for _ in range(samples // 4)])
    return data


def search_profiles():
    prof = {}
    for name, o, pr in [("static", "static", False), ("MRV", "mrv", False), ("MRV + propagim", "mrv", True)]:
        _, st = breadth_first_search(SD.Sudoku(SD.PUZZLES["hard"], o, pr), Budget(max_seconds=60))
        prof[name] = dict(sorted(st.nodes_per_depth.items()))
    _, st = iterative_deepening_dfs(L.LatinSquare(6, matching=False))
    return prof, st.nodes_per_iteration


# ---------------------------------------------------------------------------
def plot(fdata, prof, iters, path_prefix: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"     # validated categorical slots 1-3
    INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e6e5e0"
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9.5, "axes.edgecolor": MUTED,
                         "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
                         "axes.spines.top": False, "axes.spines.right": False})

    # Figure 1 - distribution of f on random configurations (small multiples)
    fig, axes = plt.subplots(2, 3, figsize=(13, 7), facecolor="#fcfcfb")
    for ax, (title, (naive, rep)) in zip(axes.flat, fdata.items()):
        ax.set_facecolor("#fcfcfb")
        lo, hi = 0, max(max(naive), max(rep))
        bins = min(60, hi - lo + 1)
        ax.hist(naive, bins=bins, range=(lo, hi), color=C1, alpha=0.85, label="naive", edgecolor="#fcfcfb", linewidth=0.6)
        ax.hist(rep, bins=bins, range=(lo, hi), color=C2, alpha=0.85, label="reprezentim i strukturuar", edgecolor="#fcfcfb", linewidth=0.6)
        ax.set_title(title, color=INK, fontsize=11, loc="left", fontweight="bold")
        ax.set_xlabel("f(x) = numri i shkeljeve")
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        ax.axvline(0, color=C3, linewidth=2)
        ax.text(0, ax.get_ylim()[1] * 0.92, " f = 0", color=INK, fontsize=8.5)
    axes[0, 0].set_ylabel("konfigurime të rastit")
    axes[1, 0].set_ylabel("konfigurime të rastit")
    axes[0, 0].legend(frameon=False, fontsize=8.5, loc="upper right")
    fig.suptitle("Landscape: shpërndarja e objective function mbi konfigurime të rastit",
                 color=INK, fontsize=12.5, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(f"{path_prefix}_objective.png", dpi=150)
    plt.close(fig)

    # Figure 2 - Sudoku BFS layer sizes (log) + IDDFS nodes per iteration
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 3.8), facecolor="#fcfcfb")
    for (name, d), col in zip(prof.items(), (C1, C2, C3)):
        xs, ys = list(d.keys()), list(d.values())
        a1.plot(xs, ys, color=col, linewidth=2, label=name)
        a1.annotate(f"{name}: max {max(ys):,}", (xs[ys.index(max(ys))], max(ys)),
                    textcoords="offset points", xytext=(4, 4), fontsize=8, color=INK)
    a1.set_yscale("log")
    a1.set_xlabel("thellësia (qeliza të mbushura nga kërkimi)")
    a1.set_ylabel("nyje të gjeneruara (log)")
    a1.set_title("Sudoku hard — BFS: madhësia e çdo shtrese", loc="left", fontweight="bold", color=INK, fontsize=11)
    a1.grid(color=GRID, linewidth=0.8)
    a1.legend(frameon=False, fontsize=8.5)
    a1.set_facecolor("#fcfcfb")

    a2.bar(range(len(iters)), iters, color=C1, width=0.75)
    a2.set_yscale("log")
    a2.set_xlabel("limiti i thellësisë L (iteracioni i IDDFS)")
    a2.set_ylabel("nyje të gjeneruara (log)")
    a2.set_title("Latin square n=6 — IDDFS pa kufi fillestar: nyje për iteracion",
                 loc="left", fontweight="bold", color=INK, fontsize=11)
    a2.annotate(f"L = D: vetëm {iters[-1]} nyje", (len(iters) - 1, iters[-1]),
                textcoords="offset points", xytext=(-150, 115), fontsize=8.5, color=INK, bbox=dict(boxstyle="round,pad=0.25", fc="#fcfcfb", ec="#e6e5e0"),
                arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    a2.grid(axis="y", color=GRID, linewidth=0.8)
    a2.set_axisbelow(True)
    a2.set_facecolor("#fcfcfb")
    fig.tight_layout()
    fig.savefig(f"{path_prefix}_search_profile.png", dpi=150)
    plt.close(fig)


def main():
    OUT.mkdir(exist_ok=True)
    res = {"analytic_log10": analytic()}
    fdata = sample_f()
    res["random_f"] = {k: {"naive_mean": round(sum(a) / len(a), 2), "naive_min": min(a),
                           "structured_mean": round(sum(b) / len(b), 2), "structured_min": min(b),
                           "P(f=0)_observed": sum(1 for x in b if x == 0) / len(b)}
                       for k, (a, b) in fdata.items()}
    rug = {}
    walks = [(f"Sudoku ({lvl}), swap brenda rreshtit", walk_sudoku(SD.parse(p))) for lvl, p in SD.PUZZLES.items()]
    walks += [(f"Latin n={n}, swap brenda rreshtit", walk_latin(n)) for n in LATIN_SQUARES]
    walks += [("Golfers 8-4-10, swap mes grupeve", walk_golf())]
    for name, fs in walks:
        r1 = autocorr(fs, 1)
        rug[name] = {"rho(1)": round(r1, 4), "correlation_length": round(corr_length(r1), 1),
                     "f_mean_on_walk": round(sum(fs) / len(fs), 1)}
    res["ruggedness"] = rug
    prof, iters = search_profiles()
    res["sudoku_bfs_max_layer"] = {k: max(v.values()) for k, v in prof.items()}
    res["latin6_iddfs_nodes_per_iteration"] = iters
    (OUT / "landscape.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
    plot(fdata, prof, iters, OUT / "fig_landscape")
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
