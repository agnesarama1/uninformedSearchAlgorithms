"""Detyra 1 - Teknikat e painformuara te kerkimit.

Usage:
    python main.py golfers [--weeks 9] [--model spread|direct|restarts|published] [--groups 8 --size 4]
    python main.py sudoku  [--level easy|medium|hard|all] [--ordering mrv|static] [--propagate]
                           [--generate] [--puzzle 81-char-string]
    python main.py latin   [--n 5] [--start-at-depth] [--ordering static|mrv] [--no-matching] [--cyclic]
    python main.py trees   [--out results/trees]
    python main.py all                         # everything, writes results/benchmarks.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from search.core import (Budget, breadth_first_search, depth_first_backtracking,
                         iterative_deepening_dfs)

ROOT = Path(__file__).parent
RESULTS = ROOT / "results"


def banner(t: str) -> None:
    print("\n" + "=" * 78 + f"\n{t}\n" + "=" * 78)


def show_stats(st) -> dict:
    s = st.summary()
    print("  " + "  ".join(f"{k}={v}" for k, v in s.items() if k != "algorithm"))
    return s


# ---------------------------------------------------------------------------
def run_golfers(a) -> dict:
    from problems import golfers as G
    n = a.groups * a.size
    ub = G.upper_bound_weeks(a.groups, a.size)
    if a.model == "published":
        if (a.groups, a.size) != (8, 4):
            sys.exit("modeli 'published' ekziston vetem per 8 grupe me nga 4 lojtare")
        weeks = G.load_published_schedule()
        banner(f"1. SOCIAL GOLFERS 8-4-10   (n=32, kufiri i siperm teorik w <= {ub})")
        print("  modeli: published   orari i publikuar i Aguado (2004), jo rezultat i DFS")
        print(f"  valid=True  f(x)={G.objective(weeks)}\n")
        print(G.fmt(weeks))
        return {"weeks": len(weeks), "source": "Aguado (2004)", "valid": True}
    banner(f"1. SOCIAL GOLFERS {a.groups}-{a.size}-{a.weeks}   (n={n}, kufiri i siperm teorik w <= {ub})")
    if a.weeks > ub:
        print(f"  E pamundur pa kerkim: {a.weeks} > floor((n-1)/(p-1)) = {ub}")
        return {"weeks": a.weeks, "solved": False, "reason": "upper bound"}
    weeks = None
    if a.model == "spread":
        d = (n - 1).bit_length()
        k = (a.size - 1).bit_length()
        if 1 << d != n or 1 << k != a.size:
            sys.exit("modeli 'spread' kerkon n dhe p fuqi te 2-shit")
        weeks, st, _ = G.solve_spread(d, k, a.weeks, budget=Budget(max_seconds=a.seconds))
    elif a.model == "restarts":
        r, st, runs = G.solve_with_restarts(a.groups, a.size, a.weeks, max_seconds=a.seconds)
        weeks = G.to_weeks(*r) if r else None
        print(f"  restarts: {runs}")
    else:
        pr = G.SocialGolfers(a.groups, a.size, a.weeks)
        sols, st = depth_first_backtracking(pr, Budget(max_seconds=a.seconds))
        weeks = G.to_weeks(pr, sols[0]) if sols else None
    print(f"  modeli: {a.model}   algoritmi: {st.algorithm}")
    s = show_stats(st)
    if weeks:
        ok = G.is_valid_schedule(weeks, n, a.size)
        print(f"  valid={ok}  f(x)={G.objective(weeks)}\n")
        print(G.fmt(weeks))
        s["valid"] = ok
    else:
        print("  pa zgjidhje" + (" (budget-i u shterua)" if st.aborted else " (e vertetuar: hapesira u shterua)"))
    return s


def run_sudoku(a) -> dict:
    from problems import sudoku as SD
    out = {}
    if a.puzzle:
        items = [("custom", a.puzzle)]
    elif a.generate:
        items = [(lvl, SD.generate(lvl, seed=a.seed)) for lvl in (["easy", "medium", "hard"] if a.level == "all" else [a.level])]
    else:
        items = [(lvl, SD.PUZZLES[lvl]) for lvl in (["easy", "medium", "hard"] if a.level == "all" else [a.level])]
    for lvl, puzzle in items:
        banner(f"2. SUDOKU [{lvl}]  clues={sum(c != '0' for c in puzzle)}  BFS + backtracking "
               f"(ordering={a.ordering}, propagim={a.propagate})")
        print(SD.fmt(SD.parse(puzzle)))
        pr = SD.Sudoku(puzzle, a.ordering, a.propagate)
        sol, st = breadth_first_search(pr, Budget(max_nodes=a.max_nodes, max_seconds=a.seconds))
        print()
        s = show_stats(st)
        if sol:
            ok = SD.is_valid_solution(sol.cells, pr.givens)
            print(f"  valid={ok}\n")
            print(SD.fmt(sol.cells))
            s["valid"] = ok
        out[lvl] = s
    return out


def run_latin(a) -> dict:
    from problems import latin as L
    banner(f"3. LATIN SQUARE n={a.n}   IDDFS + backtracking "
           f"({'start_limit = D (kufi i poshtem i sakte)' if a.start_at_depth else 'L=0,1,2,...'}, "
           f"ordering={a.ordering}, matching={not a.no_matching})")
    pr = L.LatinSquare(a.n, ordering=a.ordering, matching=not a.no_matching)
    D = pr.initial_state().empty
    sol, st = iterative_deepening_dfs(pr, Budget(max_seconds=a.seconds),
                                      start_limit=D if a.start_at_depth else 0)
    print(f"  thellesia e zgjidhjes D = {D}")
    s = show_stats(st)
    if st.aborted:
        print("  budget-i u shterua; per n te madh perdor --start-at-depth")
    if st.nodes_per_iteration and len(st.nodes_per_iteration) <= 30:
        print(f"  nyje per iteracion: {st.nodes_per_iteration}")
    if sol:
        ok = L.is_latin(sol.grid())
        print(f"  valid={ok}\n")
        print(L.fmt(sol.grid()))
        s["valid"] = ok
    if a.cyclic:
        print("\n  Konstruksioni ciklik O(n^2) (identik me shembullin e detyres):")
        print(L.fmt(L.cyclic(a.n)))
    return s


def run_trees(a) -> dict:
    from problems import trees as T
    out_dir = Path(a.out)
    banner("4. SEARCH TREES")
    res = {}
    start = (2, 0, 3, 1, 4, 6, 7, 5, 8)
    t = T.bfs_tree(start, T.puzzle_successors, lambda s: s == T.PUZZLE_GOAL, max_nodes=400)
    T.render(T.to_dot(t, T.puzzle_label, "8-Puzzle — BFS (graph search), zgjidhja në thellësinë 5",
                      html_labels=True), out_dir / "8puzzle")
    res["8puzzle"] = t.stats()
    print("  8-Puzzle:", t.stats(), "\n  zgjidhja:", " -> ".join(t.nodes[i].action for i in t.solution[1:]))

    t = T.bfs_tree(T.MC_START, T.mc_successors, lambda s: s == T.MC_GOAL, T.mc_legal, max_nodes=500)
    T.render(T.to_dot(t, T.mc_label, "Misionarët & Kanibalët — BFS (graph search), 11 kalime"),
             out_dir / "missionaries_cannibals")
    res["missionaries_cannibals"] = t.stats()
    print("  M&C:", t.stats(), "\n  zgjidhja:", " , ".join(t.nodes[i].action for i in t.solution[1:]))

    inst = T.RWSInstance()
    t = T.dfs_trace_tree(T.RWSProblem(inst), max_nodes=300)
    T.render(T.to_dot(t, T.rws_label, "Rotating Workforce Scheduling — DFS + backtracking (pema e plotë)",
                      rankdir="LR"), out_dir / "rws")
    res["rws"] = t.stats()
    print("  RWS:", t.stats())
    goal = t.nodes[t.solution[-1]].state
    print(T.rws_format(inst, goal), f"\n  f(x) = {T.rws_violations(inst, list(goal))}")
    print(f"\n  Figurat: {out_dir}/*.svg, *.png")
    return res


# ---------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("golfers")
    g.add_argument("--groups", type=int, default=8)
    g.add_argument("--size", type=int, default=4)
    g.add_argument("--weeks", type=int, default=9)
    g.add_argument("--model", choices=["spread", "direct", "restarts", "published"], default="spread")
    g.add_argument("--seconds", type=float, default=60)

    s = sub.add_parser("sudoku")
    s.add_argument("--level", choices=["easy", "medium", "hard", "all"], default="all")
    s.add_argument("--ordering", choices=["mrv", "static"], default="mrv")
    s.add_argument("--propagate", action="store_true")
    s.add_argument("--generate", action="store_true", help="gjenero enigma te reja me zgjidhje unike")
    s.add_argument("--seed", type=int, default=None)
    s.add_argument("--puzzle", type=str, default=None)
    s.add_argument("--max-nodes", type=int, default=5_000_000)
    s.add_argument("--seconds", type=float, default=120)

    l_ = sub.add_parser("latin")
    l_.add_argument("--n", type=int, default=5)
    l_.add_argument("--start-at-depth", action="store_true",
                    help="fillo nga L = D (nje iteracion) ne vend te L=0,1,2,...; per n te madh")
    l_.add_argument("--ordering", choices=["static", "mrv"], default="static")
    l_.add_argument("--no-matching", action="store_true")
    l_.add_argument("--cyclic", action="store_true")
    l_.add_argument("--seconds", type=float, default=120)

    t = sub.add_parser("trees")
    t.add_argument("--out", default=str(RESULTS / "trees"))

    sub.add_parser("all")
    a = p.parse_args(argv)

    if a.cmd == "golfers":
        run_golfers(a)
    elif a.cmd == "sudoku":
        run_sudoku(a)
    elif a.cmd == "latin":
        run_latin(a)
    elif a.cmd == "trees":
        run_trees(a)
    else:
        res = {
            "golfers_8_4_9_spread": run_golfers(p.parse_args(["golfers", "--weeks", "9"])),
            "golfers_8_4_6_restarts": run_golfers(p.parse_args(["golfers", "--weeks", "6", "--model", "restarts"])),
            "golfers_8_4_10_published": run_golfers(p.parse_args(["golfers", "--model", "published"])),
            "sudoku_mrv": run_sudoku(p.parse_args(["sudoku"])),
            "sudoku_mrv_propagate": run_sudoku(p.parse_args(["sudoku", "--propagate"])),
            "latin_5": run_latin(p.parse_args(["latin", "--n", "5", "--cyclic"])),
            "latin_30": run_latin(p.parse_args(["latin", "--n", "30", "--start-at-depth"])),
            "trees": run_trees(p.parse_args(["trees"])),
        }
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / "benchmarks.json").write_text(json.dumps(res, indent=2, ensure_ascii=False))
        print(f"\nRezultatet: {RESULTS / 'benchmarks.json'}")


if __name__ == "__main__":
    main()
