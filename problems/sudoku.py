"""Problem 2 - Sudoku solved with Breadth-First Search + backtracking.

Representation (CSP):
    variables  X_i, i = 0..80           (cell r*9+c)
    domain     D_i = {1..9}  (or the given clue)
    constraints AllDifferent on each of the 27 units (9 rows, 9 cols, 9 boxes)

Implementation details that make this fast in pure Python:
    * rows/cols/boxes are 9-bit masks  -> candidate set of a cell is one OR + NOT
    * `int.bit_count()` gives |domain| in O(1)  -> MRV is a cheap scan
    * optional naked-single propagation (forward chaining) with an undo trail
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from search.core import SearchProblem

ALL = 0x3FE                      # bits 1..9 set
ROW = [i // 9 for i in range(81)]
COL = [i % 9 for i in range(81)]
BOX = [(i // 27) * 3 + (i % 9) // 3 for i in range(81)]
DIGITS_OF = [[d for d in range(1, 10) if m >> d & 1] for m in range(1 << 10)]

# Three reference levels.  Uniqueness of each is asserted in tests/test_all.py.
PUZZLES = {
    # 32 clues - solvable by naked singles alone (classic "easy")
    "easy":   "003020600900305001001806400008102900700000008006708200002609500800203009005010300",
    # 28 clues - needs guessing (not solvable by naked singles alone)
    "medium": "000000907000420180000705026100904000050000040000507009920108000034059000507000000",
    # 21 clues - Arto Inkala's puzzle, widely publicised as one of the hardest
    "hard":   "800000000003600000070090200050007000000045700000100030001000068008500010090000400",
}


@dataclass
class SudokuState:
    cells: list[int]
    rows: list[int]
    cols: list[int]
    boxes: list[int]
    empty: int
    trail: list[int] = field(default_factory=list)   # scratch, not part of identity

    def grid(self) -> list[list[int]]:
        return [self.cells[r * 9:(r + 1) * 9] for r in range(9)]


def parse(puzzle: str) -> list[int]:
    s = [c for c in puzzle if c in "0123456789."]
    if len(s) != 81:
        raise ValueError("puzzle must have 81 cells")
    return [0 if c == "." else int(c) for c in s]


def fmt(cells: list[int]) -> str:
    out = []
    for r in range(9):
        if r and r % 3 == 0:
            out.append("------+-------+------")
        row = cells[r * 9:(r + 1) * 9]
        out.append(" | ".join(" ".join(str(v or ".") for v in row[k:k + 3]) for k in (0, 3, 6)))
    return "\n".join(out)


class Sudoku(SearchProblem[SudokuState, tuple[int, int]]):
    """ordering: 'static' (row-major first empty) or 'mrv' (fewest candidates).
    propagate: after each assignment, fill every naked single until fix-point."""

    def __init__(self, puzzle: str | list[int], ordering: str = "mrv", propagate: bool = False):
        self.givens = parse(puzzle) if isinstance(puzzle, str) else list(puzzle)
        if ordering not in ("static", "mrv"):
            raise ValueError(ordering)
        self.ordering = ordering
        self.propagate = propagate

    # -- state -----------------------------------------------------------------
    def initial_state(self) -> SudokuState:
        st = SudokuState([0] * 81, [0] * 9, [0] * 9, [0] * 9, 81)
        for i, v in enumerate(self.givens):
            if v:
                bit = 1 << v
                if (st.rows[ROW[i]] | st.cols[COL[i]] | st.boxes[BOX[i]]) & bit:
                    raise ValueError(f"inconsistent clue at cell {i}")
                self._set(st, i, v)
        if self.propagate:
            ok, _ = self._propagate(st, [])
            if not ok:
                raise ValueError("puzzle has no solution (propagation wipe-out)")
        return st

    def copy(self, s: SudokuState) -> SudokuState:
        return SudokuState(s.cells[:], s.rows[:], s.cols[:], s.boxes[:], s.empty)

    def is_goal(self, s: SudokuState) -> bool:
        return s.empty == 0

    # -- primitive set/unset -----------------------------------------------------
    @staticmethod
    def _set(s: SudokuState, i: int, v: int) -> None:
        bit = 1 << v
        s.cells[i] = v
        s.rows[ROW[i]] |= bit
        s.cols[COL[i]] |= bit
        s.boxes[BOX[i]] |= bit
        s.empty -= 1

    @staticmethod
    def _unset(s: SudokuState, i: int) -> None:
        bit = ~(1 << s.cells[i])
        s.rows[ROW[i]] &= bit
        s.cols[COL[i]] &= bit
        s.boxes[BOX[i]] &= bit
        s.cells[i] = 0
        s.empty += 1

    @staticmethod
    def candidates(s: SudokuState, i: int) -> int:
        return ALL & ~(s.rows[ROW[i]] | s.cols[COL[i]] | s.boxes[BOX[i]])

    # -- search interface --------------------------------------------------------
    def select_variable(self, s: SudokuState) -> tuple[int, int]:
        """Return (cell, candidate_mask); mask==0 means dead end."""
        cells = s.cells
        if self.ordering == "static":
            i = cells.index(0)
            return i, self.candidates(s, i)
        best_i, best_m, best_n = -1, 0, 10
        for i in range(81):
            if cells[i] == 0:
                m = self.candidates(s, i)
                n = m.bit_count()
                if n < best_n:
                    best_i, best_m, best_n = i, m, n
                    if n <= 1:
                        break
        return best_i, best_m

    def actions(self, s: SudokuState):
        if s.empty == 0:
            return
        i, mask = self.select_variable(s)
        for d in DIGITS_OF[mask]:
            yield (i, d)

    def apply(self, s: SudokuState, action: tuple[int, int]):
        i, d = action
        trail = [i]
        self._set(s, i, d)
        if self.propagate:
            ok, trail = self._propagate(s, trail)
            return ok, trail
        return True, trail

    def undo(self, s: SudokuState, trail: list[int]) -> None:
        for i in reversed(trail):
            self._unset(s, i)

    def _propagate(self, s: SudokuState, trail: list[int]) -> tuple[bool, list[int]]:
        """Naked singles to fix-point. Returns (consistent, trail)."""
        changed = True
        cells = s.cells
        while changed:
            changed = False
            for i in range(81):
                if cells[i] == 0:
                    m = self.candidates(s, i)
                    if m == 0:
                        return False, trail
                    if m & (m - 1) == 0:              # exactly one bit
                        self._set(s, i, m.bit_length() - 1)
                        trail.append(i)
                        changed = True
        return True, trail


# ---------------------------------------------------------------------------
# validation, counting, generation
# ---------------------------------------------------------------------------
def is_valid_solution(cells: list[int], givens: list[int] | None = None) -> bool:
    """Independent checker (does not reuse the solver's masks)."""
    if len(cells) != 81 or any(not 1 <= v <= 9 for v in cells):
        return False
    units = [[r * 9 + c for c in range(9)] for r in range(9)]
    units += [[r * 9 + c for r in range(9)] for c in range(9)]
    units += [[(br * 3 + r) * 9 + bc * 3 + c for r in range(3) for c in range(3)]
              for br in range(3) for bc in range(3)]
    if any(sorted(cells[i] for i in u) != list(range(1, 10)) for u in units):
        return False
    return givens is None or all(g == 0 or g == v for g, v in zip(givens, cells))


def count_solutions(puzzle, cap: int = 2) -> int:
    from search.core import depth_first_backtracking
    sols, _ = depth_first_backtracking(Sudoku(puzzle, "mrv", True), find_all=True, limit_solutions=cap)
    return len(sols)


LEVEL_CLUES = {"easy": (36, 40), "medium": (28, 32), "hard": (22, 26)}


def generate(level: str, seed: int | None = None) -> str:
    """Random full grid (randomised DFS) -> dig holes while the solution stays unique.

    Difficulty is controlled by the number of clues (and later *measured* by the
    size of the uninformed search tree, see benchmarks)."""
    rng = random.Random(seed)
    lo, hi = LEVEL_CLUES[level]
    target = rng.randint(lo, hi)

    # 1) random complete grid: DFS with shuffled value order
    p = Sudoku([0] * 81, "mrv", False)
    st = p.initial_state()

    def fill() -> bool:
        if st.empty == 0:
            return True
        i, m = p.select_variable(st)
        ds = DIGITS_OF[m][:]
        rng.shuffle(ds)
        for d in ds:
            p._set(st, i, d)
            if fill():
                return True
            p._unset(st, i)
        return False

    fill()
    grid = st.cells[:]

    # 2) remove cells in random order, keep only removals that preserve uniqueness
    order = list(range(81))
    rng.shuffle(order)
    clues = 81
    for i in order:
        if clues <= target:
            break
        saved, grid[i] = grid[i], 0
        if count_solutions(grid) != 1:
            grid[i] = saved
        else:
            clues -= 1
    return "".join(map(str, grid))
