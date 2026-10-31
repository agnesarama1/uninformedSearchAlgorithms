"""Run:  python -m unittest discover -s tests -v"""

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main as cli
from problems import golfers as G
from problems import latin as L
from problems import sudoku as SD
from problems import trees as T
from search.core import (Budget, SearchProblem, breadth_first_search, depth_first_backtracking,
                         iterative_deepening_dfs)


def run_cli(*argv: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        cli.main(list(argv))
    return out.getvalue()


class AllChildrenRejected(SearchProblem):
    """One root with two children, both rejected by apply(): exactly one dead end."""

    def initial_state(self):
        return []

    def actions(self, state):
        return [1, 2]

    def is_goal(self, state):
        return False

    def apply(self, state, action):
        return False, None

    def undo(self, state, token):
        pass

    def copy(self, state):
        return list(state)


class TestEngine(unittest.TestCase):
    def test_rejected_children_count_as_backtrack(self):
        _, st = depth_first_backtracking(AllChildrenRejected())
        self.assertEqual((st.backtracks, st.pruned), (1, 2))
        _, st = iterative_deepening_dfs(AllChildrenRejected())
        self.assertEqual((st.backtracks, st.pruned), (1, 2))

    def test_iddfs_budget_applies_at_depth_limit(self):
        _, st = iterative_deepening_dfs(L.LatinSquare(5), Budget(max_nodes=1), start_limit=1, max_limit=1)
        self.assertTrue(st.aborted)
        self.assertEqual(st.generated, 1)


class TestSudoku(unittest.TestCase):
    def test_reference_puzzles_unique(self):
        for lvl, p in SD.PUZZLES.items():
            self.assertEqual(SD.count_solutions(p), 1, lvl)

    def test_bfs_all_configs(self):
        for lvl, p in SD.PUZZLES.items():
            for o, prop in [("mrv", False), ("mrv", True)]:
                pr = SD.Sudoku(p, o, prop)
                sol, st = breadth_first_search(pr)
                self.assertTrue(st.solved, (lvl, o, prop))
                self.assertTrue(SD.is_valid_solution(sol.cells, pr.givens))

    def test_bfs_static_easy_medium(self):
        for lvl in ("easy", "medium"):
            pr = SD.Sudoku(SD.PUZZLES[lvl], "static")
            sol, _ = breadth_first_search(pr)
            self.assertTrue(SD.is_valid_solution(sol.cells, pr.givens))

    def test_dfs_and_bfs_agree(self):
        pr = SD.Sudoku(SD.PUZZLES["hard"], "mrv", True)
        b, _ = breadth_first_search(pr)
        d, _ = depth_first_backtracking(pr)
        self.assertEqual(b.cells, d[0].cells)        # unique solution

    def test_generator_levels(self):
        for lvl in ("easy", "medium", "hard"):
            p = SD.generate(lvl, seed=7)
            lo, hi = SD.LEVEL_CLUES[lvl]
            self.assertGreaterEqual(sum(c != "0" for c in p), lo)
            self.assertEqual(SD.count_solutions(p), 1)

    def test_invalid_clue_rejected(self):
        with self.assertRaises(ValueError):
            SD.Sudoku("11" + "0" * 79).initial_state()


class TestLatin(unittest.TestCase):
    def test_reduced_counts_oeis_A000315(self):
        for n, expected in [(1, 1), (2, 1), (3, 1), (4, 4), (5, 56)]:
            sols, _ = depth_first_backtracking(L.LatinSquare(n), find_all=True)
            self.assertEqual(len(sols), expected, n)
            self.assertTrue(all(L.is_latin(s.grid()) for s in sols))

    def test_matching_does_not_lose_solutions(self):
        a, _ = depth_first_backtracking(L.LatinSquare(5, matching=True), find_all=True)
        b, _ = depth_first_backtracking(L.LatinSquare(5, matching=False), find_all=True)
        self.assertEqual(sorted(map(lambda s: s.cells, a)), sorted(map(lambda s: s.cells, b)))

    def test_iddfs_textbook_and_bounded(self):
        for n in (3, 4, 5):
            for start in (0, None):
                pr = L.LatinSquare(n)
                D = pr.initial_state().empty
                sol, st = iterative_deepening_dfs(pr, start_limit=D if start is None else 0)
                self.assertTrue(L.is_latin(sol.grid()))

    def test_iddfs_large(self):
        sol, _ = iterative_deepening_dfs(L.LatinSquare(30), start_limit=29 * 29)
        self.assertTrue(L.is_latin(sol.grid()))

    def test_unsat_terminates_with_failure(self):
        sol, st = iterative_deepening_dfs(L.LatinSquare(2, partial=[[1, 0], [0, 2]]))
        self.assertIsNone(sol)
        self.assertFalse(st.aborted)

    def test_completion(self):
        P = [[1, 0, 0, 0, 0], [0, 0, 3, 0, 0], [0, 0, 0, 0, 2], [0, 5, 0, 0, 0], [0, 0, 0, 4, 0]]
        sol, _ = iterative_deepening_dfs(L.LatinSquare(5, partial=P))
        self.assertTrue(L.is_latin(sol.grid(), P))

    def test_cli_default_is_real_iddfs(self):
        out = run_cli("latin", "--n", "4")
        self.assertIn("iterations=10", out)
        self.assertIn("valid=True", out)

    def test_cli_start_at_depth_is_one_pass(self):
        out = run_cli("latin", "--n", "4", "--start-at-depth")
        self.assertIn("iterations=1 ", out)
        self.assertIn("valid=True", out)

    def test_cli_falls_back_when_iddfs_runs_out_of_budget(self):
        out = run_cli("latin", "--n", "8", "--seconds", "0.2")
        self.assertIn("--start-at-depth", out)
        self.assertIn("valid=True", out)

    def test_cyclic_matches_task_example(self):
        self.assertEqual(L.cyclic(5), [[1, 2, 3, 4, 5], [5, 1, 2, 3, 4], [4, 5, 1, 2, 3],
                                       [3, 4, 5, 1, 2], [2, 3, 4, 5, 1]])


class TestGolfers(unittest.TestCase):
    def test_known_instances(self):
        for g, p, w, sat in [(3, 3, 4, True), (3, 3, 5, False), (4, 4, 5, True), (4, 3, 5, False)]:
            pr = G.SocialGolfers(g, p, w)
            sols, st = depth_first_backtracking(pr)
            self.assertEqual(bool(sols), sat, (g, p, w))
            if sols:
                self.assertTrue(G.is_valid_schedule(G.to_weeks(pr, sols[0]), g * p, p))

    def test_direct_8_4_5(self):
        pr = G.SocialGolfers(8, 4, 5)
        sols, _ = depth_first_backtracking(pr)
        self.assertTrue(G.is_valid_schedule(G.to_weeks(pr, sols[0]), 32, 4))

    def test_restarts_8_4_6(self):
        r, st, _ = G.solve_with_restarts(8, 4, 6, max_seconds=30)
        self.assertTrue(G.is_valid_schedule(G.to_weeks(*r), 32, 4))

    def test_spread_9_weeks(self):
        weeks, st, _ = G.solve_spread(5, 2, 9)
        self.assertTrue(G.is_valid_schedule(weeks, 32, 4))
        self.assertEqual(G.objective(weeks), 0)
        self.assertEqual(len(G.SpreadGolfers(5, 2, 1).subspaces), 155)

    def test_published_10_weeks(self):
        weeks = G.load_published_schedule()
        self.assertEqual(len(weeks), G.upper_bound_weeks(8, 4))
        self.assertTrue(G.is_valid_schedule(weeks, 32, 4))
        self.assertEqual(G.objective(weeks), 0)
        self.assertIn("Java 10", run_cli("golfers", "--model", "published"))

    def test_upper_bound(self):
        self.assertEqual(G.upper_bound_weeks(8, 4), 10)

    def test_objective_detects_repeat(self):
        w = [[[0, 1], [2, 3]], [[0, 1], [2, 3]]]
        self.assertEqual(G.objective(w), 2)
        self.assertFalse(G.is_valid_schedule(w, 4, 2))


class TestTrees(unittest.TestCase):
    def test_8puzzle_optimal_depth(self):
        t = T.bfs_tree((2, 0, 3, 1, 4, 6, 7, 5, 8), T.puzzle_successors, lambda s: s == T.PUZZLE_GOAL)
        self.assertEqual(len(t.solution) - 1, 5)

    def test_8puzzle_parity(self):
        self.assertTrue(T.puzzle_solvable(T.PUZZLE_GOAL))
        self.assertFalse(T.puzzle_solvable((2, 1, 3, 4, 5, 6, 7, 8, 0)))

    def test_mc_11_crossings(self):
        t = T.bfs_tree(T.MC_START, T.mc_successors, lambda s: s == T.MC_GOAL, T.mc_legal)
        self.assertEqual(len(t.solution) - 1, 11)
        self.assertTrue(all(T.mc_legal(t.nodes[i].state) for i in t.solution))

    def test_rws_solution_feasible(self):
        inst = T.RWSInstance()
        sols, _ = depth_first_backtracking(T.RWSProblem(inst))
        self.assertEqual(T.rws_violations(inst, sols[0]["seq"]), 0)

    def test_rws_full_tree_goes_past_first_solution(self):
        inst = T.RWSInstance()
        sols, st = depth_first_backtracking(T.RWSProblem(inst), find_all=True)
        self.assertGreater(len(sols), 1)
        self.assertGreater(st.generated, len(T.dfs_trace_tree(T.RWSProblem(inst), max_nodes=300).nodes))
        self.assertTrue(all(T.rws_violations(inst, s["seq"]) == 0 for s in sols))


if __name__ == "__main__":
    unittest.main()
