#!/usr/bin/env python3
"""Paired sensitivity study for the documented Wuwa reward proposal."""
from __future__ import annotations

import argparse
import csv
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from balance.wuwa_farming import simulate_echoes, summarize


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def mean_interval(values):
    mean = statistics.mean(values)
    se = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else 0
    return {'mean': mean, 'standard_error': se, 'mc_ci95': [mean - 1.95996398454 * se, mean + 1.95996398454 * se]}


def quantile_interval(values, quantile=.9, alpha=.05):
    ordered = sorted(values)
    epsilon = math.sqrt(math.log(2 / alpha) / (2 * len(ordered)))
    def q(p):
        return ordered[max(0, min(len(ordered) - 1, math.ceil(p * len(ordered)) - 1))]
    return {'method': 'DKW inversion, Monte Carlo uncertainty only', 'cdf_epsilon': epsilon,
            'p90_mc_ci95': [q(quantile - epsilon), q(quantile + epsilon)]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Use a new output directory')
    study = json.loads(args.input.read_text())
    baseline_path = Path(study['baseline_input_path'])
    if sha(baseline_path) != study['baseline_input_sha256']:
        raise ValueError('Baseline changed')
    baseline = json.loads(baseline_path.read_text())
    for path, expected in baseline['source_files'].items():
        if sha(path) != expected:
            raise ValueError('Source changed: ' + path)
    results, rows, samples_by_id = [], [], {}
    reference = None
    for arm in study['arms']:
        values, candidates = [], []
        bundles = []
        for r in baseline['tacet_rows']:
            scaled_exp = Fraction(str(r['exp'])) * Fraction(str(arm['exp_multiplier']))
            if scaled_exp.denominator != 1:
                raise ValueError('Study arm must yield integer EXP without rounding')
            bundles.append({'exp': int(scaled_exp), 'shell': r['shell']})
        for i in range(study['samples']):
            # The original simulator uses seed + 2*i for tuning and +1 for loot.
            trial = simulate_echoes({'crit_rate': None, 'crit_damage': None}, baseline['disclosure'],
                                   baseline['checkpoints'], bundles, policy='screen10',
                                   tuners_per_claim=arm['tuners'], shell_per_claim=baseline['shell_per_claim'],
                                   keep=1, samples=1, seed=baseline['seed'] + i * 2)
            days = trial['metrics']['waveplate_equivalent_days']['mean']
            count = trial['metrics']['candidates']['mean']
            values.append(days); candidates.append(count)
            rows.append([arm['id'], i, days, count])
        if reference is None:
            if arm['id'] != 't20':
                raise ValueError('First arm must be baseline t20')
            reference = values
        samples_by_id[arm['id']] = values
        difference = [new - old for new, old in zip(values, reference)]
        result = {**arm, 'days': summarize(values), 'mean_estimate': mean_interval(values),
                  'paired_difference_days': mean_interval(difference),
                  'p90_interval': quantile_interval(values), 'mean_candidates': statistics.mean(candidates),
                  'tuner_supply_per_240_waveplates': arm['tuners'] * 4}
        result['draft_constraints'] = {'extra_daily_tuners_at_most_16': arm['tuners'] * 4 - 80 <= 16,
                                       'p90_at_most_6_days': result['days']['p90'] <= 6,
                                       'exp_unchanged': arm['exp_multiplier'] == 1}
        result['draft_feasible'] = all(result['draft_constraints'].values())
        results.append(result)
        print(f"{arm['id']}: mean={result['days']['mean']:.4f}, p90={result['days']['p90']:.4f}", flush=True)
    out = {'input_sha256': sha(args.input), 'baseline_sha256': sha(baseline_path),
           'engine_sha256': sha(Path(__file__).resolve().parents[1] / 'balance/wuwa_farming.py'),
           'study_script_sha256': sha(__file__), 'samples': study['samples'], 'seed': baseline['seed'],
           'assumptions': study['assumptions'], 'draft_decision_criteria': study['draft_decision_criteria'],
           'arms': results, 'scope': 'conditional model sensitivity; not production experiment'}
    args.out.mkdir(parents=True)
    (args.out / '결과.json').write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n')
    with (args.out / '쌍체_시행.csv').open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f); writer.writerow(['arm', 'replicate', 'waveplate_equivalent_days', 'candidates']); writer.writerows(rows)


if __name__ == '__main__':
    main()
