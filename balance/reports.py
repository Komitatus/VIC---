"""Excel용 CSV와 네트워크 없이 열리는 HTML 보고서."""

import csv
import html
import json
from pathlib import Path


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def csv_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: csv_cell(row.get(key, "")) for key in fields})


def fmt(value):
    if value is None:
        return "기간 내 미도달"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def table(headers, rows):
    return "<div class='table-wrap'><table><thead><tr>" + "".join(f"<th>{html.escape(str(v))}</th>" for v in headers) + "</tr></thead><tbody>" + "".join(
        "<tr>" + "".join(f"<td>{html.escape(fmt(value))}</td>" for value in row) + "</tr>" for row in rows) + "</tbody></table></div>"


def chart(result):
    palette = ["#67e8c3", "#7ba9ff", "#eec676", "#ef94d3", "#e49a79", "#b0a2f8"]
    days = result["simulation"]["days"]
    svg = ["<svg viewBox='0 0 880 255' role='img' aria-label='코호트별 목표 도달률 추이'>"]
    for percentage in (0, 25, 50, 75, 100):
        y = 215 - percentage * 1.8
        svg.append(f"<line x1='60' y1='{y}' x2='850' y2='{y}' stroke='#2a3b48'/><text x='10' y='{y+5}' fill='#aabac7'>{percentage}%</text>")
    for day in sorted({1, max(1, days // 2), days}):
        x = 60 + (day - 1) / max(1, days - 1) * 790
        svg.append(f"<text x='{x}' y='244' text-anchor='middle' fill='#aabac7'>{day}일</text>")
    legend = []
    for index, cohort in enumerate(result["cohorts"]):
        color = palette[index % len(palette)]
        points = " ".join(f"{60+(row['day']-1)/max(1,days-1)*790:.2f},{215-row['reached']*180:.2f}" for row in cohort["daily"])
        svg.append(f"<polyline points='{points}' fill='none' stroke='{color}' stroke-width='3'/>")
        legend.append(f"<span style='color:{color}'>● {html.escape(cohort['name'])}</span>")
    return "".join(svg) + "</svg><div class='legend'>" + " ".join(legend) + "</div>"


def document(title, body):
    return """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>""" + html.escape(title) + """</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0c151e;color:#e8f0f5;font-family:system-ui,'Malgun Gothic',sans-serif;line-height:1.65}main{max-width:1160px;margin:auto;padding:48px 28px 80px}h1{font-size:32px;letter-spacing:-1px;margin:12px 0}h2{font-size:20px;margin:0 0 16px}.eyebrow{color:#67e8c3;letter-spacing:3px;font-size:12px}section,.intro{background:#111f2b;border:1px solid #293b49;border-radius:14px;padding:24px;margin:24px 0}.muted,small{color:#a8b8c5}.badge{display:inline-block;border:1px solid #70848f;border-radius:24px;padding:5px 14px}.pass{color:#67e8c3}.needs_tuning{color:#eec676}.table-wrap{overflow:auto}table{width:100%;border-collapse:collapse;font-size:14px}th,td{text-align:left;border-bottom:1px solid #293b49;padding:12px;white-space:nowrap}th{color:#a8b8c5;font-weight:500}svg{width:100%;max-height:300px}.legend{display:flex;gap:24px;flex-wrap:wrap}li{margin:9px 0}code{word-break:break-all;color:#b9c7d2;font-size:12px}a{color:#67e8c3}@media(max-width:640px){main{padding:24px 12px}section,.intro{padding:16px}h1{font-size:26px}}@media print{body{background:white;color:black}section,.intro{background:white;border-color:#ccc}th,small,.muted{color:#444}}
</style></head><body><main><div class="eyebrow">CONTENT BALANCE / DESIGN LAB</div><h1>""" + html.escape(title) + "</h1>" + body + "</main></body></html>"


def export_report(directory, model, result):
    directory = Path(directory)
    write_json(directory / "입력_스냅샷.json", model)
    write_json(directory / "결과.json", result)
    reward_rows = []
    for stage in model["content"]["stages"]:
        for index, reward in enumerate(stage["rewards"]):
            reward_rows.append({"stage_id": stage["id"], "kind": "repeat", "row": index,
                                "min_level": stage["min_level"], "minutes": stage["minutes"],
                                "clear_rate": stage["clear_rate"], **reward})
        for currency, amount in stage["first_clear"].items():
            reward_rows.append({"stage_id": stage["id"], "kind": "first_clear", "currency": currency,
                                "amount": amount, "probability": 1, "group": ""})
    write_csv(directory / "보상표.csv", reward_rows,
              ["stage_id", "kind", "row", "min_level", "minutes", "clear_rate", "currency", "amount", "probability", "group"])
    growth_rows, cumulative = [], {row["id"]: 0 for row in model["currencies"]}
    for step in model["growth"]["steps"]:
        for currency in cumulative:
            amount = step["cost"].get(currency, 0)
            cumulative[currency] += amount
            growth_rows.append({"level": step["level"], "power": step["power"], "currency": currency,
                                "cost": amount, "cumulative_cost": cumulative[currency]})
    write_csv(directory / "성장표.csv", growth_rows, ["level", "power", "currency", "cost", "cumulative_cost"])
    write_csv(directory / "보상_기대값.csv", result["reward_expectations"],
              ["stage", "currency", "per_clear", "per_attempt", "per_minute", "first_clear"])
    summaries, daily_rows, economy = [], [], []
    for cohort in result["cohorts"]:
        summaries.append({"cohort": cohort["id"], "name": cohort["name"], "reach_rate": cohort["reach_rate"],
                          **cohort["target_days"], "final_level_mean": cohort["final_level_mean"],
                          "attempts_mean": cohort["attempts_mean"], "clears_mean": cohort["clears_mean"],
                          "minutes_mean": cohort["minutes_mean"], "spent_krw_mean": cohort["spent_krw_mean"]})
        for row in cohort["daily"]:
            for currency in model["currencies"]:
                cid = currency["id"]
                daily_rows.append({"cohort": cohort["id"], **row, "currency": cid,
                                   "wallet": row["wallet"][cid], "shortage": row["shortage"][cid]})
        for currency in model["currencies"]:
            cid = currency["id"]
            source = next(c for c in model["cohorts"] if c["id"] == cohort["id"])
            economy.append({"cohort": cohort["id"], "currency": cid, "initial": source["initial_wallet"].get(cid, 0),
                            **{key: value[cid] for key, value in cohort["flows"].items()}, "final": cohort["wallet_mean"][cid]})
    write_csv(directory / "코호트_요약.csv", summaries,
              ["cohort", "name", "reach_rate", "p10", "p50", "p90", "final_level_mean", "attempts_mean", "clears_mean", "minutes_mean", "spent_krw_mean"])
    write_csv(directory / "일별_추이.csv", daily_rows,
              ["cohort", "day", "level", "power", "active", "attempts", "clears", "minutes", "reached", "currency", "wallet", "shortage"])
    economy_fields = ["cohort", "currency", "initial", "external_income", "purchase_income", "content_income", "entry_cost", "growth_cost", "other_sink", "unpaid_sink", "final"]
    write_csv(directory / "재화_수급.csv", economy, economy_fields)
    labels = {"pass": "입력 목표 충족", "needs_tuning": "밸런스 조정 필요", "no_targets": "목표 기준 미설정"}
    body = f"<div class='intro'><span class='badge {result['status']}'>{labels[result['status']]}</span><p>{result['simulation']['days']}일 · 코호트별 {result['simulation']['samples']:,}명 모의 실행 · 시드 {result['simulation']['seed']}</p><p class='muted'>입력 가정에 따른 수치 검증입니다. 실제 서비스 적합성이나 에이전트 검토 승인을 뜻하지 않습니다.</p><small>입력 SHA-256 <code>{result['model_hash']}</code></small></div>"
    body += "<section><h2>목표 성장 단계 도달</h2>" + table(
        ["유형", "도달률", "p10 (일)", "p50 (일)", "p90 (일)", "최종 평균 단계", "평균 플레이 분"],
        [[c["name"], f"{c['reach_rate']:.1%}", *c["target_days"].values(), c["final_level_mean"], c["minutes_mean"]] for c in result["cohorts"]])
    body += "<p class='muted'>분위수는 미도달자까지 포함합니다. ‘기간 내 미도달’은 해당 분위수가 시뮬레이션 기간 밖이라는 뜻입니다.</p></section>"
    body += "<section><h2>일별 누적 도달률</h2>" + chart(result) + "</section>"
    body += "<section><h2>목표 판정</h2>" + (table(["코호트", "목표 p50 기간", "실제 p50", "최소 도달률", "실제 도달률", "판정"],
        [[c["cohort"], f"{c['target']['p50_day_min']}~{c['target']['p50_day_max']}일", c["actual_p50"], f"{c['target']['min_completion_rate']:.0%}", f"{c['actual_reach_rate']:.1%}", "충족" if c["passed"] else "조정 필요"] for c in result["checks"]]) if result["checks"] else "<p>targets에 목표를 설정하세요.</p>") + "</section>"
    body += "<section><h2>기간 누적 재화 수급 / 유저 1명 평균</h2>" + table(
        ["코호트", "재화", "시작", "외부 수입", "구매 지급", "콘텐츠 보상", "입장 소모", "성장 소모", "기타 소모", "미지불 소모", "최종 잔액"],
        [[row[field] for field in economy_fields] for row in economy]) + "</section>"
    body += "<section><h2>검토할 항목</h2><ul>" + "".join(f"<li>{html.escape(w)}</li>" for w in result["warnings"]) + "</ul><h2>가정과 적용 범위</h2><ul>" + "".join(f"<li>{html.escape(w)}</li>" for w in result["assumptions"]) + "</ul><p class='muted'>확률 강화·천장·중복 보유·거래소·PvP·유저별 이탈은 이 계산기에 포함되지 않습니다. 보상 기대값 CSV는 코호트 보정 전, 최초 보상 제외 기준입니다.</p></section>"
    body += "<p class='muted'>보상표.csv · 성장표.csv · 보상_기대값.csv · 코호트_요약.csv · 일별_추이.csv · 재화_수급.csv · 입력_스냅샷.json · 결과.json</p>"
    title = f"{model['game']} / {model['content']['name']}"
    if any("가상 예제" in assumption for assumption in result["assumptions"]):
        title = "가상 예제 · " + title
        body = "<div class='intro'><strong>계산기 검증용 가상 예제</strong><p>실제 게임의 분석 결과가 아닙니다. 보상·비용·이용 패턴은 예제용 입력입니다.</p></div>" + body
    (directory / "리포트.html").write_text(document(title, body), encoding="utf-8")


def export_comparison(directory, comparison):
    write_json(Path(directory) / "비교.json", comparison)
    write_csv(Path(directory) / "전후_비교.csv", comparison["rows"],
              ["cohort", "change", "baseline_p50", "candidate_p50", "p50_delta_days", "reach_rate_delta_pp", "final_level_delta", "minutes_delta"])
    rows = []
    for row in comparison["rows"]:
        if row["change"] != "compared":
            rows.append([row["cohort"], row["change"], "—", "—", "계산 불가", "계산 불가", "계산 불가"])
        else:
            rows.append([row["cohort"], row["change"], row["baseline_p50"], row["candidate_p50"],
                         row["p50_delta_days"] if row["p50_delta_days"] is not None else "계산 불가",
                         row["reach_rate_delta_pp"], row["final_level_delta"]])
    body = "<p class='muted'>변경안 − 기준안. 도달률 차이는 %p, 기간 차이는 일입니다. 미도달을 0일로 계산하지 않습니다. 새 코호트·제거한 코호트에는 차이를 계산하지 않습니다.</p>"
    body += table(["코호트", "상태", "기준 p50", "변경 p50", "기간 차이", "도달률 차이 (%p)", "최종 단계 차이"], rows)
    body += "<p><a href='기준안/리포트.html'>기준안 상세</a> · <a href='변경안/리포트.html'>변경안 상세</a></p>"
    (Path(directory) / "비교.html").write_text(document("콘텐츠 밸런스 · 변경 전후 비교", body), encoding="utf-8")
