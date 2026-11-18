import math
import random
import unittest

from balance.wuwa_reconstruct import reconstruction_expectation

COSTS = {0: 1, 1: 1, 2: 1, 3: 2, 4: 3}


class WuwaReconstructTests(unittest.TestCase):
    def setUp(self):
        names = ["crit_rate", "crit_damage", "atk_pct"] + [f"other{i}" for i in range(10)]
        self.names = names
        self.disclosure = {"substats": {n: {"values": [1, 2], "probabilities": [.7, .3]} for n in names}}

    def test_two_type_goal_matches_closed_form(self):
        r = reconstruction_expectation({"crit_rate": None, "crit_damage": None}, self.disclosure, COSTS)
        c = math.comb
        both, one, none = c(11, 3) / c(13, 5), 2 * c(11, 4) / c(13, 5), c(11, 5) / c(13, 5)
        e1 = 1 / (4 / 12)                       # lock the crit, reroll 4 of 12
        p_one0, p_none0 = 2 * c(10, 3) / c(12, 4), c(10, 4) / c(12, 4)
        e0 = (1 + p_one0 * e1) / (1 - p_none0)  # lock one other type
        self.assertAlmostEqual(r["natural_success_probability"], both)
        self.assertAlmostEqual(r["expected_items"], one * e1 + none * e0)
        self.assertEqual(r["p50_items"], 2)

    def test_lock_cost_and_threshold_raise_item_use(self):
        loose = reconstruction_expectation({"crit_rate": None, "crit_damage": None}, self.disclosure, COSTS)
        strict = reconstruction_expectation({"crit_rate": 2, "crit_damage": 2}, self.disclosure, COSTS)
        self.assertGreater(strict["expected_items"], loose["expected_items"])
        self.assertLessEqual(strict["p50_items"], strict["p90_items"])
        dear = reconstruction_expectation({"crit_rate": None, "crit_damage": None}, self.disclosure,
                                          {**COSTS, 1: 2})
        self.assertGreater(dear["expected_items"], loose["expected_items"])

    def test_monte_carlo_agrees_with_exact_value(self):
        goals = {"crit_rate": 2, "crit_damage": None}
        exact = reconstruction_expectation(goals, self.disclosure, COSTS)["expected_items"]
        rng, total, runs = random.Random(7), 0, 20000

        def roll(pool, k):
            return {t: (2 if rng.random() < .3 else 1) for t in rng.sample(pool, k)}

        for _ in range(runs):
            echo = roll(self.names, 5)
            have = {t for t in goals if t in echo and (goals[t] is None or echo[t] >= goals[t])}
            while have != set(goals):
                locked = set(have) or {next(t for t in echo if t not in goals)}
                total += COSTS[len(locked)]
                new = roll([t for t in self.names if t not in locked], 5 - len(locked))
                echo = {t: echo[t] for t in locked} | new
                have = {t for t in goals if t in echo and (goals[t] is None or echo[t] >= goals[t])}
        self.assertAlmostEqual(total / runs, exact, delta=exact * .03)

    def test_rejects_invalid_requests(self):
        with self.assertRaises(ValueError):
            reconstruction_expectation({}, self.disclosure, COSTS)
        with self.assertRaises(ValueError):
            reconstruction_expectation({n: None for n in self.names[:5]}, self.disclosure, COSTS)
        with self.assertRaises(ValueError):
            reconstruction_expectation({"crit_rate": None}, self.disclosure, {0: 1})


if __name__ == "__main__":
    unittest.main()
