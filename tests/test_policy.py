"""M3 rule-engine tests for the eager min-skill planner (docs/02)."""
import unittest
from rdom.policy.target import evaluate, plan_next, classify, FIXED, NCELLS


def board_from(types, pips=None, pip2=None):
    pips = pips or {}
    pip2 = pip2 or set()
    return [{"cell": c, "type": types.get(c, "empty"),
             "pip": pips.get(c, 1 if types.get(c, "empty") != "empty" else 0),
             "pip2": c in pip2}
            for c in range(1, 16)]


def complete_types():
    t = dict(FIXED)                       # 3 predator + 5 light
    t[4] = "Bubble"
    t[5] = t[9] = t[10] = "Resonance"     # 3 resonance in n-cells
    t[13] = "Switch"                      # reserved switch
    t[14] = "Light"; t[15] = "Bubble"     # don't-care fill
    return t


class TestEvaluate(unittest.TestCase):
    def test_complete_board(self):
        self.assertTrue(evaluate(board_from(complete_types()))["complete"])

    def test_wrong_fixed_cell(self):
        t = complete_types(); t[1] = "Light"
        ev = evaluate(board_from(t))
        self.assertFalse(ev["complete"])
        self.assertTrue(any(v["kind"] == "wrong_type" and v["cell"] == 1
                            for v in ev["violations"]))

    def test_resonance_pip_must_match_predator(self):
        t = complete_types()
        p = {c: 1 for c in range(1, 16)}
        p[5] = 2  # a resonance at pip2 no longer counts -> short
        ev = evaluate(board_from(t, p))
        self.assertTrue(any(v["kind"] == "need_resonance" for v in ev["violations"]))

    def test_switch_not_required(self):
        t = complete_types(); t[13] = "Light"  # no switch anywhere
        self.assertTrue(evaluate(board_from(t))["complete"])


class TestPlan(unittest.TestCase):
    def test_complete_plans_nothing(self):
        self.assertIsNone(plan_next(board_from(complete_types())))

    def test_fishing_uses_skill_merge_destroy_pip1_pure(self):
        # fixed cells unmet, board full of surplus bubbles -> fish by MERGE+DESTROY
        # (skill) so no pip-2 die is left behind (user 2026-09-17 chose pip1-pure).
        t = {c: "Bubble" for c in range(1, 16)}
        a = plan_next(board_from(t), cheong_ready=True)
        self.assertEqual(a["op"], "merge_destroy")

    def test_fishing_waits_without_skill(self):
        # same board but the skill is on cooldown -> wait (never leave a pip-2 die)
        t = {c: "Bubble" for c in range(1, 16)}
        a = plan_next(board_from(t), cheong_ready=False)
        self.assertEqual(a["op"], "wait")

    def test_reserve_switch_never_merged(self):
        # classify reserves ONE switch (the arranging tool) -> when fishing, that
        # reserved switch is never the merge/destroy target (excess switches may be).
        t = {c: "Bubble" for c in range(1, 16)}; t[15] = "Switch"
        a = plan_next(board_from(t), cheong_ready=True)
        if a["op"] in ("merge", "merge_destroy", "destroy"):
            self.assertNotIn(15, (a.get("from"), a.get("to"), a.get("cell")))

    def test_summons_when_empty_and_no_pair(self):
        t = dict(FIXED)  # 8 filled distinct-ish, 7 empty, inventory short
        a = plan_next(board_from(t))
        self.assertEqual(a["op"], "summon")

    def test_full_short_no_pair_destroys_with_skill(self):
        # full board, short a light, NO mergeable surplus pair -> free ONE cell by
        # destroying a lone surplus with the skill (pip1-pure fishing, user 2026-09-17).
        # On cooldown it must WAIT rather than leave a pip-2 die.
        t = {1: "Predator", 2: "Light", 3: "Predator", 4: "Bubble", 5: "Resonance",
             6: "Light", 7: "Light", 8: "Light", 9: "Resonance", 10: "Resonance",
             11: "Predator", 12: "Light", 13: "Switch", 14: "Bubble", 15: "Switch"}
        p = {c: (1 if c not in (14, 15) else 2) for c in range(1, 16)}
        t[2] = "Bubble"; p[2] = 3              # short 1 light; surplus share no type+pip
        self.assertEqual(plan_next(board_from(t, p), cheong_ready=True)["op"], "destroy")
        self.assertEqual(plan_next(board_from(t, p), cheong_ready=False)["op"], "wait")

    def test_arrangement_uses_switch(self):
        # inventory satisfied but #1 holds a Light while the 3rd Predator sits in
        # a don't-care n-cell (#14); a switch (#13) is present -> plan a switch move.
        t = complete_types()
        t[1] = "Light"        # #1 wrong (should be Predator)
        t[14] = "Predator"    # 3rd predator parked in a don't-care cell
        # inventory: pred #3,#11,#14; light #1,#2,#6,#7,#8,#12; reson #5,#9,#10;
        # bubble #4,#15; switch #13 -> all satisfied
        a = plan_next(board_from(t))
        self.assertEqual(a["op"], "switch")


