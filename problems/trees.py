"""Problem 4 - Search trees for 8-Puzzle, Missionaries & Cannibals and
Rotating Workforce Scheduling (RWS).

Each problem is given in the standard formulation (initial state, actions,
transition model, goal test, path cost).  A generic builder records the *search
tree* (not just the solution path): every generated node with its status

    expanded  - node was taken from the frontier and its children generated
    goal      - goal test succeeded
    repeated  - state already reached (graph search: not expanded again)
    illegal   - generated but violates a constraint (pruned)
    frontier  - generated but never expanded (search stopped first)

and renders it with Graphviz (DOT -> SVG/PNG).
"""

from __future__ import annotations

import html
import shutil
import subprocess
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Hashable, Iterable


# ===========================================================================
# Generic search-tree representation
# ===========================================================================
@dataclass
class TNode:
    id: int
    state: Hashable
    parent: int | None
    action: str | None
    depth: int
    status: str = "frontier"
    order: int | None = None          # expansion order (1, 2, 3...)
    children: list[int] = field(default_factory=list)


@dataclass
class SearchTree:
    nodes: list[TNode]
    solution: list[int]               # node ids on the solution path (root..goal)
    algorithm: str

    def stats(self) -> dict:
        from collections import Counter
        c = Counter(n.status for n in self.nodes)
        return {"algorithm": self.algorithm, "nodes": len(self.nodes),
                "solution_depth": len(self.solution) - 1 if self.solution else None, **c}


def bfs_tree(initial, successors: Callable[[Hashable], Iterable[tuple[str, Hashable]]],
             is_goal: Callable[[Hashable], bool],
             is_legal: Callable[[Hashable], bool] = lambda s: True,
             max_nodes: int = 500) -> SearchTree:
    """Breadth-first GRAPH search that records every generated node."""
    nodes = [TNode(0, initial, None, None, 0)]
    if is_goal(initial):
        nodes[0].status = "goal"
        return SearchTree(nodes, [0], "BFS")
    frontier = deque([0])
    reached = {initial}
    order = 0
    goal_id = None
    while frontier and goal_id is None:
        nid = frontier.popleft()
        node = nodes[nid]
        order += 1
        node.status, node.order = "expanded", order
        for action, child in successors(node.state):
            cid = len(nodes)
            cn = TNode(cid, child, nid, action, node.depth + 1)
            nodes.append(cn)
            node.children.append(cid)
            if not is_legal(child):
                cn.status = "illegal"
            elif child in reached:
                cn.status = "repeated"
            elif is_goal(child):                 # early goal test
                cn.status = "goal"
                goal_id = cid
                break
            else:
                reached.add(child)
                frontier.append(cid)
            if len(nodes) >= max_nodes:
                break
        if len(nodes) >= max_nodes:
            break
    path = []
    k = goal_id
    while k is not None:
        path.append(k)
        k = nodes[k].parent
    return SearchTree(nodes, path[::-1], "BFS (graph search)")


def dfs_trace_tree(problem, max_nodes: int = 60, label_action=str) -> SearchTree:
    """Records the first `max_nodes` nodes of a DFS+backtracking run on a
    `search.core.SearchProblem` (in-place apply/undo).  Nodes rejected by
    `apply` are recorded as 'illegal' (pruned)."""
    state = problem.initial_state()
    nodes = [TNode(0, None, None, None, 0, "expanded", 1)]
    order = [1]
    path: list[int] = []
    done = [False]

    def rec(nid: int, depth: int) -> bool:
        for a in problem.actions(state):
            if len(nodes) >= max_nodes:
                return False
            cid = len(nodes)
            cn = TNode(cid, None, nid, label_action(a), depth + 1)
            nodes.append(cn)
            nodes[nid].children.append(cid)
            ok, tok = problem.apply(state, a)
            cn.state = problem.snapshot(state) if hasattr(problem, "snapshot") else None
            if not ok:
                cn.status = "illegal"
            elif problem.is_goal(state):
                cn.status = "goal"
                path.append(cid)
                problem.undo(state, tok)
                return True
            else:
                order[0] += 1
                cn.status, cn.order = "expanded", order[0]
                if rec(cid, depth + 1):
                    path.append(cid)
                    problem.undo(state, tok)
                    return True
            problem.undo(state, tok)
        return False

    found = rec(0, 0)
    sol = ([0] + path[::-1]) if found else []
    # a node that was "expanded" but got cut by max_nodes before finishing
    return SearchTree(nodes, sol, "DFS + backtracking")


