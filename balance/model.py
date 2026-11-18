"""입력 계약과 예제. 지원하지 않는 필드는 조용히 무시하지 않는다."""

import hashlib
import json
import math
from pathlib import Path


class ModelError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ModelError(message)


def obj(value, path, required, optional=()):
    require(isinstance(value, dict), f"{path}: 객체여야 합니다")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    require(not missing, f"{path}: 필수 필드 누락 {sorted(missing)}")
    require(not extra, f"{path}: 지원하지 않는 필드 {sorted(extra)}")


def number(value, path, low=0, high=1e12, integer=False):
    require(type(value) in (int, float), f"{path}: 숫자여야 합니다")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite, f"{path}: 유한한 숫자여야 합니다")
    require(low <= value <= high, f"{path}: {low}~{high} 범위여야 합니다")
    if integer:
        require(type(value) is int, f"{path}: 정수여야 합니다")


def string(value, path):
    require(isinstance(value, str) and bool(value.strip()), f"{path}: 비어 있지 않은 문자열이어야 합니다")
    require(len(value) <= 2000, f"{path}: 문자열이 너무 깁니다")


def array(value, path, minimum=1, maximum=100):
    require(isinstance(value, list) and minimum <= len(value) <= maximum,
            f"{path}: 항목 {minimum}~{maximum}개의 배열이어야 합니다")


def unique(rows, field, path):
    seen = set()
    for row in rows:
        string(row.get(field), f"{path}.{field}")
        require(row[field] not in seen, f"{path}: 중복 {field} {row[field]}")
        seen.add(row[field])
    return seen


