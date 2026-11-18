"""Conditional Wuwa farming estimates from explicit public distributions.

This is separate from the deterministic content-design engine. Candidate echoes
with the required set/main stat are assumed available. No account unlock time,
combat time, or unobserved drop probabilities are inferred here.
"""
from __future__ import annotations

from collections import defaultdict
import math
import random
import statistics


def type_probability(required: int, slots: int = 5, pool: int = 13) -> float:
    if not 0 <= required <= slots <= pool:
        raise ValueError("Invalid target or draw size")
    return math.comb(pool - required, slots - required) / math.comb(pool, slots)


def summarize(values: list[float]) -> dict:
    if not values or any(not math.isfinite(v) for v in values):
        raise ValueError("Finite observations required")
    ordered = sorted(values)
    return {"mean": statistics.mean(ordered),
            "p50": ordered[math.ceil(len(ordered) * .5) - 1],
            "p90": ordered[math.ceil(len(ordered) * .9) - 1],
            "min": ordered[0], "max": ordered[-1]}


def _goal_probabilities(goals: dict, disclosure: dict) -> dict:
    if len(goals) > 5 or len(disclosure["substats"]) != 13:
        raise ValueError("This model requires the disclosed 13-type pool")
    result = {}
    for name, minimum in goals.items():
        table = disclosure["substats"][name]
        weights = table["probabilities"]
        if len(weights) != len(table["values"]) or any(w < 0 for w in weights) or not math.isclose(sum(weights), 1):
            raise ValueError("Invalid disclosed probability table")
        result[name] = sum(p for value, p in zip(table["values"], weights)
                           if minimum is None or value >= minimum)
        if result[name] <= 0:
            raise ValueError("Unreachable target")
    return result


def _discard(state: tuple[int, ...], stage: int, names: list[str], policy: str) -> bool:
    if policy == "full25":
        return stage == 5 and not all(x == 1 for x in state)
    if policy not in ("screen10", "screen15"):
        raise ValueError("Unknown screening policy")
    # A wanted type below its minimum can never reappear on this echo.
    if 2 in state or state.count(0) > 5 - stage:
        return True
    gate = 2 if policy == "screen10" else 3
    critical = [i for i, name in enumerate(names) if name in ("crit_rate", "crit_damage")]
    return stage == gate and bool(critical) and not any(state[i] == 1 for i in critical)


def policy_expectation(goals: dict, disclosure: dict, checkpoints: list[dict], policy: str) -> dict:
    """Exact finite-state expectation; 0 unseen, 1 accepted, 2 below minimum."""
    probabilities = _goal_probabilities(goals, disclosure)
    names = list(goals)
    active = {(0,) * len(names): 1.0}
    gross_xp = gross_tuners = coins = refund_xp = refund_tuners = success = 0.0
    previous_xp = previous_coins = 0
    termination_mass = 0.0
    for stage, checkpoint in enumerate(checkpoints, 1):
        reaching = sum(active.values())
        gross_xp += reaching * (checkpoint["cumulative_exp"] - previous_xp)
        gross_tuners += reaching * 10
        coins += reaching * (checkpoint["total_coins"] - previous_coins)
        previous_xp, previous_coins = checkpoint["cumulative_exp"], checkpoint["total_coins"]
        following = defaultdict(float)
        for state, mass in active.items():
            used_goals = sum(x != 0 for x in state)
            unused_other = 13 - len(names) - (stage - 1 - used_goals)
            branches = [(state, unused_other / (14 - stage))]
            for i, name in enumerate(names):
                if state[i] != 0:
                    continue
                for outcome, probability in ((1, probabilities[name]), (2, 1 - probabilities[name])):
                    revised = list(state)
                    revised[i] = outcome
                    branches.append((tuple(revised), probability / (14 - stage)))
            for revised, probability in branches:
                weight = mass * probability
                failed = _discard(revised, stage, names, policy)
                if failed:
                    refund_xp += weight * checkpoint["refunded_exp"]
                    refund_tuners += weight * checkpoint["refunded_tuners"]
                    termination_mass += weight
                elif stage == 5:
                    success += weight
                    termination_mass += weight
                else:
                    following[revised] += weight
        active = following
    if not math.isclose(termination_mass, 1, abs_tol=1e-10) or success <= 0:
        raise ValueError("Incomplete or unreachable state model")
    return {"success_probability_per_candidate": success,
            "expected_candidates": 1 / success,
            "expected_net_xp": (gross_xp - refund_xp) / success,
            "expected_net_tuners": (gross_tuners - refund_tuners) / success,
            "expected_coins": coins / success}


def _draw_attempt(rng: random.Random, goals: dict, probabilities: dict, names: list[str], pool: list[str], policy: str):
    state = [0] * len(names)
    order = rng.sample(pool, 5)
    for stage, name in enumerate(order, 1):
        if name in goals:
            state[names.index(name)] = 1 if rng.random() < probabilities[name] else 2
        failed = _discard(tuple(state), stage, names, policy)
        yield stage, failed, stage == 5 and not failed
        if failed:
            return