# ===========================================================================
# Graphviz rendering
# ===========================================================================
STYLE = {
    "expanded": dict(fillcolor="#E8F0FE", color="#3B6FD8"),
    "goal":     dict(fillcolor="#D7F5DD", color="#1E8E3E", penwidth="2.5"),
    "repeated": dict(fillcolor="#F1F3F4", color="#9AA0A6", fontcolor="#80868B", style="filled,dashed"),
    "illegal":  dict(fillcolor="#FCE8E6", color="#D93025", fontcolor="#A50E0E", style="filled,dashed"),
    "frontier": dict(fillcolor="#FFF7E0", color="#E37400"),
}


def to_dot(tree: SearchTree, label: Callable[[TNode], str], title: str,
           html_labels: bool = False, rankdir: str = "TB") -> str:
    on_path = set(tree.solution)
    out = [
        "digraph G {",
        f'  graph [rankdir={rankdir}, labelloc=t, fontsize=20, fontname="Helvetica", '
        f'label=<<b>{html.escape(title)}</b>>, nodesep=0.15, ranksep=0.45, bgcolor="white"];',
        '  node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=10, margin="0.06,0.03"];',
        '  edge [fontname="Helvetica", fontsize=9, color="#5F6368", arrowsize=0.6];',
    ]
    for n in tree.nodes:
        st = dict(STYLE[n.status])
        if n.id in on_path and n.status != "goal":
            st["penwidth"] = "2.2"
            st["color"] = "#1E8E3E"
        attrs = ", ".join(f'{k}="{v}"' for k, v in st.items())
        lab = label(n)
        if html_labels:
            out.append(f"  n{n.id} [label=<{lab}>, {attrs}];")
        else:
            lab = lab.replace('"', r'\"')
            out.append(f'  n{n.id} [label="{lab}", {attrs}];')
    for n in tree.nodes:
        if n.parent is not None:
            ep = ' color="#1E8E3E", penwidth=2.2' if n.id in on_path and n.parent in on_path else ""
            out.append(f'  n{n.parent} -> n{n.id} [label="{n.action}",{ep}];')
    # legend
    out.append('  subgraph cluster_legend { label="Legjenda"; fontsize=11; color="#DADCE0"; style=rounded;')
    for k, txt in [("expanded", "e zgjeruar (#rendi)"), ("goal", "qëllimi"),
                   ("repeated", "gjendje e përsëritur"), ("illegal", "e paligjshme / prunuar"),
                   ("frontier", "në frontier")]:
        attrs = ", ".join(f'{a}="{v}"' for a, v in STYLE[k].items())
        out.append(f'    lg_{k} [label="{txt}", {attrs}];')
    out.append("    lg_expanded -> lg_goal -> lg_repeated -> lg_illegal -> lg_frontier [style=invis]; }")
    out.append("}")
    return "\n".join(out)


def render(dot_src: str, out_base: Path) -> list[Path]:
    out_base.parent.mkdir(parents=True, exist_ok=True)
    dot_path = out_base.with_suffix(".dot")
    dot_path.write_text(dot_src, encoding="utf-8")
    produced = [dot_path]
    if shutil.which("dot"):
        for fmt_ in ("svg", "png"):
            p = out_base.with_suffix("." + fmt_)
            extra = ["-Gdpi=110"] if fmt_ == "png" else []
            subprocess.run(["dot", f"-T{fmt_}", *extra, str(dot_path), "-o", str(p)], check=True)
            produced.append(p)
    return produced


# ===========================================================================
# 4a. 8-Puzzle
# ===========================================================================
PUZZLE_GOAL = (1, 2, 3, 4, 5, 6, 7, 8, 0)
_MOVES = {"Lart": -3, "Poshtë": 3, "Majtas": -1, "Djathtas": 1}   # moves of the blank


def puzzle_successors(s):
    z = s.index(0)
    r, c = divmod(z, 3)
    for name, d in _MOVES.items():
        if (name == "Lart" and r == 0) or (name == "Poshtë" and r == 2) or \
           (name == "Majtas" and c == 0) or (name == "Djathtas" and c == 2):
            continue
        t = list(s)
        t[z], t[z + d] = t[z + d], t[z]
        yield name, tuple(t)