def validate(model):
    obj(model, "$", ("schema_version", "game", "content", "currencies", "growth", "cohorts", "simulation", "targets", "assumptions"))
    require(type(model["schema_version"]) is int and model["schema_version"] == 1, "schema_version: 지원 버전은 1입니다")
    string(model["game"], "game")
    array(model["assumptions"], "assumptions")
    for note in model["assumptions"]:
        string(note, "assumptions[]")
    array(model["currencies"], "currencies", maximum=20)
    for row in model["currencies"]:
        obj(row, "currencies[]", ("id", "name", "unit"))
        string(row["name"], "currencies.name")
        string(row["unit"], "currencies.unit")
    currencies = unique(model["currencies"], "id", "currencies")

    def amounts(value, path):
        require(isinstance(value, dict), f"{path}: 재화 ID → 수량 객체여야 합니다")
        for key, amount in value.items():
            require(key in currencies, f"{path}: 알 수 없는 재화 {key}")
            number(amount, f"{path}.{key}")

    simulation = model["simulation"]
    obj(simulation, "simulation", ("days", "samples", "seed"))
    number(simulation["days"], "simulation.days", 1, 366, True)
    number(simulation["samples"], "simulation.samples", 1, 5000, True)
    number(simulation["seed"], "simulation.seed", 0, 2**32 - 1, True)
    content = model["content"]
    obj(content, "content", ("id", "name", "start_day", "end_day", "reset_days", "attempts_per_reset", "entry_cost", "failure_cost_ratio", "stages"))
    string(content["id"], "content.id")
    string(content["name"], "content.name")
    number(content["start_day"], "content.start_day", 1, simulation["days"], True)
    number(content["end_day"], "content.end_day", content["start_day"], simulation["days"], True)
    number(content["reset_days"], "content.reset_days", 1, 366, True)
    number(content["attempts_per_reset"], "content.attempts_per_reset", 0, 1000, True)
    number(content["failure_cost_ratio"], "content.failure_cost_ratio", 0, 1)
    amounts(content["entry_cost"], "content.entry_cost")

    growth = model["growth"]
    obj(growth, "growth", ("start_level", "target_level", "starting_power", "steps"))
    number(growth["start_level"], "growth.start_level", 0, 999, True)
    number(growth["target_level"], "growth.target_level", growth["start_level"] + 1, 1000, True)
    number(growth["starting_power"], "growth.starting_power")
    array(growth["steps"], "growth.steps", maximum=1000)
    levels = []
    last_power = growth["starting_power"]
    for step in growth["steps"]:
        obj(step, "growth.steps[]", ("level", "cost", "power"))
        number(step["level"], "growth.steps.level", growth["start_level"] + 1, growth["target_level"], True)
        levels.append(step["level"])
        amounts(step["cost"], "growth.steps.cost")
        number(step["power"], "growth.steps.power", last_power)
        last_power = step["power"]
    require(levels == list(range(growth["start_level"] + 1, growth["target_level"] + 1)),
            "growth.steps: 시작 다음 단계부터 목표까지 빠짐없이 오름차순이어야 합니다")

    array(content["stages"], "content.stages", maximum=30)
    previous_level = -1
    for stage in content["stages"]:
        obj(stage, "stages[]", ("id", "name", "min_level", "minutes", "clear_rate", "rewards", "first_clear"))
        string(stage["name"], "stages.name")
        number(stage["min_level"], "stages.min_level", growth["start_level"], growth["target_level"], True)
        require(stage["min_level"] > previous_level, "stages: min_level이 중복 없이 오름차순이어야 합니다")
        previous_level = stage["min_level"]
        number(stage["minutes"], "stages.minutes", 0.01, 1440)
        number(stage["clear_rate"], "stages.clear_rate", 0, 1)
        amounts(stage["first_clear"], "stages.first_clear")
        array(stage["rewards"], "stages.rewards", minimum=0)
        groups = {}
        for reward in stage["rewards"]:
            obj(reward, "rewards[]", ("currency", "amount", "probability", "group"))
            string(reward["currency"], "rewards.currency")
            require(reward["currency"] in currencies, f"rewards: 알 수 없는 재화 {reward['currency']}")
            number(reward["amount"], "rewards.amount")
            number(reward["probability"], "rewards.probability", 0, 1)
            require(isinstance(reward["group"], str), "rewards.group: 문자열이어야 합니다")
            if reward["group"]:
                groups[reward["group"]] = groups.get(reward["group"], 0) + reward["probability"]
        for group, probability in groups.items():
            require(probability <= 1 + 1e-12, f"상호 배타 보상 그룹 {group}: 확률 합이 1을 넘습니다")
    unique(content["stages"], "id", "stages")

    array(model["cohorts"], "cohorts", maximum=12)
    for cohort in model["cohorts"]:
        obj(cohort, "cohorts[]", ("id", "name", "start_level", "active_days_per_week", "minutes_per_active_day", "attempts_per_active_day", "clear_rate_multiplier", "initial_wallet", "daily_income", "daily_sink", "purchases"))
        string(cohort["name"], "cohorts.name")
        number(cohort["start_level"], "cohorts.start_level", growth["start_level"], growth["target_level"], True)
        number(cohort["active_days_per_week"], "cohorts.active_days_per_week", 0, 7)
        number(cohort["minutes_per_active_day"], "cohorts.minutes_per_active_day", 0, 1440)
        number(cohort["attempts_per_active_day"], "cohorts.attempts_per_active_day", 0, 100, True)
        number(cohort["clear_rate_multiplier"], "cohorts.clear_rate_multiplier", 0, 10)
        for field in ("initial_wallet", "daily_income", "daily_sink"):
            amounts(cohort[field], f"cohorts.{field}")
        array(cohort["purchases"], "cohorts.purchases", minimum=0, maximum=366)
        for purchase in cohort["purchases"]:
            obj(purchase, "purchases[]", ("id", "day", "price_krw", "grants"))
            number(purchase["day"], "purchases.day", 1, simulation["days"], True)
            number(purchase["price_krw"], "purchases.price_krw")
            amounts(purchase["grants"], "purchases.grants")
        unique(cohort["purchases"], "id", "purchases")
    ids = unique(model["cohorts"], "id", "cohorts")
    work = sum(c["attempts_per_active_day"] + len(growth["steps"]) + 1 for c in model["cohorts"])
    require(simulation["days"] * simulation["samples"] * work <= 30_000_000,
            "계산 규모가 너무 큽니다. samples·days·성장 단계·일일 시도 수를 줄이세요 (작업 상한 3천만)")

    array(model["targets"], "targets", minimum=0, maximum=12)
    for target in model["targets"]:
        obj(target, "targets[]", ("cohort", "p50_day_min", "p50_day_max", "min_completion_rate"))
        string(target["cohort"], "targets.cohort")
        require(target["cohort"] in ids, f"targets: 알 수 없는 코호트 {target['cohort']}")
        number(target["p50_day_min"], "targets.p50_day_min", 0, simulation["days"], True)
        number(target["p50_day_max"], "targets.p50_day_max", target["p50_day_min"], simulation["days"], True)
        number(target["min_completion_rate"], "targets.min_completion_rate", 0, 1)
    unique(model["targets"], "cohort", "targets")
    return model


