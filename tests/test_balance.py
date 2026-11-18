import contextlib
from copy import deepcopy
import io
import json
from pathlib import Path
import random
import tempfile
import unittest

from balance.cli import fresh_output, main, safe_name
from balance.engine import compare, draw_rewards, reward_expectations, simulate
from balance.model import ModelError, example, fingerprint, load_json, validate
from balance.reports import export_report, write_csv
from balance.telemetry import FIELDS, inspect_logs


def fixture(days=3, samples=20):
    return {
        "schema_version": 1, "game": "검증게임",
        "content": {"id": "dungeon", "name": "테스트 던전", "start_day": 1, "end_day": days,
                    "reset_days": 1, "attempts_per_reset": 1, "entry_cost": {}, "failure_cost_ratio": 1,
                    "stages": [{"id": "normal", "name": "일반", "min_level": 0, "minutes": 1, "clear_rate": 1,
                                "rewards": [{"currency": "token", "amount": 1, "probability": 1, "group": ""}], "first_clear": {}}]},
        "currencies": [{"id": "token", "name": "토큰", "unit": "개"}],
        "growth": {"start_level": 0, "target_level": 2, "starting_power": 1,
                   "steps": [{"level": 1, "cost": {"token": 1}, "power": 2}, {"level": 2, "cost": {"token": 1}, "power": 3}]},
        "cohorts": [{"id": "regular", "name": "일반 유저", "start_level": 0,
                     "active_days_per_week": 7, "minutes_per_active_day": 30, "attempts_per_active_day": 3,
                     "clear_rate_multiplier": 1, "initial_wallet": {}, "daily_income": {}, "daily_sink": {}, "purchases": []}],
        "simulation": {"days": days, "samples": samples, "seed": 123},
        "targets": [{"cohort": "regular", "p50_day_min": 0, "p50_day_max": days, "min_completion_rate": 1}],
        "assumptions": ["자동 검증용 가상 입력"]}


