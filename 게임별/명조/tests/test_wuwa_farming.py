import math
import unittest

from balance.wuwa_farming import (policy_expectation, simulate_echoes,
                                  simulate_material, type_probability)


class WuwaFarmingTests(unittest.TestCase):
    def setUp(self):
        names = ["crit_rate", "crit_damage", "atk_pct"] + [f"other{i}" for i in range(10)]
        self.disclosure = {"substats": {n: {"values": [1, 2], "probabilities": [.7, .3]} for n in names}}
        self.points = [{"cumulative_exp": i * 100, "total_coins": i * 50,
                        "refunded_exp": i * 75, "refunded_tuners": i * 3}
                       for i in range(1, 6)]

    def test_exact_sampling_without_replacement(self):
        self.assertAlmostEqual(type_probability(2), 10 / 78)
        self.assertAlmostEqual(type_probability(5), 1 / 1287)
        goals = {"crit_rate": None, "crit_damage": None}
        result = policy_expectation(goals, self.disclosure, self.points, "full25")
        self.assertAlmostEqual(result["success_probability_per_candidate"], type_probability(2))
        failures = 1 / type_probability(2) - 1
        self.assertAlmostEqual(result["expected_net_tuners"], 50 + 35 * failures)
        self.assertAlmostEqual(result["expected_net_xp"], 500 + 125 * failures)

    def test_value_threshold_multiplies_type_probability(self):
        result = policy_expectation({"crit_rate": 2, "crit_damage": 2}, self.disclosure, self.points, "full25")
        self.assertAlmostEqual(result["success_probability_per_candidate"], type_probability(2) * .3 ** 2)

    def test_screening_trades_candidates_for_lower_material_cost(self):
        goals = {"crit_rate": None, "crit_damage": None}
        full = policy_expectation(goals, self.disclosure, self.points, "full25")
        screened = policy_expectation(goals, self.disclosure, self.points, "screen10")
        self.assertGreater(screened["expected_candidates"], full["expected_candidates"])
        self.assertLess(screened["expected_net_tuners"], full["expected_net_tuners"])

    def test_initial_liquidity_and_refunds_are_not_negative_costs(self):
        result = simulate_echoes({}, self.disclosure, self.points, [{"exp": 100, "shell": 50}], samples=3)
        self.assertEqual(result["metrics"]["tacet_claims"]["mean"], 5)
        self.assertEqual(result["metrics"]["credit_claims"]["mean"], 0)
        self.assertEqual(result["metrics"]["net_tuners"]["mean"], 50)
        supplied = simulate_echoes({}, self.disclosure, self.points, [{"exp": 100, "shell": 50}],
                                   samples=3, initial_inventory=(500, 50, 250))
        self.assertEqual(supplied["metrics"]["waveplates"]["mean"], 0)

    def test_monte_carlo_matches_exact_tuner_cost(self):
        goals = {"crit_rate": None, "crit_damage": None}
        exact = policy_expectation(goals, self.disclosure, self.points, "screen10")
        result = simulate_echoes(goals, self.disclosure, self.points, [{"exp": 500, "shell": 500}], samples=4000)
        self.assertLess(abs(result["metrics"]["net_tuners"]["mean"] / exact["expected_net_tuners"] - 1), .05)

    def test_material_stopping_time_keeps_overshoot(self):
        result = simulate_material([{"drop": 3}], "drop", 10, waveplate_cost=60, samples=20)
        self.assertEqual(result["claims"]["mean"], 4)
        self.assertEqual(result["waveplate_equivalent_days"]["mean"], 1)
        with self.assertRaises(ValueError):
            simulate_material([{"drop": 0}], "drop", 10, waveplate_cost=60)


if __name__ == "__main__":
    unittest.main()
