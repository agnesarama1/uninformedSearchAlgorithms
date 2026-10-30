"""Problem 3 - Latin Square solved with Iterative Deepening DFS + backtracking.

Representation (CSP):
    variables   X_{r,c},  0 <= r,c < n
    domain      {1..n}
    constraints AllDifferent(row r) for every r, AllDifferent(col c) for every c

Supports the general *quasigroup completion* problem: a partially filled grid can be
given (0 = empty), so the solver is not limited to the trivial empty grid.

Symmetry breaking (`reduced=True`): any Latin square can be brought to *reduced*
(normalised) form - first row and first column equal 1..n - by permuting columns
and then rows.  Fixing them removes 2n-1 variables from the search when the grid is
otherwise empty, and the result is still a valid answer to the task.

Matching check (`matching=True`): after X_{r,c}=v we verify that the still-empty
cells of row r and of column c can be matched one-to-one to the values still missing
in that line (bipartite perfect matching, Kuhn's augmenting paths, warm-started from
the previous matching of that line).  This is a sound pruning rule (a necessary
condition for AllDifferent).  On an empty grid with row-major ordering it is also
*sufficient*: by Hall's marriage theorem every k x n Latin rectangle extends to a
Latin square, so a row that can be completed never causes a later dead end and the
search becomes backtrack-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from search.core import SearchProblem


@dataclass
class LatinState:
    n: int
    cells: list[int]          # flat, row-major, 0 = empty
    rows: list[int]           # bitmask of values used in row r (bits 1..n)
    cols: list[int]
    empty: int
    # warm-start hints for the matching check: line -> {position: value}
    row_hint: list[dict] = field(default_factory=list)
    col_hint: list[dict] = field(default_factory=list)
    dead: bool = False        # initial grid already infeasible

    def grid(self) -> list[list[int]]:
        n = self.n
        return [self.cells[r * n:(r + 1) * n] for r in range(n)]


class LatinSquare(SearchProblem[LatinState, tuple[int, int]]):
    def __init__(self, n: int, partial: list[list[int]] | None = None,
                 reduced: bool = True, ordering: str = "static", matching: bool = True):
        if n < 1:
            raise ValueError("n >= 1")
        if ordering not in ("static", "mrv"):
            raise ValueError(ordering)
        self.n = n
        self.full = (1 << (n + 1)) - 2          # bits 1..n
        self.partial = partial
        self.reduced = reduced and partial is None
        self.ordering = ordering
        self.matching = matching
        self._vals_memo: dict[int, list[int]] = {}
        self.matching_checks = 0

    def _vals(self, mask: int) -> list[int]:
        v = self._vals_memo.get(mask)
        if v is None:
            v = [d for d in range(1, self.n + 1) if mask >> d & 1]
            self._vals_memo[mask] = v
        return v

    # -- state --------------------------------------------------------------------
    def initial_state(self) -> LatinState:
        n = self.n
        st = LatinState(n, [0] * (n * n), [0] * n, [0] * n, n * n,
                        [{} for _ in range(n)], [{} for _ in range(n)])
        fixed: dict[tuple[int, int], int] = {}
        if self.partial is not None:
            for r, row in enumerate(self.partial):
                for c, v in enumerate(row):
                    if v:
                        fixed[(r, c)] = v
        elif self.reduced:
            for c in range(n):
                fixed[(0, c)] = c + 1
            for r in range(1, n):
                fixed[(r, 0)] = r + 1
        for (r, c), v in fixed.items():
            if not 1 <= v <= n or (st.rows[r] | st.cols[c]) >> v & 1:
                raise ValueError(f"inconsistent pre-filled value {v} at ({r},{c})")
            self._set(st, r * n + c, v)
        if self.matching:
            st.dead = not all(self._line_ok(st, k, True) and self._line_ok(st, k, False)
                              for k in range(n))
        return st

    def copy(self, s: LatinState) -> LatinState:
        return LatinState(s.n, s.cells[:], s.rows[:], s.cols[:], s.empty,
                          [h.copy() for h in s.row_hint], [h.copy() for h in s.col_hint], s.dead)

    def is_goal(self, s: LatinState) -> bool:
        return s.empty == 0

    def _set(self, s: LatinState, i: int, v: int) -> None:
        r, c = divmod(i, self.n)
        b = 1 << v
        s.cells[i] = v
        s.rows[r] |= b
        s.cols[c] |= b
        s.empty -= 1

    def _unset(self, s: LatinState, i: int) -> None:
        r, c = divmod(i, self.n)
        b = ~(1 << s.cells[i])
        s.rows[r] &= b
        s.cols[c] &= b
        s.cells[i] = 0
        s.empty += 1

    # -- bipartite matching check (necessary condition of AllDifferent) -------------
    def _line_ok(self, s: LatinState, k: int, is_row: bool) -> bool:
        """Can the empty cells of row/col k be matched to that line's missing values?"""
        self.matching_checks += 1
        n, cells, rows, cols, full = self.n, s.cells, s.rows, s.cols, self.full
        if is_row:
            pos = [c for c in range(n) if cells[k * n + c] == 0]
            cand = {c: full & ~(rows[k] | cols[c]) for c in pos}
            hint = s.row_hint[k]
        else:
            pos = [r for r in range(n) if cells[r * n + k] == 0]
            cand = {r: full & ~(rows[r] | cols[k]) for r in pos}
            hint = s.col_hint[k]
        owner: dict[int, int] = {}            # value -> position
        assign: dict[int, int] = {}           # position -> value
        for p in pos:                         # warm start from previous matching
            v = hint.get(p)
            if v and cand[p] >> v & 1 and v not in owner:
                owner[v] = p
                assign[p] = v
        vals = self._vals

        def augment(p: int, seen: set[int]) -> bool:
            for v in vals(cand[p]):
                if v not in seen:
                    seen.add(v)
                    q = owner.get(v)
                    if q is None or augment(q, seen):
                        owner[v] = p
                        assign[p] = v
                        return True
            return False

        for p in pos:
            if p not in assign and not augment(p, set()):
                return False
        if is_row:
            s.row_hint[k] = assign
        else:
            s.col_hint[k] = assign
        return True

    # -- search interface ------------------------------------------------------------
    def actions(self, s: LatinState):
        if s.empty == 0 or s.dead:
            return
        n = self.n
        if self.ordering == "mrv":
            best, best_m, best_k = -1, 0, n + 1
            for i, v in enumerate(s.cells):
                if v == 0:
                    m = self.full & ~(s.rows[i // n] | s.cols[i % n])
                    k = m.bit_count()
                    if k < best_k:
                        best, best_m, best_k = i, m, k
                        if k <= 1:
                            break
            i, mask = best, best_m
        else:
            i = s.cells.index(0)
            mask = self.full & ~(s.rows[i // n] | s.cols[i % n])
        for v in self._vals(mask):
            yield (i, v)

    def apply(self, s: LatinState, action: tuple[int, int]):
        i, v = action
        r, c = divmod(i, self.n)
        token = (i, s.row_hint[r], s.col_hint[c])
        self._set(s, i, v)
        if self.matching:
            ok = self._line_ok(s, r, True) and self._line_ok(s, c, False)
            return ok, token
        return True, token

    def undo(self, s: LatinState, token) -> None:
        i, rh, ch = token
        r, c = divmod(i, self.n)
        self._unset(s, i)
        s.row_hint[r], s.col_hint[c] = rh, ch


# ---------------------------------------------------------------------------
def cyclic(n: int) -> list[list[int]]:
    """O(n^2) constructive baseline - reproduces exactly the example in the task
    (row r is row 0 shifted right by r)."""
    return [[(c - r) % n + 1 for c in range(n)] for r in range(n)]


def is_latin(grid: list[list[int]], partial: list[list[int]] | None = None) -> bool:
    n = len(grid)
    want = list(range(1, n + 1))
    if any(sorted(row) != want for row in grid):
        return False
    if any(sorted(grid[r][c] for r in range(n)) != want for c in range(n)):
        return False
    if partial:
        return all(not p or p == g for prow, grow in zip(partial, grid) for p, g in zip(prow, grow))
    return True


def fmt(grid: list[list[int]]) -> str:
    w = len(str(len(grid)))
    return "\n".join(" ".join(f"{v:>{w}}" for v in row) for row in grid)
