"""개인 식별자가 없는 일별·코호트별 집계 CSV를 입력 설계와 대조한다."""

from collections import defaultdict
import csv
from datetime import date
import hashlib
import math
from pathlib import Path

from .model import ModelError, require


BASE_METRICS = {"users", "attempts", "clears", "minutes"}
CURRENCY_METRICS = {"reward", "entry_cost", "growth_cost", "other_income", "other_sink"}
FIELDS = ["date", "content_id", "cohort_id", "metric", "currency", "value"]


def inspect_logs(path, model, simulation):
    cohort_ids = {c["id"] for c in model["cohorts"]}
    currencies = {c["id"] for c in model["currencies"]}
    groups = defaultdict(dict)
    accepted = ignored = 0
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == FIELDS, f"로그 CSV 헤더는 이 순서여야 합니다: {','.join(FIELDS)}")
        for line, row in enumerate(reader, start=2):
            require(None not in row and all(v is not None for v in row.values()), f"로그 L{line}: 열 개수가 맞지 않습니다")
            if row["content_id"] != model["content"]["id"]:
                ignored += 1
                continue
            cid, metric, currency = row["cohort_id"], row["metric"], row["currency"]
            require(cid in cohort_ids, f"로그 L{line}: 등록되지 않은 코호트 {cid}")
            require(metric in BASE_METRICS | CURRENCY_METRICS, f"로그 L{line}: 미지원 지표 {metric}")
            require((metric in BASE_METRICS and currency == "") or (metric in CURRENCY_METRICS and currency in currencies),
                    f"로그 L{line}: 통계 지표는 currency를 비우고, 재화 지표는 등록 재화 ID를 쓰세요")
            try:
                parsed_date = date.fromisoformat(row["date"])
                require(parsed_date.isoformat() == row["date"], f"로그 L{line}: 날짜 형식은 YYYY-MM-DD입니다")
                value = float(row["value"])
            except ValueError as error:
                raise ModelError(f"로그 L{line}: 날짜 또는 수량 형식 오류") from error
            require(math.isfinite(value) and value >= 0, f"로그 L{line}: 수량은 유한한 0 이상 숫자여야 합니다")
            if metric in {"users", "attempts", "clears"}:
                require(value.is_integer(), f"로그 L{line}: {metric}는 정수여야 합니다")
            bucket = groups[(row["date"], cid)]
            key = (metric, currency)
            require(key not in bucket, f"로그 L{line}: 같은 날짜·코호트·지표·재화가 중복되었습니다. 먼저 집계하세요")
            bucket[key] = value
            accepted += 1
    require(bool(groups), "대상 콘텐츠에 해당하는 로그가 없습니다")
    by_cohort = defaultdict(lambda: {"days": set(), "metrics": defaultdict(float), "currency": defaultdict(float)})
    for (day, cid), bucket in groups.items():
        missing = [key for key in sorted(BASE_METRICS) if (key, "") not in bucket]
        require(not missing, f"{day} / {cid}: 기본 지표 누락 {missing}")
        users, attempts, clears = (bucket[(key, "")] for key in ("users", "attempts", "clears"))
        require(clears <= attempts, f"{day} / {cid}: 클리어 수가 시도 수보다 큽니다")
        require(users > 0 or all(value == 0 for value in bucket.values()), f"{day} / {cid}: 유저 0명인데 활동 수치가 있습니다")
        require(attempts > 0 or bucket[("minutes", "")] == 0, f"{day} / {cid}: 시도 0회인데 플레이 시간이 있습니다")
        require(clears > 0 or not any(metric == "reward" and value > 0 for (metric, _), value in bucket.items()),
                f"{day} / {cid}: 클리어 0회인데 클리어 보상이 있습니다")
        total = by_cohort[cid]
        total["days"].add(day)
        for (metric, currency), value in bucket.items():
            if metric in BASE_METRICS:
                total["metrics"][metric] += value
            else:
                total["currency"][(metric, currency)] += value

    def divide(a, b):
        return a / b if b else None

    summaries, differences = [], []
    for cid, total in sorted(by_cohort.items()):
        metrics = total["metrics"]
        predicted = next(c for c in simulation["cohorts"] if c["id"] == cid)
        observed = {"clear_rate": divide(metrics["clears"], metrics["attempts"]),
                    "minutes_per_attempt": divide(metrics["minutes"], metrics["attempts"]),
                    "attempts_per_active_user_day": divide(metrics["attempts"], metrics["users"])}
        expected = {"clear_rate": divide(predicted["clears_mean"], predicted["attempts_mean"]),
                    "minutes_per_attempt": divide(predicted["minutes_mean"], predicted["attempts_mean"]),
                    "attempts_per_active_user_day": divide(predicted["attempts_mean"], predicted["active_days_mean"])}
        summaries.append({"cohort": cid, "start_date": min(total["days"]), "end_date": max(total["days"]),
                          "observed_days": len(total["days"]), "active_user_days": metrics["users"],
                          "attempts": metrics["attempts"], "clears": metrics["clears"], "minutes": metrics["minutes"],
                          **observed, "currency_totals": [{"metric": metric, "currency": currency, "amount": amount}
                                                          for (metric, currency), amount in sorted(total["currency"].items())]})
        for metric, value in observed.items():
            reference = expected[metric]
            differences.append({"cohort": cid, "metric": metric, "observed": value, "simulated": reference,
                                "delta": value - reference if value is not None and reference is not None else None})
        for (metric, currency), value in sorted(total["currency"].items()):
            if metric == "reward":
                actual = divide(value, metrics["clears"])
                reference = divide(predicted["flows"]["content_income"][currency], predicted["clears_mean"])
                differences.append({"cohort": cid, "metric": f"reward_per_clear:{currency}", "observed": actual,
                                    "simulated": reference, "delta": actual-reference if actual is not None and reference is not None else None})
    return {"model_hash": simulation["model_hash"], "log_sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
            "accepted_rows": accepted, "other_content_rows_ignored": ignored, "cohorts": summaries, "differences": differences,
            "limitations": ["users는 해당 날짜·코호트의 접속 유저 수입니다. 합계는 유저-일이며 기간 순유저 수가 아닙니다.",
                            "모의 결과 전체 기간과 관측 로그를 단순 대조합니다. 기간·성장 분포·최초 클리어 구성 차이는 자동 보정하지 않습니다.",
                            "로그는 자동으로 모델에 반영하지 않습니다. 큰 차이의 원본·수집 정의를 확인한 뒤 별도 변경안을 만드세요.",
                            "잔존율·매출 인과관계·개인별 성장 도달 기간은 이 집계 로그만으로 검증할 수 없습니다."]}
