"""Source-backed static cost analysis, separate from the cohort simulator."""
from __future__ import annotations

import csv
import hashlib
import html
import json
import math
from pathlib import Path
import sqlite3
import struct


def sha(path: Path) -> str:
    with path.open("rb") as source:
        digest = hashlib.sha256()
        for block in iter(lambda: source.read(1048576), b""):
            digest.update(block)
        return digest.hexdigest()


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def echo_costs(levels: list[dict], quality: dict, coin_rate: int,
               exp_return: int, tuner_return: int) -> list[dict]:
    """Rates have the client's per-1000 unit. No substat probability model."""
    maximum = quality["LevelLimit"]
    by_level = {r["Level"]: r["Exp"] for r in levels}
    if len(by_level) != len(levels) or any(i not in by_level for i in range(maximum + 1)):
        raise ValueError("Incomplete or duplicate echo level curve")
    if any(x < 0 for x in by_level.values()) or not 0 <= exp_return <= 1000 or not 0 <= tuner_return <= 1000:
        raise ValueError("Invalid cost or refund rate")
    tuner_id, tuner_count = next(iter(quality["IdentifyCost"].items()))
    if len(quality["IdentifyCost"]) != 1:
        raise ValueError("Multiple tuning currencies need an explicit model")
    total = sum(by_level[i] for i in range(1, maximum + 1))
    rows, previous = [], 0
    for level in quality["SlotUnlockLevel"]:
        exp = sum(by_level[i] for i in range(1, level + 1))
        slots = sum(i <= level for i in quality["SlotUnlockLevel"])
        tuners = slots * tuner_count
        coins = (exp * coin_rate + 999) // 1000
        refunded_exp = exp * exp_return // 1000
        refunded_tuners = tuners * tuner_return // 1000
        rows.append(dict(level=level, cumulative_exp=exp, incremental_exp=exp-previous,
                         incremental_share=(exp-previous)/total, level_coins=coins,
                         tuning_coins=slots*quality["IdentifyCoin"],
                         total_coins=coins+slots*quality["IdentifyCoin"],
                         tuners=tuners, tuner_item_id=int(tuner_id),
                         refunded_exp=refunded_exp, lost_exp=exp-refunded_exp,
                         refunded_tuners=refunded_tuners, lost_tuners=tuners-refunded_tuners))
        previous = exp
    return rows


class Evidence:
    def __init__(self, tables: Path, extracted: Path, extraction_manifest: Path):
        self.tables, self.extracted = tables, extracted
        self.table_manifest = json.loads((tables / "해석_명세.json").read_text(encoding="utf-8"))
        self.extraction = json.loads(extraction_manifest.read_text(encoding="utf-8"))
        self.file_records = {r["entry"]: r for r in self.extraction}
        self.used = {}
        for relative, digest in self.table_manifest["schemas"].items():
            self.verify(self.extracted / "JavaScript" / relative, digest)

    def verify(self, path: Path, expected: str | None = None):
        path = path.resolve()
        digest = sha(path)
        if expected and digest != expected:
            raise ValueError(f"Evidence hash mismatch: {path}")
        self.used[str(path)] = digest
        return digest

    def source(self, relative: str) -> Path:
        path = (self.extracted / relative).resolve()
        entry = "Client/Content/Aki/" + relative
        record = self.file_records[entry]
        self.verify(path, record["sha256"])
        return path

    def load(self, name: str) -> list[dict]:
        record = next(r for r in self.table_manifest["tables"] if r["table"] == name)
        if record["status"] != "client_table_verified":
            raise ValueError(f"Unverified table: {name}")
        self.verify(self.tables / (name + ".json"), record["sha256"])
        self.verify(self.extracted / "ConfigDB" / record["database"], record["source_sha256"])
        self.source("JavaScript/Core/Define/Config/" + record["schema"])
        return json.loads((self.tables / (name + ".json")).read_text(encoding="utf-8"))