def puzzle_solvable(s) -> bool:
    """For a 3x3 board: solvable <=> number of inversions (ignoring blank) is even."""
    a = [x for x in s if x]
    inv = sum(1 for i in range(len(a)) for j in range(i + 1, len(a)) if a[i] > a[j])
    return inv % 2 == 0


def puzzle_label(n: TNode) -> str:
    s = n.state
    cells = []
    for r in range(3):
        row = "".join(
            f'<td width="16" height="16" bgcolor="{"#202124" if v == 0 else "white"}">'
            f'<font color="{"#202124" if v == 0 else "#202124"}">{v if v else " "}</font></td>'
            for v in s[r * 3:(r + 1) * 3])
        cells.append(f"<tr>{row}</tr>")
    head = f"#{n.order}" if n.order else n.status
    return (f'<table border="0" cellborder="1" cellspacing="0" cellpadding="1">'
            f'<tr><td colspan="3" border="0"><font point-size="8">{head} · g={n.depth}</font></td></tr>'
            f'{"".join(cells)}</table>')


# ===========================================================================
# 4b. Missionaries and Cannibals
# ===========================================================================
MC_START = (3, 3, 1)            # (missionaries left, cannibals left, boat on left?)
MC_GOAL = (0, 0, 0)
_BOAT = [(1, 0), (2, 0), (0, 1), (0, 2), (1, 1)]


def mc_successors(s):
    m, c, b = s
    sign = -1 if b == 1 else 1
    for dm, dc in _BOAT:
        nm, nc = m + sign * dm, c + sign * dc
        if 0 <= nm <= 3 and 0 <= nc <= 3:       # physically possible move
            yield f"{dm}M{dc}K {'→' if b else '←'}", (nm, nc, 1 - b)


def mc_legal(s) -> bool:
    m, c, _ = s
    return (m == 0 or m >= c) and (3 - m == 0 or 3 - m >= 3 - c)


def mc_label(n: TNode) -> str:
    m, c, b = n.state
    left = "M" * m + "K" * c or "∅"
    right = "M" * (3 - m) + "K" * (3 - c) or "∅"
    boat = "⛵|" if b else "|⛵"
    head = f"#{n.order}" if n.order else n.status
    return f"{head}\n{left} {boat} {right}\n({m},{c},{b})"


# ===========================================================================
# 4c. Rotating Workforce Scheduling
# ===========================================================================
@dataclass
class RWSInstance:
    """Cyclic schedule of `employees` weeks (row e = week e of the rotation).
    Shift codes: 'D' day, 'N' night, '-' day off."""
    employees: int = 3
    shifts: tuple[str, ...] = ("D", "N")
    demand: dict[str, tuple[int, ...]] = field(default_factory=lambda: {
        "D": (1, 1, 1, 1, 1, 1, 1),
        "N": (1, 1, 1, 1, 1, 0, 0),
    })
    work_block: tuple[int, int] = (2, 5)      # min/max consecutive working days
    off_block: tuple[int, int] = (1, 3)       # min/max consecutive days off
    shift_block: dict[str, tuple[int, int]] = field(default_factory=lambda: {"D": (1, 4), "N": (1, 3)})
    forbidden: tuple[tuple[str, str], ...] = (("N", "D"),)   # no Day right after Night

    @property
    def length(self) -> int:
        return 7 * self.employees


def _runs_cyclic(seq: list[str], key) -> list[tuple[object, int]]:
    """Maximal runs of equal key(x) in a cyclic sequence (rotated to a run start)."""
    L = len(seq)
    ks = [key(x) for x in seq]
    if all(k == ks[0] for k in ks):
        return [(ks[0], L)]
    start = next(i for i in range(L) if ks[i] != ks[i - 1])
    runs, cur, n = [], ks[start], 0
    for j in range(L):
        k = ks[(start + j) % L]
        if k == cur:
            n += 1
        else:
            runs.append((cur, n))
            cur, n = k, 1
    runs.append((cur, n))
    return runs


