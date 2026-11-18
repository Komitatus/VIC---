"""Exact reward-supply model for the fictional interactive dungeon proposal.

This contract models successful claims and carried stamina, not combat, Echo
rolls, growth time or live Wuthering Waves drop tables.
"""
import math

LIMITS = {
    "cost": (30, 80, 10),
    "xp_items": (1, 8, 1),
    "tuners": (0, 50, 2),
    "coins": (0, 30000, 1000),
    "daily_budget": (60, 240, 10),
}


def validate(model):
    if model.get("schema") == "proposed_dungeon_economy_v2":
        return validate_economy(model)
    if model.get("schema") != "proposed_dungeon_rewards_v1" or model.get("fictional") is not True:
        raise ValueError("A fictional reward proposal must be explicitly identified")
    if model.get("days") != 7 or model.get("xp_per_item") != 5000:
        raise ValueError("This example uses seven days and 5,000 EXP per sealed tube")
    stages = model.get("stages", [])
    if len(stages) != 3 or len({s["id"] for s in stages}) != 3:
        raise ValueError("Three distinct difficulty proposals are required")
    if model.get("selected_stage") not in {s["id"] for s in stages}:
        raise ValueError("Unknown selected stage")
    for key, (lo, hi, step) in LIMITS.items():
        values = [model[key]] if key == "daily_budget" else [s[key] for s in stages]
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi or (value - lo) % step:
                raise ValueError("Out-of-range or fractional input: " + key)
    return model


def project(stage, daily_budget, days=7, xp_per_item=5000):
    """Whole claims only; unspent allocated stamina carries to the next day."""
    if daily_budget < 0 or stage["cost"] <= 0 or days < 0:
        raise ValueError("Invalid claim budget")
    balance = total_claims = total_spent = 0
    rows = []
    for day in range(1, days + 1):
        balance += daily_budget
        claims, balance = divmod(balance, stage["cost"])
        total_claims += claims
        spent = claims * stage["cost"]
        total_spent += spent
        rows.append({
            "day": day, "claims": claims, "total_claims": total_claims,
            "spent": spent, "total_spent": total_spent, "carry": balance,
            "xp_items": total_claims * stage["xp_items"],
            "xp": total_claims * stage["xp_items"] * xp_per_item,
            "tuners": total_claims * stage["tuners"],
            "coins": total_claims * stage["coins"],
        })
        assert day * daily_budget == total_spent + balance
    return rows


def calculate(model):
    validate(model)
    if model["schema"] == "proposed_dungeon_economy_v2":
        return calculate_economy(model)
    rows = []
    for stage in model["stages"]:
        one = {"xp": stage["xp_items"] * model["xp_per_item"], "tuners": stage["tuners"], "coins": stage["coins"]}
        rows.append({"id": stage["id"], "per_claim": one,
                     "per_60_stamina": {k: v * 60 / stage["cost"] for k, v in one.items()},
                     "daily_rows": project(stage, model["daily_budget"], model["days"], model["xp_per_item"])})
    return {"calculation": "exact_successful_claims_with_carry", "stages": rows,
            "limitations": ["All compared stages are unlocked and all claims succeed.",
                            "No other income, spending, first-clear bonus or random rewards.",
                            "Cumulative supply is not a farming-time or growth-completion estimate."]}


RESOURCES = ("xp", "tuners", "coins")
GLOBAL_LIMITS = {
    "cost": (30, 120, 10), "xp_percent": (50, 200, 5),
    "tuner_percent": (0, 200, 5), "coin_percent": (0, 200, 5),
}


def _integer(value, lo, hi, step=1):
    return (isinstance(value, int) and not isinstance(value, bool)
            and lo <= value <= hi and (value - lo) % step == 0)


def validate_economy(model):
    if model.get("fictional") is not True or model.get("days") != 7 or model.get("xp_per_item") != 5000:
        raise ValueError("Seven-day fictional proposal with verified EXP conversion required")
    stages = model.get("stages", [])
    if [s["id"] for s in stages] != ["basic", "focused", "deep"]:
        raise ValueError("Three ordered base difficulties required")
    for stage in stages:
        for key in ("xp_items", "tuners", "coins"):
            if not _integer(stage[key], 0, 1000000):
                raise ValueError("Base rewards must be nonnegative whole items")
    for key, (lo, hi, step) in GLOBAL_LIMITS.items():
        if not _integer(model["global_controls"][key], lo, hi, step):
            raise ValueError("Invalid shared control: " + key)
    economy = model["economy"]
    for key, lo, hi, step in [("daily_budget", 60, 360, 10), ("new_share_percent", 0, 100, 5),
                               ("adoption_percent", 0, 100, 5), ("population", 1, 1000000, 1)]:
        if not _integer(economy[key], lo, hi, step):
            raise ValueError("Invalid economy input: " + key)
    shares = economy["stage_shares"]
    if set(shares) != {s["id"] for s in stages} or any(not _integer(v, 0, 100) for v in shares.values()) or sum(shares.values()) != 100:
        raise ValueError("Difficulty shares must sum to 100 percent")
    if not _integer(economy["legacy"]["cost"], 1, 1000):
        raise ValueError("Legacy claim cost must be positive")
    for row in (economy["legacy"]["per_claim"], economy["other_daily"], economy["daily_demand"]):
        if set(row) != set(RESOURCES):
            raise ValueError("All three currencies must be specified")
        for value in row.values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1e9:
                raise ValueError("Supply and demand must be finite and nonnegative")
    return model


