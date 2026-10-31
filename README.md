# First semester assignment — Uninformed Search Techniques

Implemented in Python 3.10+ (standard library only; `matplotlib` and Graphviz `dot` are used
only for the figures). All numbers in this document are **measured** from the code
(`results/run_all.txt`, `results/landscape.json`). Program output and figure labels are in Albanian.

```
python main.py all                                   # all problems + results/benchmarks.json
python main.py golfers --weeks 9                     # 1. Social Golfers (GF(2)^5 model, DFS)
python main.py golfers --weeks 6 --model restarts    #    direct model + Luby restarts
python main.py golfers --weeks 5 --model direct      #    direct model, plain DFS
python main.py golfers --model published             #    published 10-week schedule (Aguado 2004), validated
python main.py sudoku --level hard --propagate       # 2. Sudoku (BFS)
python main.py sudoku --generate --seed 1            #    new easy/medium/hard puzzles with a unique solution
python main.py latin --n 5 --cyclic                  # 3. Latin Square (IDDFS, L = 0,1,2,...)
python main.py latin --n 30 --start-at-depth         #    large n: starts at L = D (one iteration)
python main.py trees                                 # 4. Search trees -> results/trees/*.svg|png
python landscape.py                                  # landscape: results/landscape.json + figures
python -m unittest discover -s tests -v              # 30 tests
```

## Structure

| File | Contents |
|---|---|
| `search/core.py` | Generic engine: `SearchProblem`, iterative DFS + backtracking, BFS, iterative IDDFS (cutoff vs failure), `SearchStats` (nodes, backtracks, pruned, b\*, profile per depth/iteration), `Budget` |
| `problems/golfers.py` | Social Golfers: direct model (bitmasks, 4 symmetry-breaking rules, forward checking, clique look-ahead, Luby restarts) + GF(2)^d model (partial spread) |
| `problems/sudoku.py` | Sudoku: bitmasks, static/MRV ordering, naked-single propagation with an undo trail, level generator |
| `problems/latin.py` | Latin square / quasigroup completion: perfect matching check (Hall), reduced form |
| `problems/trees.py` | 8-Puzzle, Missionaries & Cannibals, RWS + tree builder and Graphviz rendering |
| `landscape.py` | Analytic sizes, distribution of f(x), ruggedness, tree profiles |
| `tests/test_all.py` | Validators independent of the solvers |

## The shared idea: incremental formulation

* **State** = partial assignment of the variables; **action** = give the next variable a value.
* `actions()` returns **only consistent values** → this is what makes DFS/BFS/IDDFS "with backtracking":
  a branch is cut as soon as a constraint is violated, not at a leaf.
* DFS and IDDFS work **in place** (`apply`/`undo`, O(d) memory); BFS works with copies
  (`result`), because the whole frontier must exist at the same time.
* With a fixed variable order the space is a **tree** (each partial assignment is reached by
  exactly one path) → the CSPs need no explored set.
* The algorithms stay **uninformed**: MRV and propagation are CSP techniques for variable
  ordering / consistency, not heuristic functions of the distance to the goal.

---

## 1. Social Golfers — DFS + backtracking

**The question:** 32 players, groups of 4 — for how many weeks?
Each week a player meets 3 new players out of 31 → **w ≤ ⌊31/3⌋ = 10**. 10 weeks are achievable
(first explicit solution: A. Aguado, 2004); 9 weeks were found soon after 1998.

**The answer: 10 weeks.** Aguado's schedule is in `data/social_golfers_8x4x10.json` and is checked
by the independent validator (`--model published`). This schedule is published, **it was not found by DFS**:
DFS here reaches 9 weeks with model B and 7 with model A.

### Model A (direct)
| | |
|---|---|
| Variables | X_{w,g,k} = the player in week w, group g, position k (32·w) |
| Domain | {0,…,31} |
| C1 | each week is a partition of the 32 players (AllDifferent per week) |
| C2 | each pair of players is together ≤ 1 time |
| Objective | f(X) = Σ_{a<b} max(0, meetings(a,b) − 1) ; solution ⇔ f = 0 ; optimisation problem: max w s.t. f = 0 |

Bit-parallel implementation: candidates for the next slot = `~week_used & ~group_union & above(last)`.
Symmetry breaking: S1 week 1 fixed, S2 increasing within a group, S3 groups ordered by first player,
S4 weeks 2..w ordered by the 2nd player of group 0. Forward checking: FC1 the group can be completed,
FC3 every free player belongs to a 4-clique in the "have not met yet" graph.

| 8-4-w | DFS | DFS + Luby restarts |
|---|---|---|
| 2–5 | 32(w−1) nodes, 0 backtracks | — |
| 6 | does not finish (>15M nodes / 60 s) | 28 348 nodes, 0.06 s |
| 7 | — | 9.3M nodes, 21 s |
| 8–10 | — | does not finish in 100 s |