class EngineTests(unittest.TestCase):
    def test_exact_growth_and_currency_conservation(self):
        model = fixture()
        result = simulate(model)
        row = result["cohorts"][0]
        self.assertEqual(row["target_days"], {"p10": 2, "p50": 2, "p90": 2})
        self.assertEqual(row["flows"]["content_income"]["token"], 3)
        self.assertEqual(row["flows"]["growth_cost"]["token"], 2)
        self.assertEqual(row["wallet_mean"]["token"], 1)
        self.assertEqual(result["status"], "pass")

    def test_first_clear_once_across_daily_resets(self):
        model = fixture()
        model["content"]["stages"][0]["first_clear"] = {"token": 5}
        row = simulate(model)["cohorts"][0]
        self.assertEqual(row["flows"]["content_income"]["token"], 8)
        self.assertEqual(row["target_days"]["p50"], 1)

    def test_weekly_reset_and_no_rollover(self):
        model = fixture(8)
        model["content"].update(reset_days=7, attempts_per_reset=3)
        model["cohorts"][0]["attempts_per_active_day"] = 2
        rows = simulate(model)["cohorts"][0]["daily"]
        self.assertEqual([row["attempts"] for row in rows], [2, 1, 0, 0, 0, 0, 0, 2])

    def test_event_start_and_end_are_inclusive(self):
        model = fixture(5)
        model["content"].update(start_day=2, end_day=3)
        rows = simulate(model)["cohorts"][0]["daily"]
        self.assertEqual([row["attempts"] for row in rows], [0, 1, 1, 0, 0])

    def test_failed_run_consumes_quota_and_time_but_no_reward(self):
        model = fixture(1)
        model["content"]["stages"][0].update(clear_rate=0, first_clear={"token": 100})
        model["content"].update(attempts_per_reset=3, entry_cost={"token": 2}, failure_cost_ratio=0.5)
        model["cohorts"][0]["initial_wallet"] = {"token": 5}
        for step in model["growth"]["steps"]:
            step["cost"] = {"token": 100}
        row = simulate(model)["cohorts"][0]
        self.assertEqual(row["attempts_mean"], 3)
        self.assertEqual(row["minutes_mean"], 3)
        self.assertEqual(row["clears_mean"], 0)
        self.assertEqual(row["wallet_mean"]["token"], 2)
        self.assertEqual(row["flows"]["content_income"]["token"], 0)

    def test_full_entry_cost_required_even_if_failure_refunds_all(self):
        model = fixture()
        model["content"].update(entry_cost={"token": 1}, failure_cost_ratio=0)
        model["content"]["stages"][0]["clear_rate"] = 0
        row = simulate(model)["cohorts"][0]
        self.assertEqual(row["attempts_mean"], 0)
        self.assertEqual(row["blocked_days_mean"]["entry_cost"], 3)

    def test_unaffordable_time_and_locked_stage(self):
        for change, reason in (({"minutes": 31}, "time"), ({"min_level": 1}, "level")):
            with self.subTest(reason=reason):
                model = fixture()
                model["content"]["stages"][0].update(change)
                row = simulate(model)["cohorts"][0]
                self.assertEqual(row["attempts_mean"], 0)
                self.assertEqual(row["blocked_days_mean"][reason], 3)

    def test_unlock_mid_day_and_first_clear_per_stage(self):
        model = fixture(1)
        model["content"]["attempts_per_reset"] = 2
        hard = deepcopy(model["content"]["stages"][0])
        hard.update(id="hard", name="어려움", min_level=1, first_clear={"token": 5})
        model["content"]["stages"].append(hard)
        row = simulate(model)["cohorts"][0]
        self.assertEqual(row["stage_clears_mean"], {"normal": 1, "hard": 1})
        self.assertEqual(row["flows"]["content_income"]["token"], 7)

    def test_exclusive_drops_never_pay_twice(self):
        stage = {"rewards": [{"currency": "token", "amount": 1, "probability": 0.4, "group": "box"},
                             {"currency": "token", "amount": 2, "probability": 0.6, "group": "box"}]}
        rng = random.Random(9)
        values = [draw_rewards(stage, rng)["token"] for _ in range(1000)]
        self.assertEqual(set(values), {1, 2})

    def test_independent_drop_monte_carlo_matches_known_expectation(self):
        stage = {"rewards": [{"currency": "token", "amount": 4, "probability": 0.25, "group": ""}]}
        rng = random.Random(52)
        mean = sum(draw_rewards(stage, rng)["token"] for _ in range(10000)) / 10000
        self.assertAlmostEqual(mean, 1, delta=0.08)

    def test_reward_expectations_exclude_first_clear(self):
        model = fixture()
        model["content"]["stages"][0].update(clear_rate=0.5, minutes=2, first_clear={"token": 50})
        self.assertEqual(reward_expectations(model)[0], {"stage": "normal", "currency": "token",
                         "per_clear": 1, "per_attempt": 0.5, "per_minute": 0.25, "first_clear": 50})

    def test_censored_quantiles_do_not_drop_nonfinishers(self):
        model = fixture(1, 500)
        model["growth"]["target_level"] = 1
        model["growth"]["steps"] = model["growth"]["steps"][:1]
        model["content"]["stages"][0]["clear_rate"] = 0.25
        row = simulate(model)["cohorts"][0]
        self.assertGreater(row["reach_rate"], 0.1)
        self.assertLess(row["reach_rate"], 0.5)
        self.assertEqual(row["target_days"], {"p10": 1, "p50": None, "p90": None})
        self.assertEqual(row["reached_only_p50"], 1)

    def test_inactive_daily_income_purchase_and_unpaid_sink(self):
        model = fixture(2)
        model["cohorts"][0].update(active_days_per_week=0, daily_income={"token": 1}, daily_sink={"token": 5},
            purchases=[{"id": "p1", "day": 2, "price_krw": 1000, "grants": {"token": 10}}])
        row = simulate(model)["cohorts"][0]
        self.assertEqual(row["attempts_mean"], 0)
        self.assertEqual(row["flows"]["other_sink"]["token"], 6)
        self.assertEqual(row["flows"]["unpaid_sink"]["token"], 4)
        self.assertEqual(row["flows"]["purchase_income"]["token"], 10)
        self.assertEqual(row["spent_krw_mean"], 1000)
        self.assertEqual(row["wallet_mean"]["token"], 4)

    def test_initial_wallet_growth_counts_as_day_zero(self):
        model = fixture()
        model["cohorts"][0]["initial_wallet"] = {"token": 2}
        self.assertEqual(simulate(model)["cohorts"][0]["target_days"]["p50"], 0)

    def test_seed_reproducible_and_independent_of_cohort_order(self):
        model = fixture()
        model["content"]["stages"][0]["clear_rate"] = 0.6
        second = deepcopy(model["cohorts"][0])
        second["id"] = "other"
        model["cohorts"].append(second)
        first = simulate(model)
        self.assertEqual(first, simulate(model))
        model["cohorts"].reverse()
        reversed_result = simulate(model)
        self.assertEqual(first["cohorts"], list(reversed(reversed_result["cohorts"])))

    def test_compare_matches_ids_and_requires_same_simulation(self):
        model = fixture()
        baseline = simulate(model)
        model["content"]["stages"][0]["rewards"][0]["amount"] = 2
        candidate = simulate(model)
        self.assertEqual(compare(baseline, candidate)["rows"][0]["p50_delta_days"], -1)
        candidate["simulation"]["seed"] = 999
        with self.assertRaises(ValueError):
            compare(baseline, candidate)


