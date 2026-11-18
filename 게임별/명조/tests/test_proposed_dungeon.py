import unittest
import json
from pathlib import Path
from balance.proposed_dungeon import project, validate, calculate, effective_stages


class ProposedDungeonTests(unittest.TestCase):
    def setUp(self):
        self.stage = {"cost": 60, "xp_items": 5, "tuners": 24, "coins": 12000}

    def test_default_week_is_whole_claims(self):
        last = project(self.stage, 180)[-1]
        self.assertEqual((last["total_claims"], last["tuners"], last["xp"], last["coins"]), (21, 504, 525000, 252000))

    def test_unspent_stamina_carries_across_days(self):
        rows = project({**self.stage, "cost": 80}, 60)
        self.assertEqual([r["claims"] for r in rows], [0, 1, 1, 1, 0, 1, 1])
        self.assertEqual((rows[-1]["total_claims"], rows[-1]["carry"]), (5, 20))
        for r in rows:
            self.assertEqual(r["day"] * 60, r["total_spent"] + r["carry"])

    def test_zero_reward_remains_zero(self):
        rows = project({**self.stage, "tuners": 0, "coins": 0}, 240)
        self.assertTrue(all(r["tuners"] == r["coins"] == 0 for r in rows))
        self.assertGreater(rows[-1]["xp"], 0)

    def test_more_claims_never_creates_free_stamina(self):
        for budget in range(60, 241, 10):
            for cost in range(30, 81, 10):
                last = project({**self.stage, "cost": cost}, budget)[-1]
                self.assertEqual(last["total_claims"], (budget * 7) // cost)
                self.assertEqual(last["tuners"], 24 * ((budget * 7) // cost))

    def test_live_data_cannot_be_claimed_by_this_contract(self):
        with self.assertRaises(ValueError):
            validate({"schema": "proposed_dungeon_rewards_v1", "fictional": False})


class ProposedDungeonEconomyTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).with_name("잔향정제실_예제.json")
        self.model = json.loads(fixture.read_text(encoding="utf-8"))

    def test_every_stage_uses_global_sliders_and_whole_rewards(self):
        self.model["global_controls"].update(cost=80, xp_percent=150, tuner_percent=150, coin_percent=50)
        rows = effective_stages(self.model)
        self.assertEqual([s["cost"] for s in rows], [80, 80, 80])
        self.assertEqual([s["xp_items"] for s in rows], [5, 6, 8])
        self.assertEqual([s["tuners"] for s in rows], [18, 27, 36])
        self.assertEqual([s["coins"] for s in rows], [3000, 4500, 6000])

    def test_new_supply_replaces_legacy_supply(self):
        r = calculate(self.model)["week"]
        self.assertEqual(r["before_claims"], 28)
        self.assertEqual(r["remaining_legacy_claims"], 14)
        self.assertEqual(r["new_claims_participant"], 14)
        self.assertAlmostEqual(r["delta"]["tuners"], -1.4)
        for key in ["xp", "tuners", "coins"]:
            self.assertAlmostEqual(r["delta"][key],
                (r["new_supply_participant"][key] - r["lost_legacy"][key]) * .5)
            self.assertAlmostEqual(r["net_after"][key], r["after"][key] - r["demand"][key])
            self.assertAlmostEqual(r["totals_delta"][key], r["delta"][key] * 10000)

    def test_zero_adoption_or_allocation_is_unchanged(self):
        for key in ["adoption_percent", "new_share_percent"]:
            previous = self.model["economy"][key]
            self.model["economy"][key] = 0
            r = calculate(self.model)["week"]
            self.assertEqual(r["before"], r["after"])
            self.assertTrue(all(v == 0 for v in r["delta"].values()))
            self.model["economy"][key] = previous

    def test_full_adoption_and_allocation_eliminates_legacy(self):
        self.model["economy"].update(adoption_percent=100, new_share_percent=100)
        r = calculate(self.model)["week"]
        self.assertEqual(r["legacy_claims_average"], 0)
        for key in ["xp", "tuners", "coins"]:
            self.assertAlmostEqual(r["after"][key], r["new_supply_participant"][key] + r["other_supply"][key])

    def test_each_person_is_floored_before_population_averaging(self):
        self.model["global_controls"]["cost"] = 80
        self.model["economy"].update(daily_budget=60, new_share_percent=50, adoption_percent=50)
        rows = calculate(self.model)["daily_rows"]
        self.assertEqual(rows[0]["new_claims_average"], 0)
        self.assertEqual(rows[2]["new_claims_average"], .5)
        for row in rows:
            self.assertAlmostEqual(row["used_stamina_average"] + row["carry_average"], row["day"] * 60)

    def test_population_scale_does_not_change_individual_rewards(self):
        a = calculate(self.model)["week"]
        self.model["economy"]["population"] = 20000
        b = calculate(self.model)["week"]
        self.assertEqual(a["after"], b["after"])
        for key in ["xp", "tuners", "coins"]:
            self.assertAlmostEqual(a["totals_delta"][key] * 2, b["totals_delta"][key])

    def test_all_difficulty_share_can_move_to_one_stage(self):
        self.model["economy"]["stage_shares"] = {"basic": 0, "focused": 0, "deep": 100}
        r = calculate(self.model)["week"]
        self.assertEqual(r["new_supply_participant"]["tuners"], 14 * 24)

    def test_invalid_weights_and_nonfinite_economy_are_rejected(self):
        self.model["economy"]["stage_shares"]["deep"] = 51
        with self.assertRaises(ValueError):
            validate(self.model)
        self.model["economy"]["stage_shares"]["deep"] = 50
        self.model["economy"]["other_daily"]["xp"] = float("nan")
        with self.assertRaises(ValueError):
            validate(self.model)

    def test_budget_is_never_duplicated_across_routes(self):
        for budget in [60, 170, 360]:
            for share in [0, 5, 50, 95, 100]:
                for cost in [30, 80, 120]:
                    self.model["economy"].update(daily_budget=budget, new_share_percent=share)
                    self.model["global_controls"]["cost"] = cost
                    for r in calculate(self.model)["daily_rows"]:
                        self.assertGreaterEqual(r["carry_average"], 0)
                        self.assertAlmostEqual(r["used_stamina_average"] + r["carry_average"], r["day"] * budget)


if __name__ == "__main__":
    unittest.main()
