#!/usr/bin/env python3
"""Compare +10 screening with '+25 once, then sub-stat reconstruction' for kept echoes."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balance.wuwa_farming import policy_expectation
from balance.wuwa_reconstruct import reconstruction_expectation


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("기존 회차를 보존하도록 새 출력 경로를 지정하세요.")
    raw = args.input.read_bytes()
    data = json.loads(raw)
    if data["format"] != "wuwa_reconstruction_compare_v1":
        raise ValueError("Unsupported input format")
    base = args.input.resolve().parent
    for rel, digest in data["source_files"].items():
        if sha((base / rel).resolve()) != digest:
            raise ValueError(f"Source changed: {rel}")
    farm = json.loads((base / data["farming_input"]).read_text(encoding="utf-8"))
    disclosure, checkpoints = farm["disclosure"], farm["checkpoints"]
    full = next(c for c in checkpoints if c["level"] == 25)
    exp_per_claim = statistics.mean(r["exp"] for r in farm["tacet_rows"])
    lock_costs = {int(k): v for k, v in data["lock_costs"].items()}

    rows = []
    for case in data["goals"]:
        screen = policy_expectation(case["goals"], disclosure, checkpoints, data["baseline_policy"])
        recon = {z: reconstruction_expectation(case["goals"], disclosure, lock_costs, zero_lock=z)
                 for z in data["zero_lock_options"]}
        main_r = recon[data["zero_lock_options"][0]]
        saved_tuners = screen["expected_net_tuners"] - full["tuners"]
        row = {
            "id": case["id"], "name": case["name"],
            "screen10": screen,
            "reconstruct": {
                "candidates": 1,
                "exp": full["cumulative_exp"], "tuners": full["tuners"], "coins": full["total_coins"],
                "by_zero_lock": {str(z): r for z, r in recon.items()},
            },
            "tuners_saved_per_kept_echo": saved_tuners,
            "candidates_saved_per_kept_echo": screen["expected_candidates"] - 1,
            "break_even_tuners_per_item": saved_tuners / main_r["expected_items"],
            "tacet_claims": {
                "screen10_exp": screen["expected_net_xp"] / exp_per_claim,
                "screen10_tuners": {str(t): screen["expected_net_tuners"] / t for t in data["tuners_per_claim"]},
                "reconstruct_exp": full["cumulative_exp"] / exp_per_claim,
                "reconstruct_tuners": {str(t): full["tuners"] / t for t in data["tuners_per_claim"]},
            },
        }
        rows.append(row)
        print(f"{case['name']}: 선별 튜너 {screen['expected_net_tuners']:.1f}·후보 {screen['expected_candidates']:.2f}"
              f" → 재구성 튜너 {full['tuners']}·조정기 평균 {main_r['expected_items']:.3f}"
              f" (p90 {main_r['p90_items']}), 조정기 1개 ≈ 튜너 {row['break_even_tuners_per_item']:.1f}")

    out = {"format": data["format"], "input_sha256": hashlib.sha256(raw).hexdigest(),
           "status": "official_rule_plus_client_cost_estimate",
           "exp_per_claim_reference": exp_per_claim,
           "assumptions": data["assumptions"], "limitations": data["limitations"], "goals": rows}
    args.out.mkdir(parents=True)
    (args.out / "결과.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with (args.out / "비교.csv").open("w", encoding="utf-8-sig", newline="") as file:
        w = csv.writer(file)
        w.writerow(["id", "name", "screen10_candidates", "screen10_net_tuners", "screen10_net_exp",
                    "reconstruct_tuners", "reconstruct_exp", "items_mean", "items_p50", "items_p90",
                    "items_mean_zero_lock0", "break_even_tuners_per_item"])
        for r in rows:
            s, rc = r["screen10"], r["reconstruct"]
            m = rc["by_zero_lock"][str(data["zero_lock_options"][0])]
            alt = rc["by_zero_lock"].get("0", m)
            w.writerow([r["id"], r["name"], s["expected_candidates"], s["expected_net_tuners"], s["expected_net_xp"],
                        rc["tuners"], rc["exp"], m["expected_items"], m["p50_items"], m["p90_items"],
                        alt["expected_items"], r["break_even_tuners_per_item"]])


if __name__ == "__main__":
    main()