The reason: *thrashing* — a mistake in week 2 is discovered in week 6 and chronological backtracking
does not go back that far. Randomised restarts partly solve this and remain complete.

### Model B (structural reformulation)
Players = vectors in GF(2)⁵; a week = the 8 cosets of a 2-dimensional subspace U.
x, y are in the same group ⇔ x ⊕ y ∈ U∖{0}, so two weeks repeat no pair ⇔ U_i ∩ U_j = {0}.
The problem becomes a *partial spread*: choose w of 155 subspaces with disjoint non-zero parts.

| w | nodes | time |
|---|---:|---:|
| ≤ 7 | ≤ 8 | < 0.1 ms |
| 9 | **408** | **~1 ms** |
| 10 | 7 450 353 (full exhaustion) | 14.8 s → **impossible within the linear model** |

This agrees with theory (the maximal partial spread of lines in PG(4,2) = 9).

### Landscape
| | log₁₀ \|S\| |
|---|---:|
| naive 32^(32·10) | 481.6 |
| weekly partitions (32!/((4!)⁸8!) = 5.93·10¹⁹ per week)^10 | 197.7 |
| after S1 + S4 | 172.4 |
| model B: C(155,10) | **15.2** |

---

## 2. Sudoku — BFS + backtracking

| | |
|---|---|
| Variables | X_i, i = 0..80 |
| Domain | {1..9} (or the given value) |
| Constraints | AllDifferent on 27 units (9 rows, 9 columns, 9 boxes) |
| Action | (cell, digit) consistent with the row/column/box (O(1) bitmask) |
| Objective | f(x) = Σ_units Σ_{i<j} [x_i = x_j]; solution ⇔ f = 0 and the clues are respected |

Three levels: reference puzzles (uniqueness tested) + `generate(level)` (a full grid from randomised
DFS, removing cells only if the solution stays unique: easy 36–40, medium 28–32, hard 22–26 clues).

| Level | Configuration | BFS nodes | max frontier | time |
|---|---|---:|---:|---:|
| Easy (32) | static | 928 | 146 | 2 ms |
| | MRV | 49 | 1 | < 1 ms |
| | MRV + propagation | 0 (propagation solves it) | 0 | < 1 ms |
| Medium (28) | static | 22 918 | 3 616 | 70 ms |
| | MRV | 205 | 9 | 1 ms |
| | MRV + propagation | 21 | 3 | 1 ms |
| Hard (21) | static | 2 068 780 | **356 812** | 17.9 s |
| | MRV | 24 880 | 1 003 | 0.15 s |
| | MRV + propagation | 2 170 | 243 | 0.08 s |

Conclusion: all solutions are at depth d = #empty, so BFS has to build every layer —
O(b^d) in memory (356 thousand states at once on Hard, static).

Landscape (log₁₀ of the space size, by level):

| Level | Empty | naive 9^e | Π\|D_i\| after the clues | row permutations |
|---|---:|---:|---:|---:|
| Easy | 49 | 46.8 | 23.2 | 21.9 |
| Medium | 53 | 50.6 | 28.6 | 25.1 |
| Hard | 60 | 57.3 | 37.0 | 30.8 |

The explored tree stays far smaller: 10¹–10⁶ nodes (table above).

---

## 3. Latin Square — IDDFS + backtracking

| | |
|---|---|
| Variables | X_{r,c}, n² |
| Domain | {1..n} |
| Constraints | AllDifferent for every row and column |
| Goal | all cells filled → **every solution is at depth D = #empty** |
| Symmetry | reduced form (row 0 and column 0 = 1..n) → D = (n−1)² |
| Objective | f = Σ_r (n − \|unique(r)\|) + Σ_c (n − \|unique(c)\|) |

The program's default is textbook IDDFS (L = 0, 1, 2, ...). It is exponential here, because every
iteration L < D exhausts the tree. The table below is without the matching check
(`--no-matching`); with it, n = 5 takes 4 173 nodes and n = 6 takes 936 831 nodes, with the same number of iterations:

| n | iterations | total nodes | in the last iteration | overhead |
|---|---:|---:|---:|---:|
| 5 | 17 | 4 897 | 28 | 175× |
| 6 | 26 | 1 194 051 | 51 | 23 413× |
| ≥ 7 | — | > 10⁸ | — | — |

If the textbook run uses up `--seconds` (in practice n ≥ 7), the program says so and falls back to
`--start-at-depth` so it still prints a square. Results from that fallback come from the single L = D pass.

Optimisations:
1. `--start-at-depth` (`start_limit = D`): an **exact** lower bound (each action fills 1 cell) →
   completeness is preserved, but only one iteration remains, so in practice this is depth-limited DFS. Needed for
   n ≥ 7, where full IDDFS exceeds the time budget; the n = 10–100 table below uses this mode.