class ValidationTests(unittest.TestCase):
    def test_presets_are_valid(self):
        for preset in ("daily", "raid", "event"):
            validate(example(preset=preset))

    def test_bad_models_are_rejected(self):
        cases = [
            lambda m: m["targets"][0].update(cohort=[]),
            lambda m: m["content"]["stages"][0]["rewards"][0].update(currency=[]),
            lambda m: m["simulation"].update(samples=10**400),
            lambda m: m["simulation"].update(days=0),
            lambda m: m["simulation"].update(samples=True),
            lambda m: m["cohorts"][0].update(initial_wallet={"unknown": 1}),
            lambda m: m["cohorts"][0].update(daily_income={"token": -1}),
            lambda m: m["content"].update(failure_cost_ratio=float("nan")),
            lambda m: m["content"].update(end_day=4),
            lambda m: m["content"]["stages"][0].update(clear_rate=95),
            lambda m: m["content"]["stages"][0].update(minutes=0),
            lambda m: m["growth"]["steps"][1].update(level=1),
            lambda m: m["growth"]["steps"][0].update(success_rate=0.5),
            lambda m: m["targets"][0].update(cohort="missing"),
            lambda m: m["cohorts"].append(deepcopy(m["cohorts"][0])),
            lambda m: m["content"]["stages"][0].update(rewards=[{"currency": "token", "amount": 1, "probability": 0.6, "group": "box"}] * 2),
            lambda m: m["simulation"].update(days=366, samples=5000),
        ]
        for index, mutate in enumerate(cases):
            with self.subTest(index=index):
                model = fixture()
                mutate(model)
                if index == len(cases)-1:
                    model["cohorts"][0]["attempts_per_active_day"] = 100
                with self.assertRaises(ModelError):
                    validate(model)

    def test_duplicate_json_keys_and_infinity_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            for content in ('{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}'):
                path.write_text(content)
                with self.assertRaises(ModelError):
                    load_json(path)

    def test_fingerprint_ignores_key_order_but_tracks_changes(self):
        model = fixture()
        self.assertEqual(fingerprint(model), fingerprint(dict(reversed(list(model.items())))))
        changed = deepcopy(model)
        changed["assumptions"].append("new")
        self.assertNotEqual(fingerprint(model), fingerprint(changed))

    def test_path_names_reject_traversal_and_windows_reserved(self):
        for name in ("..", "a/b", "a\\b", "CON", "con.txt", "name.", " bad", "_템플릿", ""):
            with self.subTest(name=name), self.assertRaises(ModelError):
                safe_name(name)
        self.assertEqual(safe_name("한글 던전"), "한글 던전")


