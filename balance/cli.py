"""콘텐츠 등록, 검증, 계산, 비교, 로그 대조 명령."""

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile

from .engine import compare, simulate
from .model import ModelError, example, fingerprint, load_model, require
from .reports import document, export_comparison, export_report, table, write_csv, write_json
from .telemetry import inspect_logs


ROOT = Path(__file__).resolve().parent.parent


def safe_name(value):
    require(value == value.strip() and bool(value), "폴더 이름은 비어 있거나 앞뒤 공백이 있으면 안 됩니다")
    require(not re.search(r'[<>:"/\\|?*\x00-\x1f]', value) and not value.endswith(".") and value not in (".", ".."),
            f"폴더 이름에 사용할 수 없는 문자: {value!r}")
    require(not re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", value), "Windows 예약 파일 이름은 사용할 수 없습니다")
    require(not value.startswith("_") and len(value) <= 80, "폴더 이름은 밑줄로 시작할 수 없고 80자 이하여야 합니다")
    return value


@contextmanager
def fresh_output(destination):
    """결과를 임시 폴더에 완성한 뒤 새 목적지로 이동. 기존 회차는 덮어쓰지 않는다."""
    destination = Path(destination).absolute()
    require(not destination.exists(), f"이미 존재하는 경로입니다: {destination}. 새 회차 경로를 사용하세요")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".balance-", dir=destination.parent))
    try:
        yield temporary
        destination.mkdir()  # 마지막 순간에도 기존 경로를 교체하지 않는다.
        try:
            for child in temporary.iterdir():
                shutil.move(str(child), destination / child.name)
        except Exception:
            shutil.rmtree(destination)
            raise
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def default_output(model_path, kind):
    return Path(model_path).resolve().parent / "결과" / (datetime.now().strftime("%Y%m%d_%H%M%S_%f") + "_" + kind)


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def brief(result):
    return {"status": result["status"], "model_hash": result["model_hash"],
            "cohorts": [{"id": c["id"], "reach_rate": c["reach_rate"], "target_days": c["target_days"]} for c in result["cohorts"]],
            "warnings": result["warnings"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="콘텐츠 전용 보상·성장 밸런스 도구 (Python 3.10+)")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="콘텐츠 등록; 가상 프리셋 생성")
    init.add_argument("--game", required=True)
    init.add_argument("--content", required=True)
    init.add_argument("--preset", choices=("daily", "raid", "event"), default="daily")
    init.add_argument("--root", type=Path, default=ROOT / "콘텐츠")
    check = commands.add_parser("validate", help="모델 형식·참조·확률 검증")
    check.add_argument("model", type=Path)
    run = commands.add_parser("simulate", help="모의 계산과 CSV·HTML 생성")
    run.add_argument("model", type=Path)
    run.add_argument("--out", type=Path)
    run.add_argument("--strict", action="store_true", help="목표 미설정·미충족이면 결과 생성 후 종료 코드 2")
    diff = commands.add_parser("compare", help="동일 게임·콘텐츠 변경 전후 재계산")
    diff.add_argument("baseline", type=Path)
    diff.add_argument("candidate", type=Path)
    diff.add_argument("--out", type=Path)
    logs = commands.add_parser("logs", help="집계 로그와 모의 결과 대조")
    logs.add_argument("model", type=Path)
    logs.add_argument("csv", type=Path)
    logs.add_argument("--out", type=Path)
    options = parser.parse_args(argv)
    try:
        if options.command == "init":
            game, content = safe_name(options.game), safe_name(options.content)
            target = options.root / game / content
            model = example(game, content, options.preset)
            # 같은 프리셋으로 등록한 두 콘텐츠도 서로 다른 데이터로 식별한다.
            model["content"]["id"] = content
            with fresh_output(target) as directory:
                write_json(directory / "모델.json", model)
                write_json(directory / "설정.json", {
                    "game": game, "content": content, "preset": options.preset, "model": "모델.json",
                    "purpose": "이 콘텐츠의 보상·성장 속도와 경제 영향을 설계",
                    "scope": "지정 콘텐츠의 입장·반복·보상·직접 연결 성장·재화 수급",
                    "exclude": ["게임 전체 방향", "UA·마케팅", "무관한 BM 개편"],
                    "materials": [], "fixed_decisions": [], "data_status": "가상 초안 — 실데이터로 교체 필요"})
                (directory / "자료").mkdir()
                (directory / "결과").mkdir()
            print_json({"created": str(target.resolve()), "data_status": "가상 초안",
                        "next": f"Codex에서 '{game}의 {content} 보상·성장 밸런스를 설계해줘. 목표는 ...'라고 요청하세요."})
            return 0
        if options.command == "compare":
            baseline, candidate = load_model(options.baseline), load_model(options.candidate)
            # 부적절한 비교는 계산 전에 거른다.
            require(baseline["game"] == candidate["game"] and baseline["content"]["id"] == candidate["content"]["id"], "같은 게임·콘텐츠끼리 비교하세요")
            require(baseline["simulation"] == candidate["simulation"], "days·samples·seed가 동일해야 비교할 수 있습니다")
            target = options.out or default_output(options.candidate, "비교")
            with fresh_output(target) as directory:
                before, after = simulate(baseline), simulate(candidate)
                comparison = compare(before, after)
                for name, model, result in (("기준안", baseline, before), ("변경안", candidate, after)):
                    (directory / name).mkdir()
                    export_report(directory / name, model, result)
                export_comparison(directory, comparison)
            print_json({"output": str(target.resolve()), **comparison})
            return 0
        model = load_model(options.model)
        if options.command == "validate":
            print_json({"valid": True, "model_hash": fingerprint(model), "content": model["content"]["name"]})
            return 0
        target = options.out or default_output(options.model, "검증" if options.command == "logs" else "계산")
        with fresh_output(target) as directory:
            result = simulate(model)
            export_report(directory, model, result)
            if options.command == "logs":
                telemetry = inspect_logs(options.csv, model, result)
                write_json(directory / "로그_검증.json", telemetry)
                write_csv(directory / "로그_대조.csv", telemetry["differences"], ["cohort", "metric", "observed", "simulated", "delta"])
                body = table(["코호트", "지표", "관측", "모의", "차이"],
                             [[row[key] if row[key] is not None else "계산 불가" for key in ("cohort", "metric", "observed", "simulated", "delta")] for row in telemetry["differences"]])
                from html import escape
                body += "<ul>" + "".join(f"<li>{escape(note)}</li>" for note in telemetry["limitations"]) + "</ul>"
                (directory / "로그_검증.html").write_text(document("콘텐츠 집계 로그 대조", body), encoding="utf-8")
        print_json({"output": str(target.resolve()), **(telemetry if options.command == "logs" else brief(result))})
        return 2 if options.command == "simulate" and options.strict and result["status"] != "pass" else 0
    except (ModelError, OSError, ValueError, ArithmeticError) as error:
        print(f"오류: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