2. *Perfect matching* check (Kuhn, warm start) for the affected row and column. By
   **Hall's theorem**, every Latin rectangle extends to a square → with row-by-row ordering the search becomes
   **backtrack-free** (verified: `nodes = D + rejected values`, backtracks = 0).
3. Iterative DLS (n = 50 has D = 2401 > Python's recursion limit).

| n | static: nodes / time | MRV: nodes / time |
|---:|---|---|
| 10 | 121 / 1 ms | 82 / 3 ms |
| 20 | 681 / 14 ms (without matching: does not finish) | 371 / 35 ms |
| 50 | 6 649 / 0.45 s | 2 533 / 0.85 s |
| 100 | 43 785 / 5.4 s | 9 943 / 14.3 s |

Verified: the number of reduced squares for n = 1..6 = 1, 1, 1, 4, 56, 9408 (OEIS A000315);
an unsolvable grid → IDDFS stops with *failure*; quasigroup completion works.
`--cyclic` also prints the O(n²) construction, which matches the assignment's example exactly.

Landscape (log₁₀ of the space size):

| n | naive n^(n²) | row permutations (n!)^n | reduced cells n^((n−1)²) | Latin squares L(n) |
|---:|---:|---:|---:|---:|
| 5 | 17.5 | 10.4 | 11.2 | 5.2 |
| 8 | 57.8 | 36.8 | 44.3 | 20.0 |

---

## 4. Search Trees

The trees are generated by the code (`results/trees/*.svg|png`): every generated node with its status
(expanded #order / goal / repeated / illegal / frontier); the solution path is in green.

| Problem | State | Actions | Algorithm | Tree | Solution |
|---|---|---|---|---|---|
| 8-Puzzle | permutation of 0..8 (181 440 reachable; inversion parity) | blank up/down/left/right | BFS graph search | 78 nodes, 27 repeated | 5 moves (optimal) |
| Missionaries & Cannibals | (M_left, C_left, boat) | {1M, 2M, 1C, 2C, 1M1C} | BFS graph search | 47 nodes, 18 illegal, 14 repeated | 11 crossings (optimal) |
| Rotating Workforce Scheduling | cyclic string of length 7n over {D, N, –} | the shift of day t | DFS + backtracking | 78 nodes up to the first solution, 45 pruned | f = 0 |

RWS (n = 3): demand D = 1 every day, N = 1 Mon–Fri; work blocks 2–5, days off 1–3, D ≤ 4, N ≤ 3,
N→D forbidden; objective = coverage shortage/excess + block violations + forbidden sequences.

The RWS figure stops at the first solution. Continuing the same search to the end generates
49 374 nodes (32 611 pruned) and finds 306 solutions; that full tree is too large to draw.

```
        Mon Tue Wed Thu Fri Sat Sun
Week 1:  D   D   D   D   N   -   D
Week 2:  N   N   -   -   D   D   -
Week 3:  -   -   N   N   -   -   -
```

---

## Landscape — summary (`landscape.py`)

* `results/fig_landscape_objective.png`: f(x) on random configurations (4000 per Sudoku and Latin
  instance, 1000 for Golfers), naive vs structured representation. No sample has f = 0 → pruning is needed.
* Ruggedness: a random walk with swaps gives the autocorrelation ρ(1) and the correlation length ℓ.

| Instance | mean f, naive → structured | ρ(1) | ℓ |
|---|---:|---:|---:|
| Sudoku Easy | 91.1 → 49.8 | 0.901 | 9.6 |
| Sudoku Medium | 94.9 → 53.3 | 0.926 | 13.0 |
| Sudoku Hard | 102.3 → 61.2 | 0.947 | 18.2 |
| Latin n = 5 | 16.4 → 8.2 | 0.773 | 3.9 |
| Latin n = 8 | 44.0 → 22.0 | 0.931 | 13.9 |
| Golfers 8-4-10 | 292.9 → 163.4 | 0.975 | 38.8 |

* `results/fig_landscape_search_profile.png`: BFS layers on Sudoku Hard and nodes per iteration
  of IDDFS on Latin n = 6.

## References
* S. Russell, P. Norvig — *Artificial Intelligence: A Modern Approach*, ch. 3 & 6.
* CSPLib prob010 — Social Golfers Problem; A. Aguado (2004) 8-4-10 solution.
* C. Gomes, B. Selman, H. Kautz (1998) — heavy-tailed behaviour & randomized restarts; M. Luby et al. (1993).
* P. Hall (1935) — On representatives of subsets (marriage theorem).
* E. Weinberger (1990) — Correlated and uncorrelated fitness landscapes.
* N. Musliu, J. Gärtner, W. Slany (2002) — Efficient generation of rotating workforce schedules.