def simulate_echoes(goals: dict, disclosure: dict, checkpoints: list[dict],
                    tacet_rows: list[dict], *, policy: str = "screen10",
                    tuners_per_claim: int = 20, shell_per_claim: int = 84000,
                    keep: int = 1, samples: int = 5000, seed: int = 20261118,
                    initial_inventory: tuple[int, int, int] = (0, 0, 0)) -> dict:
    if len(checkpoints) != 5 or not tacet_rows or samples < 1 or keep < 1:
        raise ValueError("Missing checkpoints, observations, or sample size")
    if tuners_per_claim <= 0 or shell_per_claim <= 0 or min(initial_inventory) < 0:
        raise ValueError("Invalid supply or inventory")
    if any(r["exp"] <= 0 or r["shell"] < 0 for r in tacet_rows):
        raise ValueError("Invalid Tacet reward bundle")
    probabilities = _goal_probabilities(goals, disclosure)
    pool, names = list(disclosure["substats"]), list(goals)
    metrics = defaultdict(list)
    for sample in range(samples):
        # Separate streams preserve the same tuning trials across supply proposals.
        tune = random.Random(seed + sample * 2)
        loot = random.Random(seed + sample * 2 + 1)
        xp, tuners, shell = initial_inventory
        earned_xp = earned_tuners = earned_shell = 0
        net_xp = net_tuners = spent_shell = attempts = kept = tacet = credit = 0
        while kept < keep:
            attempts += 1
            if attempts > 100000:
                raise ValueError("Trial exceeded supported horizon; do not silently drop it")
            previous_xp = previous_shell = 0
            for stage, failed, accepted in _draw_attempt(tune, goals, probabilities, names, pool, policy):
                point = checkpoints[stage - 1]
                need_xp = point["cumulative_exp"] - previous_xp
                need_shell = point["total_coins"] - previous_shell
                previous_xp, previous_shell = point["cumulative_exp"], point["total_coins"]
                while xp < need_xp or tuners < 10 or shell < need_shell:
                    if xp < need_xp or tuners < 10:
                        bundle = loot.choice(tacet_rows)
                        xp += bundle["exp"]
                        shell += bundle["shell"]
                        tuners += tuners_per_claim
                        earned_xp += bundle["exp"]
                        earned_shell += bundle["shell"]
                        earned_tuners += tuners_per_claim
                        tacet += 1
                    else:
                        shell += shell_per_claim
                        earned_shell += shell_per_claim
                        credit += 1
                xp -= need_xp
                tuners -= 10
                shell -= need_shell
                net_xp += need_xp
                net_tuners += 10
                spent_shell += need_shell
                if failed:
                    xp += point["refunded_exp"]
                    tuners += point["refunded_tuners"]
                    net_xp -= point["refunded_exp"]
                    net_tuners -= point["refunded_tuners"]
                elif accepted:
                    kept += 1
        if (xp, tuners, shell) != (initial_inventory[0] + earned_xp - net_xp,
                                   initial_inventory[1] + earned_tuners - net_tuners,
                                   initial_inventory[2] + earned_shell - spent_shell):
            raise AssertionError("Resource conservation failed")
        waveplates = tacet * 60 + credit * 40
        row = {"candidates": attempts, "tacet_claims": tacet, "credit_claims": credit,
               "waveplates": waveplates, "waveplate_equivalent_days": waveplates / 240,
               "net_xp": net_xp, "net_tuners": net_tuners, "coins_spent": spent_shell}
        for key, value in row.items():
            metrics[key].append(value)
    return {"samples": samples, "seed": seed, "keep": keep, "policy": policy,
            "goals": goals, "tuners_per_claim": tuners_per_claim,
            "initial_inventory": list(initial_inventory),
            "metrics": {key: summarize(values) for key, values in metrics.items()}}


def simulate_material(rows: list[dict], field: str, target: float, *, waveplate_cost: int,
                      samples: int = 10000, seed: int = 20261118) -> dict:
    if target <= 0 or not rows or waveplate_cost <= 0 or samples < 1 or any(r[field] < 0 for r in rows) or not any(r[field] > 0 for r in rows):
        raise ValueError("Invalid material farming model")
    rng = random.Random(seed)
    counts = []
    for _ in range(samples):
        total = runs = 0
        while total < target:
            total += rng.choice(rows)[field]
            runs += 1
            if runs > 100000:
                raise ValueError("Material trial exceeded supported horizon")
        counts.append(runs)
    return {"target": target, "field": field, "samples": samples, "seed": seed,
            "claims": summarize(counts),
            "waveplate_equivalent_days": summarize([c * waveplate_cost / 240 for c in counts])}