class IOTests(unittest.TestCase):
    def invoke(self, args):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(args)

    def test_cli_registration_preserves_existing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["init", "--game", "테스트", "--content", "일일 던전", "--root", directory]
            self.assertEqual(self.invoke(args), 0)
            path = Path(directory) / "테스트/일일 던전/모델.json"
            before = path.read_bytes()
            self.assertEqual(json.loads(before)["content"]["id"], "일일 던전")
            self.assertEqual(self.invoke(args), 1)
            self.assertEqual(path.read_bytes(), before)

    def test_strict_failure_still_writes_complete_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path, out = Path(directory) / "model.json", Path(directory) / "result"
            model = fixture()
            model["content"]["stages"][0]["clear_rate"] = 0
            path.write_text(json.dumps(model))
            self.assertEqual(self.invoke(["simulate", str(path), "--out", str(out), "--strict"]), 2)
            self.assertTrue((out / "리포트.html").is_file())
            self.assertEqual(len(list(out.iterdir())), 9)
            snapshot = (out / "결과.json").read_bytes()
            self.assertEqual(self.invoke(["simulate", str(path), "--out", str(out)]), 1)
            self.assertEqual((out / "결과.json").read_bytes(), snapshot)

    def test_failed_export_does_not_leave_partial_result(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "result"
            with self.assertRaises(RuntimeError):
                with fresh_output(out) as temporary:
                    (temporary / "partial").write_text("temporary")
                    raise RuntimeError("failure")
            self.assertFalse(out.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_html_escapes_input_and_csv_prevents_formula_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            model = fixture()
            model["game"] = "<script>alert(1)</script>"
            model["cohorts"][0]["name"] = "=1+1"
            export_report(directory, model, simulate(model))
            html = (Path(directory) / "리포트.html").read_text()
            self.assertNotIn("<script>", html)
            self.assertIn("&lt;script&gt;", html)
            csv = (Path(directory) / "코호트_요약.csv").read_text(encoding="utf-8-sig")
            self.assertIn("'=1+1", csv)

    def test_no_targets_are_not_a_pass(self):
        model = fixture()
        model["targets"] = []
        self.assertEqual(simulate(model)["status"], "no_targets")


class LogTests(unittest.TestCase):
    def setUp(self):
        self.model = fixture()
        self.simulation = simulate(self.model)
        self.rows = [{"date": "2026-01-01", "content_id": "dungeon", "cohort_id": "regular",
                      "metric": metric, "currency": currency, "value": value}
                     for metric, currency, value in [("users", "", 10), ("attempts", "", 10),
                                                      ("clears", "", 10), ("minutes", "", 10), ("reward", "token", 10)]]

    def inspect(self, rows):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "logs.csv"
            write_csv(path, rows, FIELDS)
            return inspect_logs(path, self.model, self.simulation)

    def test_observed_rates_and_other_content_filter(self):
        other = dict(self.rows[0], content_id="unrelated", cohort_id="unknown")
        result = self.inspect(self.rows + [other])
        self.assertEqual(result["other_content_rows_ignored"], 1)
        self.assertEqual(result["cohorts"][0]["active_user_days"], 10)
        self.assertTrue(all(row["delta"] == 0 for row in result["differences"]))

    def test_duplicate_missing_unknown_and_invalid_counts_rejected(self):
        variants = [self.rows + [self.rows[0]], self.rows[1:],
                    [dict(row, cohort_id="unknown") for row in self.rows],
                    [dict(row, value=11) if row["metric"] == "clears" else row for row in self.rows],
                    [dict(row, value=0) if row["metric"] == "users" else row for row in self.rows]]
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(ModelError):
                self.inspect(rows)

    def test_missing_currency_is_unobserved_not_zero(self):
        result = self.inspect(self.rows[:-1])
        self.assertFalse(any(row["metric"].startswith("reward_per_clear") for row in result["differences"]))

    def test_zero_activity_denominators_return_none(self):
        result = self.inspect([dict(row, value=0) for row in self.rows])
        self.assertTrue(all(row["observed"] is None and row["delta"] is None for row in result["differences"]))


if __name__ == "__main__":
    unittest.main()
