"""유저 단위 이산 시뮬레이션. 확률과 최초 보상을 기대값으로 매일 중복 지급하지 않는다."""

from collections import defaultdict
import hashlib
import math
import random

from . import __version__
from .model import fingerprint, validate


def quantile(values, probability):
    if not values:
        return None
    return sorted(values)[max(0, math.ceil(len(values) * probability) - 1)]


def reward_expectations(model):
    rows = []
    for stage in model["content"]["stages"]:
        values = defaultdict(float)
        for reward in stage["rewards"]:
            values[reward["currency"]] += reward["amount"] * reward["probability"]
        for currency in model["currencies"]:
            amount = values[currency["id"]]
            rows.append({"stage": stage["id"], "currency": currency["id"],
                         "per_clear": amount, "per_attempt": amount * stage["clear_rate"],
                         "per_minute": amount * stage["clear_rate"] / stage["minutes"],
                         "first_clear": stage["first_clear"].get(currency["id"], 0)})
    return rows


def draw_rewards(stage, rng):
    result = defaultdict(float)
    grouped = defaultdict(list)
    for reward in stage["rewards"]:
        if reward["group"]:
            grouped[reward["group"]].append(reward)
        elif rng.random() < reward["probability"]:
            result[reward["currency"]] += reward["amount"]
    for choices in grouped.values():
        roll = rng.random()
        cumulative = 0
        for reward in choices:
            cumulative += reward["probability"]
            if roll < cumulative:
                result[reward["currency"]] += reward["amount"]
                break
    return result


def can_pay(wallet, amounts):
    return all(wallet[currency] + 1e-9 >= amount for currency, amount in amounts.items())


def run_player(model, cohort, rng):
    content, growth = model["content"], model["growth"]
    currencies = [currency["id"] for currency in model["currencies"]]
    wallet = {currency: float(cohort["initial_wallet"].get(currency, 0)) for currency in currencies}
    flows = {kind: dict.fromkeys(currencies, 0.0) for kind in
             ("external_income", "purchase_income", "content_income", "entry_cost", "growth_cost", "other_sink", "unpaid_sink")}
    level = cohort["start_level"]
    reached_day = 0 if level >= growth["target_level"] else None
    steps = {step["level"]: step for step in growth["steps"]}
    first_clears = set()
    remaining = 0
    total_attempts = total_clears = total_minutes = active_days = 0
    blocked = defaultdict(int)
    stage_attempts = defaultdict(int)
    stage_clears = defaultdict(int)
    daily = []
    spent_krw = 0

    def transfer(amounts, kind, direction):
        for currency, amount in amounts.items():
            wallet[currency] += direction * amount
            flows[kind][currency] += amount
            if abs(wallet[currency]) < 1e-9:
                wallet[currency] = 0.0

    def grow(day):
        nonlocal level, reached_day
        while level < growth["target_level"]:
            step = steps[level + 1]
            if not can_pay(wallet, step["cost"]):
                break
            transfer(step["cost"], "growth_cost", -1)
            level += 1
        if level >= growth["target_level"] and reached_day is None:
            reached_day = day

    grow(0)
    for day in range(1, model["simulation"]["days"] + 1):
        transfer(cohort["daily_income"], "external_income", 1)
        for purchase in cohort["purchases"]:
            if purchase["day"] == day:
                transfer(purchase["grants"], "purchase_income", 1)
                spent_krw += purchase["price_krw"]
        for currency, requested in cohort["daily_sink"].items():
            actual = min(wallet[currency], requested)
            transfer({currency: actual}, "other_sink", -1)
            flows["unpaid_sink"][currency] += requested - actual
        grow(day)
        attempts = clears = minutes = 0
        active = rng.random() < cohort["active_days_per_week"] / 7
        active_days += int(active)
        opened = content["start_day"] <= day <= content["end_day"]
        if opened and (day - content["start_day"]) % content["reset_days"] == 0:
            remaining = content["attempts_per_reset"]
        if active and opened:
            for _ in range(min(remaining, cohort["attempts_per_active_day"])):
                eligible = [stage for stage in content["stages"] if stage["min_level"] <= level]
                if not eligible:
                    blocked["level"] += 1
                    break
                affordable_time = [stage for stage in eligible if stage["minutes"] <= cohort["minutes_per_active_day"] - minutes + 1e-9]
                if not affordable_time:
                    blocked["time"] += 1
                    break
                if not can_pay(wallet, content["entry_cost"]):
                    blocked["entry_cost"] += 1
                    break
                stage = affordable_time[-1]
                success = rng.random() < min(1, stage["clear_rate"] * cohort["clear_rate_multiplier"])
                ratio = 1 if success else content["failure_cost_ratio"]
                transfer({k: v * ratio for k, v in content["entry_cost"].items()}, "entry_cost", -1)
                remaining -= 1
                attempts += 1
                stage_attempts[stage["id"]] += 1
                minutes += stage["minutes"]
                if success:
                    clears += 1
                    stage_clears[stage["id"]] += 1
                    transfer(draw_rewards(stage, rng), "content_income", 1)
                    if stage["id"] not in first_clears:
                        first_clears.add(stage["id"])
                        transfer(stage["first_clear"], "content_income", 1)
                    grow(day)
        total_attempts += attempts
        total_clears += clears
        total_minutes += minutes
        next_cost = steps[level + 1]["cost"] if level < growth["target_level"] else {}
        power = steps[level]["power"] if level in steps else growth["starting_power"]
        daily.append({"day": day, "level": level, "power": power, "attempts": attempts,
                      "clears": clears, "minutes": minutes, "active": int(active),
                      "reached": int(reached_day is not None), "wallet": dict(wallet),
                      "shortage": {k: max(0, next_cost.get(k, 0) - wallet[k]) for k in currencies}})

    # 재화별 수급 보존식. 중복 지급·숨은 차감이 생기면 결과를 내지 않는다.
    for currency in currencies:
        expected = cohort["initial_wallet"].get(currency, 0)
        expected += sum(flows[kind][currency] for kind in ("external_income", "purchase_income", "content_income"))
        expected -= sum(flows[kind][currency] for kind in ("entry_cost", "growth_cost", "other_sink"))
        if not math.isclose(wallet[currency], expected, rel_tol=1e-10, abs_tol=1e-5) or wallet[currency] < -1e-7:
            raise ArithmeticError(f"재화 보존식 불일치: {currency}")
    return {"daily": daily, "level": level, "reached_day": reached_day, "wallet": wallet,
            "flows": flows, "attempts": total_attempts, "clears": total_clears,
            "minutes": total_minutes, "active_days": active_days, "spent_krw": spent_krw,
            "blocked": blocked, "stage_attempts": stage_attempts, "stage_clears": stage_clears}