def csv_rows(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                         for k, v in r.items()} for r in rows)


def run_analysis(tables: Path, extracted: Path, manifest: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError("Use a new output directory")
    evidence = Evidence(tables, extracted, manifest)
    game_root = Path(evidence.extraction[0]["package"]).parents[3]
    version_file = game_root / "launcherDownloadConfig" / "common.json"
    evidence.verify(version_file)
    build = json.loads(version_file.read_text(encoding="utf-8"))["version"]
    for package in sorted({r["package"] for r in evidence.extraction}):
        evidence.verify(Path(package))
    common_path = evidence.source("ConfigDB/db_common_param.db")
    source_methods = {
        "PhantomLevelUpCoinCost": "Module/Phantom/PhantomBattle/PhantomBattleConfig.js",
        "PhantomExpReturnRatio": "Module/Phantom/PhantomBattle/Data/PhantomDataBase.js",
        "PhantomIdentifyReturnRatio": "Module/Phantom/PhantomBattle/Data/PhantomDataBase.js",
        "ExpConversionCount": "Module/RoleUi/RoleModel.js",
        "WeaponLevelUpCoinCost": "Module/Weapon/WeaponConfig.js",
        "renew_energy_timespan": "Module/Power/PowerConfig.js",
        "renew_energy_limit": "Module/Power/PowerConfig.js",
    }
    params = {}
    with sqlite3.connect(common_path.as_uri() + "?mode=ro", uri=True) as db:
        for key, relative in source_methods.items():
            source = evidence.source("JavaScript/Game/" + relative)
            if f'GetIntConfig("{key}")' not in source.read_text(encoding="utf-8"):
                raise ValueError(f"Parameter type not confirmed: {key}")
            row = db.execute("select BinData from commonparam where KeyName=?", (key,)).fetchone()
            if not row or len(row[0]) < 4:
                raise ValueError(f"Missing parameter: {key}")
            params[key] = {"value": struct.unpack_from("<i", row[0])[0],
                           "database": "db_common_param.db", "table": "commonparam",
                           "row": key, "reader": str(source), "decoder": "ParseInt: little-endian i32 at offset 0"}
    evidence.source("JavaScript/Core/Config/DeserializeConfig.js")
    evidence.source("JavaScript/Game/GameUtils.js")
    evidence.source("JavaScript/Game/Module/Weapon/Data/WeaponDataBase.js")
    evidence.source("JavaScript/Game/Module/RoleUi/RoleData/Module/RoleLevelData.js")
    evidence.source("JavaScript/Game/Module/Power/PowerData.js")
    p = {k: v["value"] for k, v in params.items()}
    quality = next(r for r in evidence.load("phantomquality") if r["Quality"] == 5)
    groups = {r["LevelUpGroupId"] for r in evidence.load("phantomitem") if r["QualityId"] == 5}
    if len(groups) != 1:
        raise ValueError("Gold echo level groups differ; choose an explicit item")
    group = next(iter(groups))
    levels = [r for r in evidence.load("phantomlevel") if r["GroupId"] == group]
    echo = echo_costs(levels, quality, p["PhantomLevelUpCoinCost"], p["PhantomExpReturnRatio"], p["PhantomIdentifyReturnRatio"])
    exp_items = evidence.load("phantomexpitem")
    top_exp = next(r["Exp"] for r in exp_items if r["ItemId"] == 36000004)
    lang_path = evidence.source("ConfigDB/ko/lang_multi_text.db")
    lang = sqlite3.connect(lang_path.as_uri() + "?mode=ro", uri=True)

    def name(key):
        row = lang.execute("select Content from MultiText where Id=?", (key,)).fetchone()
        return row[0] if row and row[0] else key

    items = {r["Id"]: r for r in evidence.load("iteminfo")}
    item_names = {str(k): name(v["Name"]) for k, v in items.items()}
    roles = evidence.load("roleinfo")
    role_levels = evidence.load("rolelevelconsume")
    role_breaches = evidence.load("rolebreach")
    role = next(r for r in roles if r["Id"] == 1202)
    role_curve = [r for r in role_levels if r["ConsumeGroupId"] == role["LevelConsumeId"]]
    role_total = sum(r["ExpCount"] for r in role_curve if 1 < r["Level"] <= 90)
    role_breach = sum(r["BreachConsume"].get("2", 0) for r in role_breaches if r["BreachGroupId"] == role["BreachId"] and 1 <= r["BreachLevel"] <= 6)
    weapon = next(r for r in evidence.load("weaponconf") if r["ItemId"] == 21010015)
    weapon_total = sum(r["Exp"] for r in evidence.load("weaponlevel") if r["LevelId"] == weapon["LevelId"] and 1 <= r["Level"] < 90)
    weapon_breach = sum(r["GoldConsume"] for r in evidence.load("weaponbreach") if r["BreachId"] == weapon["BreachId"] and 0 <= r["Level"] < 6)
    costs = [
        {"target": name(role["Name"]) + " 1→90", "id": role["Id"], "exp": role_total,
         "level_coins": (role_total*p["ExpConversionCount"]+999)//1000, "breach_coins": role_breach,
         "scope": "레벨·돌파 코인; 스킬·돌파 재료 제외"},
        {"target": name(weapon["WeaponName"]) + " 1→90", "id": weapon["ItemId"], "exp": weapon_total,
         "level_coins": (weapon_total*p["WeaponLevelUpCoinCost"]+999)//1000, "breach_coins": weapon_breach,
         "scope": "레벨·돌파 코인; 돌파 재료·공명 제외"},
    ]
    for c in costs:
        c["total_coins"] = c["level_coins"] + c["breach_coins"]

    exchanges = evidence.load("exchangereward")
    packages = {r["Id"]: r for r in evidence.load("droppackage")}
    areas, rewards = [], []
    for area in evidence.load("silentareadetection"):
        title = name(area["Name"])
        if "무음구역" not in title:
            continue
        candidates = [r for r in exchanges if r["RewardId"] and r["RewardId"] == area["ShowRewardMap"]]
        for exchange in candidates:
            areas.append({"detection_id": area["Id"], "name": title, "exchange_id": exchange["Id"],
                          "cost": exchange["Cost"], "preview_ids_by_stage": area["ShowRewardMap"],
                          "link_method": "identical_reward_map (inference, not a direct foreign key)"})
            if area["Id"] == 30010001:
                for stage, rid in area["ShowRewardMap"].items():
                    for item, qty in packages[rid]["DropPreview"].items():
                        rewards.append({"stage_key": stage, "drop_package_id": rid,
                                        "item_id": int(item), "item_name": item_names.get(item, "미해석 에코 미리보기 ID"),
                                        "preview_quantity": qty, "actual_expected_quantity": None,
                                        "status": "client_preview_only"})
    selected = next(r for r in areas if r["detection_id"] == 30010001)
    wave_cost = selected["cost"]["5"]
    daily = 86400 / p["renew_energy_timespan"]
    maximum = echo[-1]
    unresolved = [
        "DropPreview의 0은 실제 지급 0으로 해석하지 않음. 무음구역 재료별 지급 분포·평균은 미확인.",
        "부옵션 추첨 가중치·목표 옵션 성공률·서버 보정 미확인. 종결 파밍 기대 횟수와 p50/p90 미산출.",
        "보상맵 일치로 콘텐츠와 ExchangeReward를 연결함. 런타임 서버 보상·핫픽스와의 일치 여부는 미검증.",
        "게임 내 실측 로그, 플레이 시간, 이벤트·상점·퀘스트 공급량을 수집하지 않음.",
    ]
    assumptions = [
        "경험치 0에서 정확한 필요 경험치만 투입하는 비용 기준. 재료 단위 초과 투입·전투 경험치 제외.",
        "해당 레벨의 모든 부옵션 슬롯을 튜닝한 뒤 재료로 소비할 때의 경험치·튜너 환급 계산.",
        "하루 행동력 240은 24시간 자연 회복을 손실 없이 수령한 경우. 다른 콘텐츠 소비·충전·저장 행동력 제외.",
        "비용 표는 전투 효율 평가가 아님. 마지막 5레벨의 주옵션 증가와 빌드별 가치는 별도 평가 필요.",
        "성장 해금 조건을 충족한 상태의 자원 비용이다. 계정 레벨·퀘스트 선행 조건에 따른 대기 기간은 제외.",
    ]
    inputs = {"format": "wuwa_static_analysis_v1", "build": build, "scope": "중부 평원 무음구역 → 5성 에코 성장",
              "source_files": evidence.used, "parameters": params, "echo_group": group, "source_root": str(game_root),
              "tools": {str(f): sha(f) for f in [Path(__file__), Path(__file__).with_name("wuwa_pak.py"), Path(__file__).parents[1]/"도구/명조_DB해석.cjs"]},
              "assumptions": assumptions, "unresolved": unresolved}
    result = {"format": "wuwa_static_analysis_v1", "status": "analyzed_partial", "echo_checkpoints": echo,
              "full_set_5": {"exp": maximum["cumulative_exp"]*5, "coins": maximum["total_coins"]*5, "tuners": maximum["tuners"]*5},
              "top_echo_exp_item": {"id": 36000004, "exp": top_exp, "items_for_one_echo_ceiling": math.ceil(maximum["cumulative_exp"]/top_exp)},
              "other_growth": costs, "content_links": areas, "preview_rewards": rewards,
              "natural_power": {"seconds_per_unit": p["renew_energy_timespan"], "cap": p["renew_energy_limit"],
                                "per_day": daily, "matched_exchange_cost": wave_cost, "max_runs_per_day_if_all_allocated": daily/wave_cost},
              "supply_ratio_diagnostics": {"one_retained_echo_xp_per_tuner": maximum["cumulative_exp"]/maximum["tuners"],
                                           "failed_full_echo_net_xp_per_net_tuner": maximum["lost_exp"]/maximum["lost_tuners"]},
              "unresolved": unresolved, "assumptions": assumptions}
    output.mkdir(parents=True)
    write_json(output / "분석입력.json", inputs)
    result["input_sha256"] = sha(output / "분석입력.json")
    write_json(output / "결과.json", result)
    csv_rows(output / "에코_성장과환급.csv", echo)
    csv_rows(output / "캐릭터_무기_비용.csv", costs)
    csv_rows(output / "무음구역_연결.csv", areas)
    csv_rows(output / "중부평원_보상미리보기.csv", rewards)
    write_json(output / "파밍설계_입력.json", {
        "format": "wuwa_content_design_v1", "content_id": selected["detection_id"], "name": selected["name"],
        "source_analysis_sha256": sha(output / "결과.json"), "waveplate_cost": wave_cost,
        "growth_cost_csv": "에코_성장과환급.csv", "expected_exp_per_claim": None, "expected_tuners_per_claim": None,
        "substat_acceptance_probability": None, "clear_minutes": None, "target_days": None,
        "status": "awaiting_verified_yields", "reason": "실제 지급량·분포를 확인한 뒤 기간 모델을 작성한다. null은 0이 아니다."})
    render_report(output, result, inputs)
    lang.close()
    return result


def render_report(output: Path, result: dict, inputs: dict) -> None:
    rows = result["echo_checkpoints"]
    fmt = lambda n: f"{n:,}"
    last = rows[-1]
    checkpoint_md = "\n".join(f"| +{r['level']} | {fmt(r['cumulative_exp'])} | {fmt(r['incremental_exp'])} | {fmt(r['total_coins'])} | {r['tuners']} | {fmt(r['lost_exp'])} | {r['lost_tuners']} |" for r in rows)
    other_md = "\n".join(f"| {r['target']} | {fmt(r['exp'])} | {fmt(r['level_coins'])} | {fmt(r['breach_coins'])} | {fmt(r['total_coins'])} |" for r in result["other_growth"])
    limitations = "\n".join("- " + s for s in result["unresolved"])
    assumptions = "\n".join("- " + s for s in result["assumptions"])
    md = f"""# 명조 {inputs['build']} — 무음구역 보상과 에코 성장 분석

설치 경로 `{inputs['source_root']}`의 PAK에서 추출한 DB와 같은 빌드의 JavaScript 정의를 사용했다. 게임 실행·설치파일 수정 없이 읽었다. 버전 근거는 `launcherDownloadConfig/common.json`이다.

주 분석 범위는 **중부 평원 · 무음구역 → 5성 에코 성장**이다. 캐릭터·무기는 연결 재화인 클램 코인의 경쟁 소비를 확인하는 비교 사례다. 확정 비용 분석은 완료했고, 실제 보상 분포와 확률 성장 기간은 미확인으로 남겼다.

## 확정된 성장 비용

5성 에코 +25 한 개는 경험치 **{fmt(last['cumulative_exp'])}**, 레벨업 코인 **{fmt(last['level_coins'])}**, 튜닝 코인 **{fmt(last['tuning_coins'])}**, 특급 튜너 **{last['tuners']}개**가 필요하다. 다섯 슬롯을 모두 채운 경우다. 5개 세트는 경험치 {fmt(result['full_set_5']['exp'])}, 코인 {fmt(result['full_set_5']['coins'])}, 튜너 {result['full_set_5']['tuners']}개다.

| 목표 레벨 | 누적 경험치 | 직전 5레벨 비용 | 코인 합계 | 누적 튜너 | 재료 소비 후 경험치 순손실 | 튜너 순손실 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
{checkpoint_md}

+20→+25의 경험치 {fmt(last['incremental_exp'])}는 전체의 **{last['incremental_share']:.2%}**다. 비용이 후반에 집중된다. 이 수치는 투자 비중이며, 해당 구간의 주옵션 성장까지 고려한 전투 효율을 뜻하지 않는다.

근거: `PhantomItem.QualityId=5 → LevelUpGroupId=4 → PhantomLevel.GroupId=4`, `PhantomQuality.Quality=5`의 LevelLimit·SlotUnlockLevel·IdentifyCost·IdentifyCoin. `PhantomBattleConfig.GetPhantomLevelUpCostRatio`는 CommonParam `PhantomLevelUpCoinCost=100`을 1,000으로 나눈다. 경험치 재료 `PhantomExpItem.ItemId=36000004`는 5,000 EXP이므로 단일 등급만 쓰면 29개가 필요하지만, 2,400 EXP 초과분 처리는 이 비용 기준에 포함하지 않았다.

## 환급과 반복 투자

`PhantomDataBase.GetEatFullExp`는 누적 경험치의 75%를 내림하고, `GetIdentifyBackItem`은 사용 튜너의 30%를 내림한다. +25 실패품 한 개를 재료로 쓰면 경험치 {fmt(last['refunded_exp'])}, 튜너 {last['refunded_tuners']}개가 돌아와 순손실은 {fmt(last['lost_exp'])} EXP와 {last['lost_tuners']}개다. 표의 코인은 선행 지출액이다. 별도의 코인 환급 규칙은 이 분석에서 확인하지 않았다.

확정 완성품 한 개의 투입비는 튜너 1개당 {result['supply_ratio_diagnostics']['one_retained_echo_xp_per_tuner']:,.0f} EXP지만, +25 실패품의 환급 후 순손실비는 약 {result['supply_ratio_diagnostics']['failed_full_echo_net_xp_per_net_tuner']:,.2f} EXP다. +5 선별 반복의 순손실비는 약 {rows[0]['lost_exp']/rows[0]['lost_tuners']:,.2f} EXP로, 경험치 대비 튜너의 상대 소모 비중이 더 높다. 따라서 콘텐츠 보상 비율을 설계할 때 완성 비용만 맞추면 선별 반복 행동을 반영하지 못한다. 실제 합격률 없이 평균 반복 횟수를 정하지 않았다.

## 콘텐츠 보상 연결

`SilentAreaDetection.Id=30010001`의 ShowRewardMap과 `ExchangeReward.Id=14001001`의 RewardId 맵이 일치한다. 이 **보상맵 일치에 따른 연결**에서 행동력 재화 ID 5 비용은 60이다. {len(result['content_links'])}개 무음구역의 같은 방식 연결을 CSV에 기록했다. 런타임 지급 경로를 직접 검증한 외래키 관계는 아니다.

`DropPackage.Id=14008` 미리보기에는 특급 비밀음파 통(ID 36000004)과 특급 튜너(ID 36000014)가 있지만 수량은 모두 0이다. 이는 **실제 지급 0이나 드롭 확률 0으로 사용할 수 없는 값**이다. 보상 종류는 확인되지만, 1회 평균 EXP·튜너 수급량 및 파밍 일수는 계산하지 않았다.

`PowerConfig`와 CommonParam에서 자연 회복은 360초마다 1, 상한은 240이다. 손실 없는 24시간 회복은 240이며 모두 이 비용 60 콘텐츠에 배정하면 하루 4회분이다. 이는 행동력 예산이며 성장 완료 일수가 아니다.

## 연결 재화의 경쟁 소비

| 대상 | 레벨 경험치 | 레벨업 코인 | 돌파 코인 | 코인 합계 |
| --- | ---: | ---: | ---: | ---: |
{other_md}

치샤는 RoleInfo 1202 → LevelConsumeId 10002, BreachId 1202를 사용한다. RoleLevelData가 다음 레벨 행을 읽으므로 2~90행 ExpCount를 합쳤다. RoleModel.GetMoneyToLevelUp은 `ceil(EXP × ExpConversionCount / 1000)`, 이 설치본의 ExpConversionCount는 350이다. 무기는 WeaponConf 21010015 → LevelId 5와 BreachId 21010015를 연결했다. WeaponDataBase.GetLastLevelMaxExp에 맞춰 1~89행을 합쳤고 레벨업 코인 비율은 400/1000이다. 스킬·공명·돌파 재료는 합계에서 제외했다.

## 설계에 적용할 판단

- +20 이후 경험치 비용을 독립 구간으로 관리한다. 구간 비용을 낮추면 경험치 소비가 줄어드는 만큼 반복 도전이 늘어 튜너 수요가 바뀔 수 있다.
- 경험치와 튜너 보상은 함께 검토한다. +5/+10 선별, 완성 후 교체 등 실제 행동 비중을 먼저 측정한다.
- 행동력 단가 60에서 지급량을 바꾸려면 우선 회차별 지급 로그를 확보한다. `파밍설계_입력.json`의 미확인 지급량은 null로 유지했다.
- 부옵션 가중치·성공률·보정 자료가 확인되기 전에는 일반 확정 성장 시뮬레이터에 대입하지 않는다.

## 조건과 남은 범위

{assumptions}

{limitations}

## 재현과 출처

`분석입력.json`에 사용한 원본 DB·코드·해석 테이블의 경로와 SHA-256을 기록했다. 입력 SHA-256은 `{result['input_sha256']}`이다. `결과.json`, CSV, `검토_1.json`을 함께 보관한다. 데이터 해석 과정은 SQLite의 키 열과 FlatBuffers getter의 동일 필드를 대조했다. 한국어 명칭은 같은 설치본의 ko/lang_multi_text.db에서 읽었다.

추출 형식 참고: [CUE4Parse PAK 구조](https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/UE4/Pak/Objects/FPakEntry.cs), [부분 암호화 처리](https://github.com/FabianFG/CUE4Parse/blob/master/CUE4Parse/GameTypes/Misc/UE4/Paks/PartialEncryptionPakFileReader.cs), [repak 압축 라이브러리 로더](https://github.com/trumank/repak/blob/master/oodle_loader/src/lib.rs), [공개 추출 키 설정](https://github.com/yarik0chka/wuwa-keys). 게임 밸런스 수치의 외부 자료 대체는 하지 않았다.
"""
    (output / "분석보고서.md").write_text(md, encoding="utf-8")
    # Offline, exportable SVG cost chart; no external scripts or requests.
    bars = []
    for i, r in enumerate(rows):
        width = r["cumulative_exp"] / last["cumulative_exp"] * 530
        y = 25 + i * 45
        bars.append(f'<text x="0" y="{y+19}" fill="#dbe6f1">+{r["level"]}</text><rect x="55" y="{y}" width="{width:.1f}" height="28" rx="4" fill="#55c6b0"/><text x="{65+width:.1f}" y="{y+19}" fill="#dbe6f1">{r["cumulative_exp"]:,}</text>')
    table = '<table><tr><th>레벨</th><th>누적 EXP</th><th>코인</th><th>튜너</th><th>환급 후 EXP 손실</th></tr>' + ''.join(f'<tr><td>+{r["level"]}</td><td>{r["cumulative_exp"]:,}</td><td>{r["total_coins"]:,}</td><td>{r["tuners"]}</td><td>{r["lost_exp"]:,}</td></tr>' for r in rows) + '</table>'
    doc = f'''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>명조 보상·성장 분석</title><style>body{{background:#101923;color:#e9eff4;font:16px/1.7 system-ui,sans-serif;max-width:1040px;margin:40px auto;padding:0 24px}}h1{{font-size:32px}}a{{color:#68d9c4}}.stats{{display:flex;gap:24px;flex-wrap:wrap}}.stats p{{background:#1d2d3c;padding:20px;border-radius:12px}}b{{color:#7de5ce}}table{{border-collapse:collapse;width:100%;margin:24px 0}}td,th{{text-align:right;padding:10px;border-bottom:1px solid #354656}}td:first-child,th:first-child{{text-align:left}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:15px/1.8 system-ui}}svg{{width:100%;max-width:760px}}.note{{border-left:4px solid #efc273;padding:12px 20px;background:#292820}}</style><body><p>설치본 {inputs['build']} · 정적 추출 · 검증된 범위 분석</p><h1>무음구역 보상과 5성 에코 성장</h1><div class="stats"><p>+25 경험치<br><b>{last['cumulative_exp']:,}</b></p><p>레벨업 + 튜닝 코인<br><b>{last['total_coins']:,}</b></p><p>튜너 5슬롯<br><b>{last['tuners']}개</b></p></div><h2>누적 성장 비용</h2><svg viewBox="0 0 740 260" role="img" aria-label="에코 목표 레벨별 누적 경험치">{''.join(bars)}</svg>{table}<p>+20→+25에 전체 경험치의 <b>{last['incremental_share']:.2%}</b>가 필요합니다. +25를 재료로 소비할 때 경험치 순손실은 <b>{last['lost_exp']:,}</b>, 튜너 순손실은 <b>{last['lost_tuners']}개</b>입니다.</p><p class="note">보상 미리보기의 재료 수량 0은 실제 지급량으로 사용하지 않았습니다. 성장 비용은 확인했으며, 파밍 일수·부옵션 성공률은 미확인입니다.</p><p><a href="에코_성장과환급.csv">에코 비용 CSV</a> · <a href="캐릭터_무기_비용.csv">다른 성장 비용</a> · <a href="중부평원_보상미리보기.csv">보상 근거</a> · <a href="결과.json">계산 JSON</a> · <a href="분석보고서.md">상세 보고서</a></p><details><summary>전체 근거와 해석 보기</summary><pre>{html.escape(md)}</pre></details></body></html>'''
    (output / "명조_보상성장_분석.html").write_text(doc, encoding="utf-8")
