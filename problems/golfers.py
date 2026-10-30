"""Problem 1 - Social Golfers (CSPLib prob010) solved with DFS + backtracking.

Instance g-p-w: n = g*p golfers play in g groups of p for w weeks; no two golfers may
share a group more than once.  The task instance is 8-4-w (32 golfers).

Representation (CSP):
    variables   X_{w,g,k}  = golfer in week w, group g, position k      (w*g*p vars)
    domain      {0 .. n-1}
    constraints (C1) each week is a partition:  AllDifferent_k,g X_{w,g,k}  for every w
                (C2) socialisation: for every pair of golfers a<b,
                     |{(w,g) : a,b in group (w,g)}| <= 1

Bit-parallel implementation: every set of golfers is a 32-bit int.
    week_used[w]     golfers already placed in week w
    met[a]           golfers that a has already shared a group with
    The candidate set for the next slot of group G is then ONE expression:
        ~week_used[w] & ~(met[m1] | met[m2] | ...) & above(last)        (all O(1))

Symmetry breaking (each rule is a lex-leader constraint for an independent symmetry):
    S1 golfer symmetry  -> week 0 is fixed to 0..p-1 | p..2p-1 | ...
    S2 position symmetry -> golfers inside a group are increasing
    S3 group symmetry    -> groups of a week ordered by their first golfer, which
                            forces "first golfer of a group = smallest unused golfer"
    S4 week symmetry     -> weeks 1..w-1 ordered by the 2nd golfer of group 0
                            (week 0 is excluded because S1 already fixed it)
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

from search.core import Budget, SearchStats, SearchProblem, depth_first_backtracking


@dataclass
class GolfState:
    sched: list[int]          # flat slots, -1 = empty
    k: int                    # next slot to fill (static variable ordering)
    week_used: list[int]
    group_union: list[int]    # OR of met[] over members of each (week,group) - cache
    group_mask: list[int]     # members of each (week,group)
    met: list[int]


class SocialGolfers(SearchProblem[GolfState, int]):
    def __init__(self, groups: int = 8, size: int = 4, weeks: int = 9,
                 symmetry: bool = True, forward_check: bool = True,
                 lookahead: str = "clique", seed: int | None = None,
                 prefix: list[list[list[int]]] | None = None):
        self.G, self.P, self.W = groups, size, weeks
        self.N = groups * size
        self.ALL = (1 << self.N) - 1
        self.slots = weeks * groups * size
        self.symmetry = symmetry
        self.forward_check = forward_check
        self.lookahead = lookahead                 # "degree" | "clique"
        self.rng = random.Random(seed) if seed is not None else None
        # hybrid mode: fixed first weeks (e.g. from the GF(2)^d model), DFS completes the rest
        self.prefix = prefix or []

    # ----------------------------------------------------------------------------
    def _decode(self, k: int) -> tuple[int, int, int]:
        w, r = divmod(k, self.G * self.P)
        g, p = divmod(r, self.P)
        return w, g, p

    def initial_state(self) -> GolfState:
        W, G, P, N = self.W, self.G, self.P, self.N
        st = GolfState([-1] * self.slots, 0, [0] * W, [0] * (W * G), [0] * (W * G), [0] * N)
        if self.prefix:
            for week in self.prefix:
                for grp in week:
                    for q in sorted(grp):
                        ok, _ = self.apply(st, q)
                        if not ok:
                            raise ValueError("prefix is infeasible")
        elif self.symmetry and W > 0:                    # S1: fix week 0
            for q in range(N):
                ok, _ = self.apply(st, q)
                assert ok
        return st

    def copy(self, s: GolfState) -> GolfState:
        return GolfState(s.sched[:], s.k, s.week_used[:], s.group_union[:], s.group_mask[:], s.met[:])

    def is_goal(self, s: GolfState) -> bool:
        return s.k == self.slots

    # ----------------------------------------------------------------------------
    def candidate_mask(self, s: GolfState) -> int:
        w, g, p = self._decode(s.k)
        free = self.ALL & ~s.week_used[w]
        if p == 0:
            if not self.symmetry:
                return free
            return free & -free                         # S3: lowest unused golfer only
        gi = w * self.G + g
        last = s.sched[s.k - 1]
        cand = free & ~s.group_union[gi]
        if self.symmetry:
            cand &= ~((1 << (last + 1)) - 1)            # S2: increasing inside group
            if g == 0 and p == 1 and w >= max(2, len(self.prefix) + 1):   # S4: free weeks ordered
                prev = s.sched[(w - 1) * self.G * self.P + 1]
                cand &= ~((1 << (prev + 1)) - 1)
        return cand

    def actions(self, s: GolfState):
        if s.k >= self.slots:
            return
        m = self.candidate_mask(s)
        vals = []
        while m:
            low = m & -m
            vals.append(low.bit_length() - 1)
            m ^= low
        if self.rng is not None and len(vals) > 1:
            self.rng.shuffle(vals)                 # randomised value order (for restarts)
        yield from vals

    def apply(self, s: GolfState, q: int):
        w, g, p = self._decode(s.k)
        gi = w * self.G + g
        gm = s.group_mask[gi]
        bq = 1 << q
        token = (s.k, gi, gm, s.group_union[gi], q)
        # socialise q with current members
        s.met[q] |= gm
        m = gm
        while m:
            low = m & -m
            s.met[low.bit_length() - 1] |= bq
            m ^= low
        s.group_mask[gi] = gm | bq
        s.group_union[gi] |= s.met[q] | bq   # q's (now updated) contacts + q itself
        s.week_used[w] |= bq
        s.sched[s.k] = q
        s.k += 1
        if self.forward_check and not self._feasible(s, w, g, p, q):
            return False, token
        return True, token

    def undo(self, s: GolfState, token) -> None:
        k, gi, gm, gu, q = token
        w = k // (self.G * self.P)
        bq = 1 << q
        s.k = k
        s.sched[k] = -1
        s.week_used[w] &= ~bq
        s.group_mask[gi] = gm
        s.group_union[gi] = gu
        # pairs are met at most once, so clearing the bits restores the old state
        s.met[q] &= ~gm
        m = gm
        while m:
            low = m & -m
            s.met[low.bit_length() - 1] &= ~bq
            m ^= low

    def _feasible(self, s: GolfState, w: int, g: int, p: int, q: int) -> bool:
        """Forward checking after placing q at (w,g,p).
        FC1: the current group can still be completed by golfers above q.
        FC2: when a group has just been closed, every golfer still free this week
             will land in a *fresh* group, so it needs >= P-1 free golfers it has not
             met yet.  (Not applied while a group is open: a free golfer may join the
             open group, whose members are no longer free, so the test would be unsound.)"""
        P = self.P
        free = self.ALL & ~s.week_used[w]
        need = P - 1 - p
        if need > 0:                                       # FC1
            gi = w * self.G + g
            cand = free & ~s.group_union[gi]
            if self.symmetry:
                cand &= ~((1 << (q + 1)) - 1)
            return cand.bit_count() >= need
        if self.lookahead == "clique":
            if not self._clique_cover(s, free):
                return False
            # week just finished -> next week starts with everybody free
            if free == 0 and w + 1 < self.W:
                return self._clique_cover(s, self.ALL)
            return True
        m = free                                           # FC2 (degree version)
        met = s.met
        while m:
            low = m & -m
            a = low.bit_length() - 1
            if (free & ~met[a] & ~low).bit_count() < P - 1:
                return False
            m ^= low
        return True

    def _clique_cover(self, s: GolfState, free: int) -> bool:
        """FC3: in the 'not-yet-met' graph restricted to `free`, every golfer must lie
        in a clique of size P (a possible future group).  Strictly stronger than the
        degree test; bit-parallel, and every clique found certifies all its members."""
        met, ALL, need = s.met, self.ALL, self.P - 1
        uncovered = free

        def grow(cand: int, k: int, members: int) -> int:
            if k == 0:
                return members
            m = cand
            while m:
                low = m & -m
                b = low.bit_length() - 1
                r = grow(cand & ~met[b] & ~((low << 1) - 1), k - 1, members | low)
                if r:
                    return r
                m ^= low
            return 0

        while uncovered:
            low = uncovered & -uncovered
            a = low.bit_length() - 1
            clique = grow(free & ALL & ~met[a] & ~low, need, low)
            if not clique:
                return False
            uncovered &= ~clique
        return True


# ---------------------------------------------------------------------------
def luby(i: int) -> int:
    """Luby et al. (1993) universal restart sequence 1,1,2,1,1,2,4,1,1,2,..."""
    k = 1
    while (1 << k) - 1 < i:
        k += 1
    while True:
        if i == (1 << k) - 1:
            return 1 << (k - 1)
        if (1 << (k - 1)) <= i < (1 << k) - 1:
            i = i - (1 << (k - 1)) + 1
            k = 1
            while (1 << k) - 1 < i:
                k += 1
        else:
            k -= 1


def solve_with_restarts(groups: int, size: int, weeks: int, unit: int = 20_000,
                        max_seconds: float = 120.0, seed: int = 0, **kw):
    """Randomised DFS + backtracking with Luby restarts (Gomes, Selman & Kautz 1998).

    Each run is an ordinary complete DFS, cut off after luby(i)*unit nodes.  Restarts
    fight the heavy-tailed runtime of chronological backtracking: a bad decision in
    week 2 is never revisited by plain DFS within any reasonable time, whereas a
    restart discards it.  Returns (solution|None, aggregated stats, runs)."""
    import time
    deadline = time.perf_counter() + max_seconds
    total = SearchStats(algorithm="DFS+backtracking+restarts")
    t0 = time.perf_counter()
    run = 0
    while time.perf_counter() < deadline:
        run += 1
        pr = SocialGolfers(groups, size, weeks, seed=seed * 100_003 + run, **kw)
        left = deadline - time.perf_counter()
        sols, st = depth_first_backtracking(pr, Budget(max_nodes=luby(run) * unit, max_seconds=left))
        total.generated += st.generated
        total.expanded += st.expanded
        total.backtracks += st.backtracks
        total.pruned += st.pruned
        total.max_depth = max(total.max_depth, st.max_depth)
        if sols:
            total.solved = True
            total.iterations = run
            total.elapsed = time.perf_counter() - t0
            return (pr, sols[0]), total, run
        if not st.aborted:              # complete run without solution -> proven UNSAT
            total.iterations = run
            total.elapsed = time.perf_counter() - t0
            return None, total, run
    total.aborted = True
    total.iterations = run
    total.elapsed = time.perf_counter() - t0
    return None, total, run


def to_weeks(problem: SocialGolfers, s: GolfState) -> list[list[list[int]]]:
    G, P = problem.G, problem.P
    return [[s.sched[(w * G + g) * P:(w * G + g + 1) * P] for g in range(G)] for w in range(problem.W)]


def is_valid_schedule(weeks: list[list[list[int]]], n: int, p: int) -> bool:
    """Independent checker: every week a partition, every pair together at most once."""
    seen_pairs: set[tuple[int, int]] = set()
    for week in weeks:
        if sorted(x for grp in week for x in grp) != list(range(n)):
            return False
        for grp in week:
            if len(grp) != p:
                return False
            for i in range(p):
                for j in range(i + 1, p):
                    pair = (min(grp[i], grp[j]), max(grp[i], grp[j]))
                    if pair in seen_pairs:
                        return False
                    seen_pairs.add(pair)
    return True


def objective(weeks: list[list[list[int]]]) -> int:
    """f = sum over pairs of max(0, times_together - 1).  Feasible <=> f == 0."""
    from collections import Counter
    c: Counter = Counter()
    for week in weeks:
        for grp in week:
            for i in range(len(grp)):
                for j in range(i + 1, len(grp)):
                    c[(min(grp[i], grp[j]), max(grp[i], grp[j]))] += 1
    return sum(v - 1 for v in c.values() if v > 1)


def upper_bound_weeks(g: int, p: int) -> int:
    """Each week a golfer meets p-1 new golfers out of n-1 -> w <= floor((n-1)/(p-1))."""
    n = g * p
    return (n - 1) // (p - 1) if p > 1 else 10 ** 9


def load_published_schedule() -> list[list[list[int]]]:
    """Aguado's (2004) 8-4-10 schedule, read from data/.  It is a published construction,
    not a result of DFS; it is checked here by the independent validator."""
    path = Path(__file__).resolve().parent.parent / "data" / "social_golfers_8x4x10.json"
    weeks = json.loads(path.read_text(encoding="utf-8"))["weeks"]
    if len(weeks) != 10 or not is_valid_schedule(weeks, 32, 4):
        raise ValueError("published 8-4-10 schedule failed validation")
    return weeks


def fmt(weeks: list[list[list[int]]]) -> str:
    lines = []
    for w, week in enumerate(weeks):
        lines.append(f"Java {w + 1:>2}: " + " | ".join(",".join(f"{x:>2}" for x in grp) for grp in week))
    return "\n".join(lines)


# ===========================================================================
# Model B - structural reformulation over GF(2)^d   (n = 2^d golfers, p = 2^k)
# ===========================================================================
class SpreadGolfers(SearchProblem[list, int]):
    """Golfers are the vectors of GF(2)^d (n = 2^d); a *week* is the set of cosets
    x + U of a k-dimensional linear subspace U (2^(d-k) groups of size p = 2^k).

    Golfers x != y share a group in week U  <=>  x XOR y in U \\ {0}.
    Hence weeks U_i, U_j never repeat a pair  <=>  U_i ∩ U_j = {0}.

    So a w-week schedule is the same thing as w subspaces whose non-zero parts are
    pairwise disjoint (a *partial spread*).  This shrinks a variable from
    "which of 32 golfers" (32*w*... variables) to "which of 155 subspaces" (w variables)
    while every constraint becomes one bitwise AND over 31-bit masks.

    State  : [mask_used, last_index, depth]           (mutable list)
    Action : index i of a subspace, i > last (weeks unordered -> combinations)
    """

    def __init__(self, d: int = 5, k: int = 2, weeks: int = 9):
        self.d, self.k, self.W = d, k, weeks
        self.subspaces = self._enumerate(d, k)          # list of (frozenset vectors, mask)
        self.masks = [m for _, m in self.subspaces]

    @staticmethod
    def _enumerate(d: int, k: int) -> list[tuple[tuple[int, ...], int]]:
        seen, out = set(), []
        n = 1 << d

        def span(gens: tuple[int, ...]) -> tuple[int, ...]:
            vs = {0}
            for g in gens:
                vs |= {v ^ g for v in vs}
            return tuple(sorted(vs))

        def rec(start: int, gens: tuple[int, ...]):
            if len(gens) == k:
                sp = span(gens)
                if len(sp) == 1 << k and sp not in seen:
                    seen.add(sp)
                    mask = 0
                    for v in sp[1:]:
                        mask |= 1 << v
                    out.append((sp, mask))
                return
            for v in range(start, n):
                rec(v + 1, gens + (v,))

        rec(1, ())
        return out

    def initial_state(self):
        return [0, -1, 0]

    def copy(self, s):
        return s[:]

    def is_goal(self, s) -> bool:
        return s[2] == self.W

    def actions(self, s):
        used, last, depth = s
        masks = self.masks
        need = self.W - depth
        # symmetry: GL(d,2) is transitive on subspaces -> first week = subspace 0
        rng = range(0, 1) if depth == 0 else range(last + 1, len(masks))
        for i in rng:
            if masks[i] & used == 0:
                if len(masks) - i < need:          # not enough indices left
                    return
                yield i

    def apply(self, s, i):
        token = (s[0], s[1])
        s[0] |= self.masks[i]
        s[1] = i
        s[2] += 1
        # counting bound: remaining non-zero vectors must fit the remaining weeks
        free_pts = (1 << self.d) - 1 - s[0].bit_count()
        return free_pts >= (self.W - s[2]) * ((1 << self.k) - 1), token

    def undo(self, s, token):
        s[0], s[1] = token
        s[2] -= 1

    def to_weeks(self, chosen: list[int]) -> list[list[list[int]]]:
        weeks = []
        n = 1 << self.d
        for i in chosen:
            U = self.subspaces[i][0]
            seen, groups = set(), []
            for x in range(n):
                if x not in seen:
                    grp = sorted(x ^ u for u in U)
                    seen.update(grp)
                    groups.append(grp)
            weeks.append(groups)
        return weeks


def solve_spread(d: int = 5, k: int = 2, weeks: int = 9, find_all: bool = False):
    """DFS over subspaces. Returns (weeks|None, stats).  The chosen indices are
    recovered by replaying the search path stored in the solution state."""
    pr = SpreadGolfers(d, k, weeks)
    chosen: list[int] = []
    # light wrapper that records the path so we can rebuild the schedule
    orig_apply, orig_undo = pr.apply, pr.undo

    def apply(s, i):
        chosen.append(i)
        return orig_apply(s, i)

    def undo(s, t):
        chosen.pop()
        orig_undo(s, t)

    pr.apply, pr.undo = apply, undo
    snapshot: list[list[int]] = []
    orig_goal = pr.is_goal

    def is_goal(s):
        g = orig_goal(s)
        if g and not snapshot:
            snapshot.append(chosen[:])
        return g

    pr.is_goal = is_goal
    sols, st = depth_first_backtracking(pr)
    if not sols:
        return None, st, pr
    return pr.to_weeks(snapshot[0]), st, pr