class TestBomb(unittest.TestCase):
    def test_bomb_removed_first(self):
        t = complete_types(); t[7] = "Bomb"    # bomb on a fixed light cell
        a = plan_next(board_from(t), cheong_ready=True)
        self.assertIn(a["op"], ("merge", "destroy"))
        if a["op"] == "merge":
            self.assertEqual(a["from"], 7)      # dragged FROM the bomb cell
        else:
            self.assertEqual(a["cell"], 7)

    def test_two_bombs_merge_destroy_as_pair(self):
        # merging two bombs yields a pip-2 die -> must merge+destroy to remove it
        # and keep the board pip-1 (user 2026-09-16).
        t = complete_types(); t[7] = "Bomb"; t[9] = "Bomb"   # two bombs
        a = plan_next(board_from(t), cheong_ready=True)
        self.assertEqual(a["op"], "merge_destroy")
        self.assertEqual({a["from"], a["to"]}, {7, 9})

    def test_bombs_wait_when_cheong_on_cd(self):
        t = complete_types(); t[7] = "Bomb"; t[9] = "Bomb"
        a = plan_next(board_from(t), cheong_ready=False)
        self.assertEqual(a["op"], "wait")           # don't merge into pip-2 leftover

    def test_odd_bomb_uses_skill(self):
        t = complete_types(); t[7] = "Bomb"                  # one (odd) bomb
        a = plan_next(board_from(t), cheong_ready=True)
        self.assertEqual(a["op"], "destroy")
        self.assertEqual(a["cell"], 7)

    def test_bomb_beats_arrangement(self):
        # even with other work to do, the bomb goes first
        t = complete_types(); t[1] = "Light"; t[14] = "Predator"; t[5] = "Bomb"
        a = plan_next(board_from(t))
        self.assertEqual(a.get("op") in ("merge", "destroy"), True)


class TestPip2Disabled(unittest.TestCase):
    # pip2->skill removal is DISABLED (unreliable live detector deleted good predators).
    # The planner must NOT fire the skill on a pip2 flag until detection is trustworthy.
    def test_pip2_predator_not_destroyed(self):
        t = complete_types(); t[1] = "Light"    # make it incomplete so a plan is returned
        a = plan_next(board_from(t, pip2={3}), cheong_ready=True)
        self.assertNotEqual((a or {}).get("why", ""), "skill: remove pip2 die")

    def test_pip2_resonance_not_destroyed(self):
        t = complete_types(); t[1] = "Light"
        a = plan_next(board_from(t, pip2={5}), cheong_ready=True)
        self.assertNotEqual((a or {}).get("why", ""), "skill: remove pip2 die")

    def test_fishing_never_merges_predators(self):
        # full board, extra predators as surplus, still short a light -> the fisher must
        # NOT merge two predators (합성금지: would make an unusable pip2 predator).
        t = {c: "Predator" for c in range(1, 16)}   # all predators (surplus galore)
        t[2] = "Bubble"                              # short on Light -> unmet
        a = plan_next(board_from(t), cheong_ready=True)
        if a and a.get("op") in ("merge", "merge_destroy"):
            self.assertNotEqual(board_from(t)[a["from"] - 1]["type"], "Predator")

    def test_fishing_never_merges_resonance(self):
        t = {c: "Resonance" for c in range(1, 16)}
        t[1] = "Bubble"                              # short on Predator
        a = plan_next(board_from(t), cheong_ready=True)
        if a and a.get("op") in ("merge", "merge_destroy"):
            self.assertNotEqual(board_from(t)[a["from"] - 1]["type"], "Resonance")