def effective_stages(model):
    """Apply every slider to all stages; whole rewards use round-half-up."""
    controls = model["global_controls"]
    stages = []
    for base in model["stages"]:
        stage = {**base, "cost": controls["cost"]}
        for key, scale in [("xp_items", "xp_percent"), ("tuners", "tuner_percent"), ("coins", "coin_percent")]:
            stage[key] = (base[key] * controls[scale] + 50) // 100
        stages.append(stage)
    return stages


def calculate_economy(model):
    """Compare replacement, not additive free stamina. Average only after flooring
    each participant's claims; nonparticipants retain their original route.
    Supply minus demand is a resource gap, not an observed wallet balance.
    """
    validate_economy(model)
    economy, stages = model["economy"], effective_stages(model)
    days, budget = model["days"], economy["daily_budget"]
    adoption = economy["adoption_percent"] / 100
    new_budget = budget * economy["new_share_percent"] / 100
    legacy = economy["legacy"]
    new_rows = {s["id"]: project(s, new_budget, days, model["xp_per_item"]) for s in stages}
    rows = []
    for day in range(1, days + 1):
        before_claims = math.floor(day * budget / legacy["cost"])
        remaining_claims = math.floor(day * (budget - new_budget) / legacy["cost"])
        weighted = {key: sum(new_rows[s["id"]][day - 1][key] * economy["stage_shares"][s["id"]] / 100 for s in stages)
                    for key in (*RESOURCES, "total_claims", "total_spent", "carry")}
        row = {"day": day, "before_claims": before_claims, "remaining_legacy_claims": remaining_claims,
               "new_claims_participant": weighted["total_claims"],
               "new_claims_average": weighted["total_claims"] * adoption,
               "legacy_claims_average": before_claims + (remaining_claims - before_claims) * adoption}
        for key in ("before", "after", "delta", "participant_after", "new_supply_participant", "lost_legacy",
                    "other_supply", "demand", "net_before", "net_after", "totals_before", "totals_after", "totals_delta"):
            row[key] = {}
        for currency in RESOURCES:
            other = day * economy["other_daily"][currency]
            before = before_claims * legacy["per_claim"][currency] + other
            participant = remaining_claims * legacy["per_claim"][currency] + weighted[currency] + other
            after = before + (participant - before) * adoption
            demand = day * economy["daily_demand"][currency]
            row["before"][currency], row["after"][currency] = before, after
            row["delta"][currency] = after - before
            row["participant_after"][currency] = participant
            row["new_supply_participant"][currency] = weighted[currency]
            row["lost_legacy"][currency] = (before_claims - remaining_claims) * legacy["per_claim"][currency]
            row["other_supply"][currency], row["demand"][currency] = other, demand
            row["net_before"][currency], row["net_after"][currency] = before - demand, after - demand
            for source, target in [("before", "totals_before"), ("after", "totals_after"), ("delta", "totals_delta")]:
                row[target][currency] = row[source][currency] * economy["population"]
        before_used = before_claims * legacy["cost"]
        participant_used = remaining_claims * legacy["cost"] + weighted["total_spent"]
        row["used_stamina_average"] = before_used + (participant_used - before_used) * adoption
        row["carry_average"] = day * budget - row["used_stamina_average"]
        rows.append(row)
    return {"calculation": "fixed_budget_replacement_with_population_weights", "stages": stages,
            "new_daily_budget": new_budget, "legacy_daily_budget": budget - new_budget,
            "stage_rows": new_rows, "daily_rows": rows, "week": rows[-1],
            "limitations": ["Three Echo-growth currencies only; not the entire live game economy.",
                            "Historical legacy averages and editable fictional population, income and demand.",
                            "No Echo candidate valuation, combat failure, growth timing or price forecast."]}