def rws_violations(inst: RWSInstance, seq: list[str]) -> int:
    """Objective function f(x): total number of violated constraints (0 = feasible)."""
    v = 0
    for d in range(7):
        col = [seq[e * 7 + d] for e in range(inst.employees)]
        for s in inst.shifts:
            v += abs(col.count(s) - inst.demand[s][d])
    for is_work, n in _runs_cyclic(seq, lambda x: x != "-"):
        lo, hi = inst.work_block if is_work else inst.off_block
        v += (n < lo) + (n > hi)
    for s_, n in _runs_cyclic(seq, lambda x: x):
        if s_ in inst.shift_block:
            lo, hi = inst.shift_block[s_]
            v += (n < lo) + (n > hi)
    L = len(seq)
    v += sum(1 for i in range(L) if (seq[i - 1], seq[i]) in inst.forbidden)
    return v


class RWSProblem:
    """Incremental formulation for DFS: assign day t = 0..7n-1 in time order."""

    def __init__(self, inst: RWSInstance):
        self.inst = inst
        self.values = list(inst.shifts) + ["-"]

    def initial_state(self):
        return {"seq": [], "count": [[0] * 7 for _ in self.values]}

    def snapshot(self, s):
        return tuple(s["seq"])

    def copy(self, s):
        return {"seq": s["seq"][:], "count": [c[:] for c in s["count"]]}

    def is_goal(self, s) -> bool:
        return len(s["seq"]) == self.inst.length

    def actions(self, s):
        if len(s["seq"]) < self.inst.length:
            yield from self.values

    def apply(self, s, v):
        inst, seq = self.inst, s["seq"]
        t = len(seq)
        d = t % 7
        vi = self.values.index(v)
        seq.append(v)
        s["count"][vi][d] += 1
        return self._consistent(s, t, d), (vi, d)

    def undo(self, s, tok):
        vi, d = tok
        s["seq"].pop()
        s["count"][vi][d] -= 1

    def _consistent(self, s, t, d) -> bool:
        inst, seq = self.inst, s["seq"]
        v = seq[-1]
        # (1) column demand: never exceed, and the cells left in the column must be able
        #     to cover the shifts still missing
        left_in_col = inst.employees - 1 - t // 7
        missing = 0
        for i, sh in enumerate(inst.shifts):
            have, want = s["count"][i][d], inst.demand[sh][d]
            if have > want:
                return False
            missing += want - have
        if missing > left_in_col:
            return False
        # (2) forbidden successions
        if t > 0 and (seq[-2], v) in inst.forbidden:
            return False
        # (3) maximum block lengths (work / off / per shift) of the run ending at t
        def run_len(pred):
            n = 0
            for x in reversed(seq):
                if pred(x):
                    n += 1
                else:
                    break
            return n, n == len(seq)
        w = v != "-"
        n, from_start = run_len(lambda x: (x != "-") == w)
        if n > (inst.work_block if w else inst.off_block)[1]:
            return False
        if v in inst.shift_block:
            m, _ = run_len(lambda x: x == v)
            if m > inst.shift_block[v][1]:
                return False
        # (4) minimum block lengths for a run that has just closed (not the first run,
        #     which may continue cyclically from the end)
        if t > 0 and (seq[-2] != "-") != w:
            prev_w = not w
            k = 0
            for x in reversed(seq[:-1]):
                if (x != "-") == prev_w:
                    k += 1
                else:
                    break
            if k < t and k < (inst.work_block if prev_w else inst.off_block)[0]:
                return False
        # (5) complete cyclic check at the last cell
        if t == inst.length - 1:
            return rws_violations(inst, seq) == 0
        return True


def rws_label(n: TNode) -> str:
    """Compact: expansion order + the current week row being filled (t = day index)."""
    if n.state is None:
        return "#1  (bosh)"
    seq = "".join(n.state)
    t = len(seq) - 1
    week, day = divmod(t, 7)
    row = seq[week * 7:]
    head = f"#{n.order}" if n.order else ("✗" if n.status == "illegal" else n.status)
    return f"{head}  J{week + 1}: {row:<7}"


def rws_format(inst: RWSInstance, seq) -> str:
    days = ["Hë", "Ma", "Më", "En", "Pr", "Sh", "Di"]
    out = ["        " + "  ".join(days)]
    for e in range(inst.employees):
        out.append(f"Java {e + 1}:  " + "   ".join(seq[e * 7:(e + 1) * 7]))
    return "\n".join(out)