def simulate(model):
    validate(model)
    days, samples, seed = (model["simulation"][key] for key in ("days", "samples", "seed"))
    currencies = [row["id"] for row in model["currencies"]]
    result = {"schema_version": 1, "engine_version": __version__, "model_hash": fingerprint(model),
              "game": model["game"], "content_id": model["content"]["id"], "content_name": model["content"]["name"],
              "simulation": dict(model["simulation"]), "assumptions": list(model["assumptions"]),
              "method": "유저별 이산 Monte Carlo. p10/p50/p90은 미도달자를 포함하며 관측 기간을 넘으면 null. 실측 예측 정확도를 뜻하지 않음.",
              "reward_expectations": reward_expectations(model), "cohorts": [], "checks": [], "warnings": []}
    for cohort in model["cohorts"]:
        day_sums = [{"day": day, "level": 0, "power": 0, "attempts": 0, "clears": 0,
                     "minutes": 0, "active": 0, "reached": 0,
                     "wallet": dict.fromkeys(currencies, 0.0), "shortage": dict.fromkeys(currencies, 0.0)}
                    for day in range(1, days + 1)]
        totals = defaultdict(float)
        flow_sums = defaultdict(lambda: defaultdict(float))
        blocked = defaultdict(float)
        stage_attempts = defaultdict(float)
        stage_clears = defaultdict(float)
        reaches, levels = [], []
        for index in range(samples):
            stable_seed = int.from_bytes(hashlib.sha256(f"{seed}:{cohort['id']}:{index}".encode()).digest()[:8], "big")
            player = run_player(model, cohort, random.Random(stable_seed))
            reaches.append(player["reached_day"])
            levels.append(player["level"])
            for key in ("attempts", "clears", "minutes", "active_days", "spent_krw"):
                totals[key] += player[key]
            for kind, amounts in player["flows"].items():
                for currency, amount in amounts.items():
                    flow_sums[kind][currency] += amount
            for target, source in ((blocked, "blocked"), (stage_attempts, "stage_attempts"), (stage_clears, "stage_clears")):
                for key, value in player[source].items():
                    target[key] += value
            for aggregate, row in zip(day_sums, player["daily"]):
                for key in ("level", "power", "attempts", "clears", "minutes", "active", "reached"):
                    aggregate[key] += row[key]
                for key in ("wallet", "shortage"):
                    for currency in currencies:
                        aggregate[key][currency] += row[key][currency]
        for row in day_sums:
            for key in ("level", "power", "attempts", "clears", "minutes", "active", "reached"):
                row[key] /= samples
            for key in ("wallet", "shortage"):
                row[key] = {currency: amount / samples for currency, amount in row[key].items()}
        completed = [value for value in reaches if value is not None]
        censored = [value if value is not None else days + 1 for value in reaches]
        quantiles = {}
        for percentile in (10, 50, 90):
            value = quantile(censored, percentile / 100)
            quantiles[f"p{percentile}"] = value if value <= days else None
        rate = len(completed) / samples
        summary = {"id": cohort["id"], "name": cohort["name"], "reach_rate": rate,
                   "reach_rate_mc_se": math.sqrt(rate * (1 - rate) / samples),
                   "target_days": quantiles, "reached_only_p50": quantile(completed, 0.5),
                   "final_level_mean": sum(levels) / samples, "final_level_p50": quantile(levels, 0.5),
                   **{key + "_mean": value / samples for key, value in totals.items()},
                   "flows": {key: {currency: value / samples for currency, value in amounts.items()} for key, amounts in flow_sums.items()},
                   "wallet_mean": dict(day_sums[-1]["wallet"]),
                   "blocked_days_mean": {key: value / samples for key, value in blocked.items()},
                   "stage_attempts_mean": {key: value / samples for key, value in stage_attempts.items()},
                   "stage_clears_mean": {key: value / samples for key, value in stage_clears.items()},
                   "daily": day_sums}
        result["cohorts"].append(summary)
        if summary["attempts_mean"] == 0:
            result["warnings"].append(f"{cohort['id']}: 콘텐츠 입장 0회. 접속·시간·해금·입장 비용·참여 제한을 확인하세요.")
        if rate < 0.9:
            result["warnings"].append(f"{cohort['id']}: {days}일 안에 목표 미도달 {1-rate:.1%}; 미도달자를 제외한 중앙값을 전체 중앙값으로 사용하지 마세요.")
        if any(value > 0 for value in summary["flows"]["unpaid_sink"].values()):
            result["warnings"].append(f"{cohort['id']}: 예정 소모를 잔액 부족으로 모두 지불하지 못했습니다. unpaid_sink를 확인하세요.")
        target = next((row for row in model["targets"] if row["cohort"] == cohort["id"]), None)
        if target:
            median = quantiles["p50"]
            passed = median is not None and target["p50_day_min"] <= median <= target["p50_day_max"] and rate >= target["min_completion_rate"]
            result["checks"].append({"cohort": cohort["id"], "passed": passed, "target": target,
                                     "actual_p50": median, "actual_reach_rate": rate})
    result["status"] = "no_targets" if not result["checks"] else ("pass" if all(c["passed"] for c in result["checks"]) else "needs_tuning")
    return result


