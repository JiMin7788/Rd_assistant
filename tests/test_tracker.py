"""Gate tests for the CellTracker (docs/07 Layer A).

Core guarantees:
- an effect burst (low-confidence frames) never changes a settled belief;
- a correct fixed Predator survives even a run of confident WRONG reads (K=8);
- a normal cell changes after a short stable streak (K=3);
- a switch is reflected immediately and self-repairs in one frame if it didn't take;
- a die on an empty cell (a summon) is accepted at once;
- merge/destroy frees the source cell;
- unseen / low-confidence cells report as uncertain (never moved).
"""
import unittest
from rdom.perception.tracker import CellTracker, ABSTAIN


def obs(spec):
    """15 observations; unspecified cells are abstained (conf 0.1) so they stay unseen.
    A spec value is (type, conf) or (type, conf, pip2)."""
    out = []
    for c in range(1, 16):
        if c in spec:
            v = spec[c]
            t, p = v[0], v[1]
            pip2 = v[2] if len(v) > 2 else False
        else:
            t, p, pip2 = "empty", 0.1, False
        out.append({"cell": c, "type": t, "conf": p, "pip2": pip2})
    return out


class TestTracker(unittest.TestCase):
    def test_effect_burst_does_not_change_belief(self):
        tr = CellTracker()
        tr.update(obs({1: ("Predator", 0.95)}))
        self.assertEqual(tr.belief[1], "Predator")
        for _ in range(10):                       # 10 glow frames read a low-conf wrong type
            tr.update(obs({1: ("Light", ABSTAIN - 0.05)}))
        self.assertEqual(tr.belief[1], "Predator")

    def test_correct_predator_survives_confident_wrong_run(self):
        tr = CellTracker()
        tr.update(obs({1: ("Predator", 0.95)}))
        for i in range(7):                         # 7 confident WRONG reads: still Predator
            tr.update(obs({1: ("Light", 0.9)}))
            self.assertEqual(tr.belief[1], "Predator", f"flipped early at {i}")
        tr.update(obs({1: ("Light", 0.9)}))       # 8th (K_PROTECT) -> a real change
        self.assertEqual(tr.belief[1], "Light")

    def test_normal_cell_changes_after_k3(self):
        tr = CellTracker()
        tr.update(obs({5: ("Resonance", 0.95)}))
        tr.update(obs({5: ("Bubble", 0.9)})); self.assertEqual(tr.belief[5], "Resonance")
        tr.update(obs({5: ("Bubble", 0.9)})); self.assertEqual(tr.belief[5], "Resonance")
        tr.update(obs({5: ("Bubble", 0.9)})); self.assertEqual(tr.belief[5], "Bubble")

    def test_switch_reflected_immediately(self):
        tr = CellTracker()
        tr.update(obs({1: ("Light", 0.95), 5: ("Predator", 0.95)}))
        tr.update(obs({}), last_action={"op": "switch", "from": 5, "to": 1})
        self.assertEqual(tr.belief[1], "Predator")
        self.assertEqual(tr.belief[5], "Light")

    def test_switch_that_did_not_take_repairs_in_one_frame(self):
        tr = CellTracker()
        tr.update(obs({1: ("Light", 0.95), 5: ("Predator", 0.95)}))
        # swap applied optimistically, but the game rejected it -> next frame still old
        tr.update(obs({1: ("Light", 0.95), 5: ("Predator", 0.95)}),
                  last_action={"op": "switch", "from": 5, "to": 1})
        self.assertEqual(tr.belief[1], "Light")
        self.assertEqual(tr.belief[5], "Predator")

    def test_summon_fills_empty_in_one_frame(self):
        tr = CellTracker()
        tr.update(obs({4: ("empty", 1.0)}))
        self.assertEqual(tr.belief[4], "empty")
        tr.update(obs({4: ("Bubble", 0.9)}))
        self.assertEqual(tr.belief[4], "Bubble")

    def test_merge_frees_source_cell(self):
        tr = CellTracker()
        tr.update(obs({4: ("Bubble", 0.95), 5: ("Bubble", 0.95)}))
        tr.update(obs({}), last_action={"op": "merge", "from": 4, "to": 5})
        self.assertEqual(tr.belief[4], "empty")

    def test_destroy_frees_cell(self):
        tr = CellTracker()
        tr.update(obs({7: ("Bomb", 1.0)}))
        tr.update(obs({}), last_action={"op": "destroy", "cell": 7})
        self.assertEqual(tr.belief[7], "empty")

    def test_uncertain_lists_unseen_cells(self):
        tr = CellTracker()
        tr.update(obs({1: ("Predator", 0.95)}))
        u = tr.uncertain()
        self.assertNotIn(1, u)
        self.assertIn(2, u)               # never observed -> uncertain

    def test_pip2_needs_k_consecutive_frames(self):
        from rdom.perception.tracker import CellTracker as CT
        tr = CT()
        tr.update(obs({5: ("Resonance", 0.95)}))
        for i in range(CT.PIP2_K - 1):                  # not yet believed
            tr.update(obs({5: ("Resonance", 0.95, True)}))
            self.assertFalse(tr.pip2[5], f"believed too early at {i}")
        tr.update(obs({5: ("Resonance", 0.95, True)}))  # K-th frame
        self.assertTrue(tr.pip2[5])

    def test_pip2_cleared_by_a_clean_pip1_frame(self):
        from rdom.perception.tracker import CellTracker as CT
        tr = CT()
        tr.update(obs({5: ("Resonance", 0.95)}))
        for _ in range(CT.PIP2_K):
            tr.update(obs({5: ("Resonance", 0.95, True)}))
        self.assertTrue(tr.pip2[5])
        tr.update(obs({5: ("Resonance", 0.95, False)}))  # one clean pip1 read
        self.assertFalse(tr.pip2[5])

    def test_pip2_reset_on_type_change_and_free(self):
        from rdom.perception.tracker import CellTracker as CT
        tr = CT()
        tr.update(obs({4: ("Bubble", 0.95)}))
        for _ in range(CT.PIP2_K):
            tr.update(obs({4: ("Bubble", 0.95, True)}))
        self.assertTrue(tr.pip2[4])
        tr.update(obs({}), last_action={"op": "destroy", "cell": 4})
        self.assertFalse(tr.pip2[4])

    def test_switch_pip2_never_surfaced_to_planner(self):
        tr = CellTracker()
        tr.update(obs({13: ("Switch", 0.95)}))
        # even if pip2 somehow set, belief_board must not flag a Switch as pip2
        tr.pip2[13] = True
        b = {c["cell"]: c for c in tr.belief_board()}
        self.assertFalse(b[13]["pip2"])

    def test_belief_board_shape(self):
        tr = CellTracker()
        tr.update(obs({1: ("Predator", 0.95)}))
        b = tr.belief_board()
        self.assertEqual(len(b), 15)
        self.assertEqual(b[0]["type"], "Predator")
        self.assertEqual(b[0]["pip"], 1)
        self.assertEqual(b[1]["type"], "empty")   # unseen -> empty for planning


if __name__ == "__main__":
    unittest.main()
