#!/usr/bin/env python3
"""Run explicitly sourced conditional farming scenarios, without network access."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balance.wuwa_farming import policy_expectation, simulate_echoes, simulate_material


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("기존 회차를 보존하도록 새 출력 경로를 지정하세요.")
    raw = args.input.read_bytes()
    data = json.loads(raw)
    if data["format"] != "wuwa_conditional_farming_v1":
        raise ValueError("Unsupported input format")
    for path, digest in data["source_files"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Source changed: {path}")
    results = []
    for case in data["echo_scenarios"]:
        result = simulate_echoes(case["goals"], data["disclosure"], data["checkpoints"],
                                 data["tacet_rows"], policy=case["policy"],
                                 tuners_per_claim=case["tuners_per_claim"],
                                 shell_per_claim=data["shell_per_claim"], keep=case["keep"],
                                 samples=case["samples"], seed=data["seed"])
        result.update(id=case["id"], name=case["name"], evidence_status=case["evidence_status"])
        result["exact_per_kept_echo"] = policy_expectation(case["goals"], data["disclosure"],
                                                          data["checkpoints"], case["policy"])
        results.append(result)
        days = result["metrics"]["waveplate_equivalent_days"]
        print(f"{case['name']}: 평균 {days['mean']:.3f}, p50 {days['p50']:.3f}, p90 {days['p90']:.3f} 환산일", flush=True)
    materials = []
    for case in data["material_scenarios"]:
        result = simulate_material(case["rows"], case["field"], case["target"],
                                   waveplate_cost=case["waveplate_cost"],
                                   seed=data["seed"], samples=case["samples"])
        result.update(id=case["id"], name=case["name"], evidence_status=case["evidence_status"])
        materials.append(result)
    output = {"format": data["format"], "input_sha256": hashlib.sha256(raw).hexdigest(),
              "status": "external_reference_estimate", "assumptions": data["assumptions"],
              "limitations": data["limitations"], "echo_scenarios": results,
              "material_scenarios": materials}
    args.out.mkdir(parents=True)
    (args.out / "결과.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.out / "에코_시나리오.csv").open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["id", "name", "status", "mean_waveplate_days", "p50_waveplate_days", "p90_waveplate_days", "samples"])
        for r in results:
            days = r["metrics"]["waveplate_equivalent_days"]
            writer.writerow([r["id"], r["name"], r["evidence_status"], days["mean"], days["p50"], days["p90"], r["samples"]])


if __name__ == "__main__":
    main()