def compare(baseline, candidate):
    if baseline["content_id"] != candidate["content_id"] or baseline["game"] != candidate["game"]:
        raise ValueError("같은 게임·콘텐츠의 설계안끼리 비교하세요")
    if baseline["simulation"] != candidate["simulation"]:
        raise ValueError("비교안의 days·samples·seed를 동일하게 맞추세요")
    old = {row["id"]: row for row in baseline["cohorts"]}
    new = {row["id"]: row for row in candidate["cohorts"]}
    rows = []
    for cid in sorted(old.keys() | new.keys()):
        if cid not in old or cid not in new:
            rows.append({"cohort": cid, "change": "added" if cid in new else "removed"})
            continue
        a, b = old[cid], new[cid]
        p50a, p50b = a["target_days"]["p50"], b["target_days"]["p50"]
        rows.append({"cohort": cid, "change": "compared", "baseline_p50": p50a, "candidate_p50": p50b,
                     "p50_delta_days": p50b - p50a if p50a is not None and p50b is not None else None,
                     "reach_rate_delta_pp": 100 * (b["reach_rate"] - a["reach_rate"]),
                     "final_level_delta": b["final_level_mean"] - a["final_level_mean"],
                     "minutes_delta": b["minutes_mean"] - a["minutes_mean"]})
    return {"baseline_hash": baseline["model_hash"], "candidate_hash": candidate["model_hash"], "rows": rows}