def load_json(path):
    def reject_constant(value):
        raise ModelError(f"JSON: 비유한 숫자 {value}는 허용하지 않습니다")

    def no_duplicates(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"JSON: 중복 키 {key}")
            result[key] = value
        return result

    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          parse_constant=reject_constant, object_pairs_hook=no_duplicates)
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ModelError(f"{path}: JSON을 읽을 수 없습니다: {error}") from error


def load_model(path):
    return validate(load_json(path))


def fingerprint(model):
    raw = json.dumps(model, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def example(game="예시게임", name="성장던전", preset="daily"):
    """모든 수치는 가상이다. 입력 파일에 가정 표시를 남긴다."""
    days = 28
    content = {"id": "growth_dungeon", "name": name, "start_day": 1, "end_day": days,
               "reset_days": 1, "attempts_per_reset": 3, "entry_cost": {"ticket": 1},
               "failure_cost_ratio": 1,
               "stages": [
                   {"id": "normal", "name": "일반", "min_level": 0, "minutes": 3, "clear_rate": 0.95,
                    "rewards": [{"currency": "gold", "amount": 100, "probability": 1, "group": ""},
                                {"currency": "shard", "amount": 8, "probability": 1, "group": ""},
                                {"currency": "shard", "amount": 5, "probability": 0.2, "group": ""}],
                    "first_clear": {"gold": 200, "shard": 15}},
                   {"id": "hard", "name": "어려움", "min_level": 5, "minutes": 4, "clear_rate": 0.85,
                    "rewards": [{"currency": "gold", "amount": 180, "probability": 1, "group": ""},
                                {"currency": "shard", "amount": 15, "probability": 1, "group": ""}],
                    "first_clear": {"gold": 400, "shard": 30}}]}
    if preset == "raid":
        content.update(id="weekly_raid", reset_days=7, attempts_per_reset=3)
        for stage in content["stages"]:
            stage["minutes"] *= 3
            for reward in stage["rewards"]:
                reward["amount"] *= 5
    elif preset == "event":
        content.update(id="limited_event", end_day=14)
    elif preset != "daily":
        raise ModelError(f"알 수 없는 프리셋: {preset}")
    cohorts = []
    for cid, title, active, minutes, attempts in [
        ("casual", "라이트 무과금", 4, 12, 2),
        ("regular", "꾸준한 무과금", 7, 30, 3),
        ("pass", "패스 이용", 7, 30, 3),
    ]:
        cohorts.append({"id": cid, "name": title, "start_level": 0,
                        "active_days_per_week": active, "minutes_per_active_day": minutes,
                        "attempts_per_active_day": attempts, "clear_rate_multiplier": 1,
                        "initial_wallet": {}, "daily_income": {"gold": 60, "ticket": 3},
                        "daily_sink": {"gold": 20},
                        "purchases": ([{"id": "pass_28d", "day": 1, "price_krw": 9900,
                                        "grants": {"gold": 800, "shard": 120}}] if cid == "pass" else [])})
    return validate({"schema_version": 1, "game": game, "content": content,
                     "currencies": [{"id": "gold", "name": "골드", "unit": "개"},
                                    {"id": "shard", "name": "성장 조각", "unit": "개"},
                                    {"id": "ticket", "name": "입장권", "unit": "장"}],
                     "growth": {"start_level": 0, "target_level": 10, "starting_power": 100,
                                "steps": [{"level": level, "cost": {"gold": 120 + level * 35, "shard": 15 + level * 8},
                                           "power": 100 + level * 20} for level in range(1, 11)]},
                     "cohorts": cohorts, "simulation": {"days": days, "samples": 400, "seed": 2026},
                     "targets": [{"cohort": "regular", "p50_day_min": 14, "p50_day_max": 21, "min_completion_rate": 0.9}],
                     "assumptions": ["가상 예제: 수치·가격·플레이 패턴은 실측이나 업계 기준이 아닙니다.",
                                     "매일 독립적으로 접속 여부를 추첨하며, 보상·입장권의 보유 상한과 소멸은 없습니다.",
                                     "재화가 모이면 확정 성장하며, 전투력은 표시용이고 클리어율은 난이도별 고정 입력입니다.",
                                     "외부 일일 수입·소모·예약 구매는 미접속일에도 처리합니다. 패스는 1일차 일괄 지급 가정입니다."]})