class TestClassify(unittest.TestCase):
    def test_reserves_one_switch(self):
        t = complete_types()
        keep, surplus, unmet = classify(board_from(t))
        self.assertEqual(sum(unmet.values()), 0)
        # the reserved switch at #13 is a keep, not surplus
        self.assertIn(13, keep)


class TestStickyLock(unittest.TestCase):
    """A confirmed-correct fixed cell must NEVER be disturbed, even when the current
    frame misreads it (bubble effect). This is the accuracy guarantee."""

    def test_locked_predator_not_swapped_out(self):
        # #1 truly holds a Predator but THIS frame misreads it as Light; a spare
        # predator sits at #5 and a switch at #13. Without the lock the planner
        # would walk the switch onto #1 to "fix" it, bouncing the real predator out.
        t = {1: "Light",          # misread of a locked Predator cell
             3: "Predator", 11: "Predator",
             2: "Light", 6: "Light", 7: "Light", 8: "Light", 12: "Light",
             5: "Predator",        # a spare predator elsewhere
             13: "Switch"}
        board = board_from(t)
        a = plan_next(board, locked=frozenset({1}))
        # the planner must not move anything into or out of the locked cell #1
        if a and a["op"] == "switch":
            self.assertNotIn(1, (a.get("from"), a.get("to")),
                             "locked predator cell #1 was disturbed")

    def test_without_lock_it_would_disturb(self):
        # same board, no lock -> the planner DOES target #1 (proves the lock matters)
        t = {1: "Light", 3: "Predator", 11: "Predator",
             2: "Light", 6: "Light", 7: "Light", 8: "Light", 12: "Light",
             5: "Predator", 13: "Switch"}
        a = plan_next(board_from(t))
        self.assertEqual(a["op"], "switch")
        self.assertIn(1, (a.get("from"), a.get("to")))


class TestArrangeConvergence(unittest.TestCase):
    """The switch arrangement must reach the EXACT layout (Predator #1,#3,#11 and
    Light #2,#6,#7,#8,#12) from any scrambled board whose inventory is satisfied,
    in bounded swaps -- no cannibalising correct cells, no oscillation."""

    @staticmethod
    def _scramble(seed):
        import random
        rng = random.Random(seed)
        deck = ["Predator", "Light", "Resonance", "Bubble", "Switch"]
        pool = (["Predator"] * 3 + ["Resonance"] * 3 + ["Light"] * 5
                + ["Bubble"] * 1 + ["Switch"] * 1)
        while len(pool) < 15:
            pool.append(rng.choice(deck))       # 2 junk
        rng.shuffle(pool)
        return [{"cell": i + 1, "type": t, "pip": 1} for i, t in enumerate(pool)]

    def _exact(self, board):
        bc = {c["cell"]: c for c in board}
        return all(bc[cell]["type"] == want for cell, want in FIXED.items())

    def test_converges_100pct(self):
        for seed in range(120):
            board = self._scramble(seed)
            for _ in range(200):
                if evaluate(board)["complete"] and self._exact(board):
                    break
                a = plan_next(board, cheong_ready=True, switch_ready=True)
                self.assertIsNotNone(a, f"seed {seed}: planner gave up early")
                bc = {c["cell"]: c for c in board}
                if a["op"] == "switch":          # swap the two cells
                    i, j = a["from"], a["to"]
                    bc[i]["type"], bc[j]["type"] = bc[j]["type"], bc[i]["type"]
                    bc[i]["pip"], bc[j]["pip"] = bc[j]["pip"], bc[i]["pip"]
                else:
                    self.fail(f"seed {seed}: unexpected {a['op']} (inventory OK)")
            self.assertTrue(evaluate(board)["complete"] and self._exact(board),
                            f"seed {seed}: did not converge to exact layout")


if __name__ == "__main__":
    unittest.main()
