"""Generic uninformed tree-search engine.

Every problem in this project is formulated as *incremental* search: a state is a
(partial) assignment, an action assigns one more variable, and `actions()` yields only
values that are consistent with what is already assigned.  Filtering inconsistent
values at generation time is exactly what turns plain DFS/BFS/IDDFS into their
"with backtracking" variants: dead branches are cut the moment a constraint is
violated instead of being discovered only at a complete-assignment leaf.

Two execution models are supported, chosen per algorithm for efficiency:

* in-place  (`apply` / `undo`)  - O(1) memory per level, used by DFS and IDDFS.
  This is chronological backtracking in the strict sense: on failure we *undo*
  the last decision and try the next value.
* functional (`result`)          - every node owns a copy of its state, required by
  BFS because the whole frontier must coexist in memory.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Generic, Hashable, Iterable, Iterator, TypeVar

S = TypeVar("S")
A = TypeVar("A")


class SearchProblem(ABC, Generic[S, A]):
    """Incremental formulation of a constraint-satisfaction / planning problem."""

    @abstractmethod
    def initial_state(self) -> S: ...

    @abstractmethod
    def actions(self, state: S) -> Iterable[A]:
        """Consistent actions only (this is where pruning / backtracking happens)."""

    @abstractmethod
    def is_goal(self, state: S) -> bool: ...

    # --- in-place model -------------------------------------------------------
    @abstractmethod
    def apply(self, state: S, action: A) -> tuple[bool, Any]:
        """Mutate `state`; return (still_consistent, undo_token).

        `still_consistent` may be False when the action triggers constraint
        propagation that wipes out a domain; the caller must still call `undo`.
        """

    @abstractmethod
    def undo(self, state: S, token: Any) -> None: ...

    @abstractmethod
    def copy(self, state: S) -> S: ...

    # --- functional model (default built on top of the in-place one) -----------
    def result(self, state: S, action: A) -> S | None:
        child = self.copy(state)
        ok, _ = self.apply(child, action)
        return child if ok else None


@dataclass
class SearchStats:
    algorithm: str = ""
    generated: int = 0          # nodes created (children produced by actions())
    expanded: int = 0           # nodes whose children were generated
    backtracks: int = 0         # dead ends: an expanded node none of whose children survived
    pruned: int = 0             # children rejected by apply() (constraint check / propagation)
    max_depth: int = 0
    max_frontier: int = 0       # BFS: peak queue size (memory proxy)
    iterations: int = 0         # IDDFS: number of depth limits tried
    elapsed: float = 0.0
    solved: bool = False
    aborted: bool = False       # node / time budget exhausted
    nodes_per_depth: dict[int, int] = field(default_factory=dict)
    nodes_per_iteration: list[int] = field(default_factory=list)

    def bump_depth(self, d: int) -> None:
        self.nodes_per_depth[d] = self.nodes_per_depth.get(d, 0) + 1
        if d > self.max_depth:
            self.max_depth = d

    def effective_branching_factor(self) -> float:
        """b* such that N = b* + b*^2 + ... + b*^d (Russell & Norvig)."""
        n, d = self.generated, self.max_depth
        if d == 0 or n == 0:
            return 0.0
        import math
        if n <= d:                      # chain-like tree: b* <= 1
            return 1.0
        log_n = math.log(n)

        def log_total(b: float) -> float:   # log(b + b^2 + ... + b^d), overflow-safe
            if b == 1.0:
                return math.log(d)
            x = d * math.log(b)
            # log(b (b^d - 1)/(b - 1)) = log b + x + log(1 - b^-d) - log(b - 1)
            return math.log(b) + x + math.log1p(-math.exp(-x)) - math.log(b - 1)

        lo, hi = 1.0 + 1e-12, max(2.0, float(n))
        for _ in range(200):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if log_total(mid) < log_n else (lo, mid)
        return round((lo + hi) / 2, 4)

    def summary(self) -> dict[str, Any]:
        return {
            "algorithm": self.algorithm,
            "solved": self.solved,
            "aborted": self.aborted,
            "generated": self.generated,
            "expanded": self.expanded,
            "backtracks": self.backtracks,
            "pruned": self.pruned,
            "max_depth": self.max_depth,
            "max_frontier": self.max_frontier,
            "iterations": self.iterations,
            "b*": self.effective_branching_factor(),
            "time_s": round(self.elapsed, 4),
        }


class Budget:
    """Node and wall-clock limits so exponential instances terminate gracefully."""

    def __init__(self, max_nodes: int | None = None, max_seconds: float | None = None):
        self.max_nodes = max_nodes
        self.deadline = None if max_seconds is None else time.perf_counter() + max_seconds

    def exceeded(self, stats: SearchStats) -> bool:
        if self.max_nodes is not None and stats.generated >= self.max_nodes:
            return True
        # checking the clock is ~50ns; only do it every 4096 nodes
        if self.deadline is not None and (stats.generated & 0xFFF) == 0:
            return time.perf_counter() > self.deadline
        return False


# ---------------------------------------------------------------------------
# Depth-First Search with chronological backtracking (iterative, explicit stack)
# ---------------------------------------------------------------------------
def depth_first_backtracking(
    problem: SearchProblem[S, A],
    budget: Budget | None = None,
    find_all: bool = False,
    limit_solutions: int | None = None,
) -> tuple[list[S], SearchStats]:
    """Iterative DFS: no recursion limit, state mutated in place and restored via undo.

    The stack holds (actions_iterator, undo_token) per level, i.e. O(d) memory.
    Returns the list of solutions found (copies) and statistics.
    """
    stats = SearchStats(algorithm="DFS+backtracking")
    budget = budget or Budget()
    t0 = time.perf_counter()
    state = problem.initial_state()
    solutions: list[S] = []
    stats.bump_depth(0)

    if problem.is_goal(state):
        solutions.append(problem.copy(state))
        stats.solved = True
        stats.elapsed = time.perf_counter() - t0
        return solutions, stats

    stack: list[tuple[Iterator[A], Any]] = [(iter(problem.actions(state)), None)]
    stats.expanded += 1
    produced_child = [False]  # per-level flag: did any child of this node survive apply()?

    while stack:
        it, _ = stack[-1]
        action = next(it, None)
        if action is None:                       # level exhausted -> backtrack
            _, token = stack.pop()
            if not produced_child.pop():
                stats.backtracks += 1
            if token is not None:
                problem.undo(state, token)
            continue

        stats.generated += 1
        depth = len(stack)
        stats.bump_depth(depth)
        ok, token = problem.apply(state, action)
        if not ok:
            stats.pruned += 1
            problem.undo(state, token)
            continue

        produced_child[-1] = True
        if problem.is_goal(state):
            solutions.append(problem.copy(state))
            stats.solved = True
            if not find_all or (limit_solutions and len(solutions) >= limit_solutions):
                problem.undo(state, token)
                break
            problem.undo(state, token)
            continue

        if budget.exceeded(stats):
            stats.aborted = True
            problem.undo(state, token)
            break

        stats.expanded += 1
        stack.append((iter(problem.actions(state)), token))
        produced_child.append(False)

    # unwind remaining levels so the caller's state object is clean
    while stack:
        _, token = stack.pop()
        if token is not None:
            problem.undo(state, token)

    stats.elapsed = time.perf_counter() - t0
    return solutions, stats


# ---------------------------------------------------------------------------
# Breadth-First Search (tree search over consistent partial assignments)
# ---------------------------------------------------------------------------
def breadth_first_search(
    problem: SearchProblem[S, A],
    budget: Budget | None = None,
    graph_key=None,
) -> tuple[S | None, SearchStats]:
    """FIFO frontier, early goal test (on generation) - saves one full layer.

    For incremental CSP formulations with a fixed variable order the state space is
    a *tree* (each partial assignment is reachable by exactly one path), so no
    explored-set is needed.  Pass `graph_key` (state -> hashable) to enable
    graph-search duplicate elimination for problems that do have cycles.
    """
    stats = SearchStats(algorithm="BFS+backtracking")
    budget = budget or Budget()
    t0 = time.perf_counter()
    root = problem.initial_state()
    stats.bump_depth(0)
    if problem.is_goal(root):
        stats.solved = True
        stats.elapsed = time.perf_counter() - t0
        return root, stats

    frontier: deque[tuple[S, int]] = deque([(root, 0)])
    seen: set[Hashable] | None = {graph_key(root)} if graph_key else None

    while frontier:
        if len(frontier) > stats.max_frontier:
            stats.max_frontier = len(frontier)
        state, depth = frontier.popleft()
        stats.expanded += 1
        produced = False
        for action in problem.actions(state):
            stats.generated += 1
            child = problem.result(state, action)
            if child is None:                      # constraint check failed
                stats.pruned += 1
                continue
            if seen is not None:
                k = graph_key(child)
                if k in seen:
                    continue
                seen.add(k)
            produced = True
            stats.bump_depth(depth + 1)
            if problem.is_goal(child):
                stats.solved = True
                stats.elapsed = time.perf_counter() - t0
                return child, stats
            frontier.append((child, depth + 1))
            if budget.exceeded(stats):
                stats.aborted = True
                stats.elapsed = time.perf_counter() - t0
                return None, stats
        if not produced:
            stats.backtracks += 1

    stats.elapsed = time.perf_counter() - t0
    return None, stats


# ---------------------------------------------------------------------------
# Iterative Deepening DFS (depth-limited DFS with in-place backtracking)
# ---------------------------------------------------------------------------
_CUTOFF = object()


def iterative_deepening_dfs(
    problem: SearchProblem[S, A],
    budget: Budget | None = None,
    max_limit: int | None = None,
    start_limit: int = 0,
    step: int = 1,
) -> tuple[S | None, SearchStats]:
    """IDDFS that distinguishes *cutoff* from *failure* (Russell & Norvig, Fig. 3.12).

    If a depth-limited pass finishes without ever hitting the limit, the whole
    (pruned) tree has been explored and there is provably no solution - we stop
    instead of deepening forever.
    """
    stats = SearchStats(algorithm="IDDFS+backtracking")
    budget = budget or Budget()
    t0 = time.perf_counter()
    state = problem.initial_state()

    def dls(limit: int):
        """Depth-limited DFS, iterative (explicit stack) so depth is not bounded by
        Python's recursion limit (a 50x50 Latin square has goal depth 2401).

        Returns a solution copy, _CUTOFF (limit was hit somewhere) or None (failure:
        the pruned subtree was exhausted without touching the limit)."""
        if problem.is_goal(state):
            return problem.copy(state)
        if limit == 0:
            return _CUTOFF
        cutoff = False
        stats.expanded += 1
        stack: list[list] = [[iter(problem.actions(state)), None, False]]  # it, token, had_child
        result = None
        while stack:
            frame = stack[-1]
            action = next(frame[0], None)
            if action is None:                                   # backtrack
                stack.pop()
                if not frame[2]:
                    stats.backtracks += 1
                if frame[1] is not None:
                    problem.undo(state, frame[1])
                continue
            depth = len(stack)
            stats.generated += 1
            stats.bump_depth(depth)
            if budget.exceeded(stats):                           # also covers nodes at the limit
                stats.aborted = True
                break
            ok, token = problem.apply(state, action)
            if not ok:
                stats.pruned += 1
                problem.undo(state, token)
                continue
            frame[2] = True
            if problem.is_goal(state):
                result = problem.copy(state)
                problem.undo(state, token)
                break
            if depth == limit:                                   # cutoff: do not expand
                cutoff = True
                problem.undo(state, token)
                continue
            stats.expanded += 1
            stack.append([iter(problem.actions(state)), token, False])
        while stack:                                             # unwind
            frame = stack.pop()
            if frame[1] is not None:
                problem.undo(state, frame[1])
        if result is not None:
            return result
        if stats.aborted:
            return None
        return _CUTOFF if cutoff else None

    limit = start_limit
    while max_limit is None or limit <= max_limit:
        stats.iterations += 1
        before = stats.generated
        r = dls(limit)
        stats.nodes_per_iteration.append(stats.generated - before)
        if r is not _CUTOFF:
            stats.solved = r is not None
            stats.elapsed = time.perf_counter() - t0
            return r, stats
        if stats.aborted:
            break
        limit += step

    stats.elapsed = time.perf_counter() - t0
    return None, stats
