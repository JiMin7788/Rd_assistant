"""Placement simulator tests (M6): operations, and that the min-skill planner
converges using far fewer skill casts than destroy-only."""
import unittest
from rdom.sim.board_sim import SimBoard, is_complete, FIXED, NCELLS
from rdom.sim.planner import solve, classify, NEED


class TestOps(unittest.TestCase):
    def test_summon_fills_empty_at_pip1(self):
        b = SimBoard(seed=1)
        i = b.summon()
        self.assertIsNotNone(i)
        self.assertEqual(b.cells[i][1], 1)
        self.assertEqual(b.summons, 1)

    def test_merge_same_type_frees_cell_and_raises_pip(self):
        b = SimBoard(seed=1)
        b.cells[0] = b.cells[1] = ("Resonance", 1)
        t = b.merge(0, 1)
        self.assertIsNotNone(t)
        self.assertIsNone(b.cells[0])
        self.assertEqual(b.cells[1][1], 2)     # pip raised
        self.assertEqual(b.merges, 1)
        self.assertEqual(b.skills, 0)          # merge is free

    def test_merge_rejects_mismatch(self):
        b = SimBoard(seed=1)
        b.cells[0], b.cells[1] = ("Light", 1), ("Bubble", 1)
        self.assertIsNone(b.merge(0, 1))

    def test_destroy_counts_a_skill(self):
        b = SimBoard(seed=1)
        b.cells[5] = ("Predator", 1)
        b.destroy(5)
        self.assertIsNone(b.cells[5])
        self.assertEqual(b.skills, 1)


class TestComplete(unittest.TestCase):
    def _valid(self):
        cells = [None] * 15
        for cell, want in FIXED.items():
            cells[cell - 1] = (want, 1)
        vals = [("Bubble", 3), ("Resonance", 1), ("Resonance", 1),
                ("Resonance", 1), ("Switch", 1), ("Predator", 2), ("Light", 1)]
        for c, v in zip(NCELLS, vals):
            cells[c - 1] = v
        return cells

    def test_valid_target_complete(self):
        self.assertTrue(is_complete(self._valid()))

    def test_pip_mismatch_predator_resonance_fails(self):
        cells = self._valid()
        cells[0] = ("Predator", 2)   # #1 predator pip2 while resonance pip1
        self.assertFalse(is_complete(cells))

    def test_too_few_resonance_fails(self):
        cells = self._valid()
        cells[4 - 1] = ("Light", 1)  # drop a resonance from n-cells
        # now only 2 resonance in n-cells
        self.assertFalse(is_complete(cells))


class TestPlanner(unittest.TestCase):
    def test_min_skill_converges_every_seed(self):
        for seed in range(300):
            b = SimBoard(seed=seed)
            r = solve(b, mode="min_skill")
            self.assertTrue(r["complete_inventory"], f"seed {seed}")
            self.assertTrue(is_complete(b.cells), f"seed {seed} layout")

    def test_min_skill_uses_fewer_skills_than_destroy_only(self):
        def avg(mode):
            tot = 0
            for seed in range(300):
                tot += solve(SimBoard(seed=seed), mode=mode)["skills"]
            return tot / 300
        self.assertLess(avg("min_skill"), avg("destroy_only"))

    def test_eager_converges_and_lowers_worst_case(self):
        worst_eager = worst_min = 0
        for seed in range(300):
            worst_eager = max(worst_eager, solve(SimBoard(seed=seed), mode="eager")["skills"])
            worst_min = max(worst_min, solve(SimBoard(seed=seed), mode="min_skill")["skills"])
        self.assertLessEqual(worst_eager, worst_min)

    def test_recovery_from_disruption_converges(self):
        from rdom.sim.board_sim import disrupt
        import random
        for seed in range(100):
            b = SimBoard(seed=seed)
            solve(b, mode="eager")
            self.assertTrue(is_complete(b.cells))
            b.cells = disrupt(b.cells, 3, random.Random(seed))
            solve(b, mode="eager")
            self.assertTrue(is_complete(b.cells), f"seed {seed} recovery")


if __name__ == "__main__":
    unittest.main()
