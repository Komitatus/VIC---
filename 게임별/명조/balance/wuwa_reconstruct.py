"""Exact sub-stat reconstruction (주파수 조정기) costs for a +25 5-star echo.

Rules come from the official disclosure and the 3.8.0 client table:
- reconstruction is allowed only after all five slots are tuned;
- locked types never reappear, unlocked old types may reappear;
- each rerolled slot shows one of the (13 - locked) types with equal probability,
  and rerolled slots do not duplicate each other (same rule as tuning);
- the item cost depends on the lock count (PhantomVicePolishConfig.Cost).

The policy locks every target type that already meets its minimum value. When no
target qualifies it locks ``zero_lock`` non-target types (1 by default, matching the
smallest lock count listed in the disclosure). Item supply is not modelled.
"""
from __future__ import annotations

from functools import lru_cache
from itertools import combinations
import math

from balance.wuwa_farming import _goal_probabilities

SLOTS, POOL = 5, 13


def _appear(missing: tuple[str, ...], draws: int, pool: int):
    """Yield (subset of missing types that appear, probability) for ``draws`` from ``pool``."""
    total = math.comb(pool, draws)
    others = pool - len(missing)
    for size in range(len(missing) + 1):
        if size > draws:
            break
        ways = math.comb(others, draws - size) / total
        for subset in combinations(missing, size):
            yield subset, ways


def _transitions(have: frozenset, names: tuple[str, ...], q: dict, draws: int, pool: int):
    missing = tuple(n for n in names if n not in have)
    out: dict[frozenset, float] = {}
    for shown, p_shown in _appear(missing, draws, pool):
        # each shown target independently passes its value threshold
        for mask in range(1 << len(shown)):
            p = p_shown
            gained = set()
            for i, name in enumerate(shown):
                if mask >> i & 1:
                    p *= q[name]
                    gained.add(name)
                else:
                    p *= 1 - q[name]
            if p:
                key = have | frozenset(gained)
                out[key] = out.get(key, 0.0) + p
    return out


def reconstruction_expectation(goals: dict, disclosure: dict, lock_costs: dict[int, int],
                               *, zero_lock: int = 1, max_steps: int = 2000) -> dict:
    """Expected and percentile 조정기 use for one +25 echo until all goals qualify."""
    if not goals:
        raise ValueError("At least one target sub-stat is required")
    names = tuple(sorted(goals))
    if len(names) > 4:
        raise ValueError("At least one slot must remain unlocked")
    q = _goal_probabilities(goals, disclosure)
    goal = frozenset(names)

    def plan(have: frozenset) -> tuple[int, int]:
        locked = len(have) if have else zero_lock
        if locked not in lock_costs:
            raise ValueError(f"No reconstruction cost for {locked} locked slots")
        return lock_costs[locked], locked

    @lru_cache(maxsize=None)
    def step(have: frozenset):
        cost, locked = plan(have)
        return cost, _transitions(have, names, q, SLOTS - locked, POOL - locked)

    @lru_cache(maxsize=None)
    def expected(have: frozenset) -> float:
        if have == goal:
            return 0.0
        cost, nxt = step(have)
        stay = nxt.get(have, 0.0)
        rest = sum(p * expected(s) for s, p in nxt.items() if s != have)
        return (cost + rest) / (1 - stay)

    start = _transitions(frozenset(), names, q, SLOTS, POOL)
    natural = start.get(goal, 0.0)
    mean = sum(p * expected(s) for s, p in start.items())

    # distribution of items used, by forward propagation over item counts
    mass = {(s, 0): p for s, p in start.items()}
    done: dict[int, float] = {}
    for _ in range(max_steps):
        nxt: dict = {}
        for (s, used), p in mass.items():
            if s == goal:
                done[used] = done.get(used, 0.0) + p
                continue
            cost, trans = step(s)
            for s2, p2 in trans.items():
                k = (s2, used + cost)
                nxt[k] = nxt.get(k, 0.0) + p * p2
        mass = nxt
        if sum(mass.values()) < 1e-12:
            break
    else:
        raise ValueError("Reconstruction distribution did not converge")

    def quantile(level: float) -> int:
        acc = 0.0
        for used in sorted(done):
            acc += done[used]
            if acc >= level - 1e-12:
                return used
        raise ValueError("Quantile outside distribution")

    states = {",".join(sorted(s)) or "-": {"probability_after_natural_25": p,
                                          "expected_items_from_state": expected(s)}
              for s, p in sorted(start.items(), key=lambda kv: len(kv[0]))}
    return {"natural_success_probability": natural,
            "expected_items": mean,
            "p50_items": quantile(.5), "p90_items": quantile(.9),
            "zero_lock": zero_lock,
            "states_after_natural_25": states}
