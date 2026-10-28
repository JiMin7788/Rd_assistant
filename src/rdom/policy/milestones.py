"""Support-deck milestone tracker. Pure, no I/O (the caller takes screenshots and writes the log).

Milestones (name, score limit, min Resonance 7, min Alignment 7, min Bubbles): the board condition
must first hold while the last confirmed score is still below the limit ("reached"); first holding
at or above the limit is "late" and does not count. Before any confirmed score the score is
unknown (None) and counts as 0. Crossings record the board counts when the score first passes
2000/3000/4000, for the human to check against the screenshot.
"""
from __future__ import annotations

MILESTONES = (("m1", 2000, 1, 1, 0), ("m2", 3000, 2, 1, 0), ("m3", 4000, 2, 3, 2))
CROSSINGS = (2000, 3000, 4000)


def _counts_text(res7, align7, bubbles):
    return f"(Res7 {res7}, Align7 {align7}, Bubble {bubbles})"


class MilestoneTracker:
    def __init__(self):
        self.score = None                    # last confirmed score
        self.max_score = 0
        self.scores_confirmed = 0
        self._counts = (0, 0, 0)             # res7, align7, bubbles of the last on_board call
        self._ms = {m[0]: {"reached": False, "late": False, "score": None, "shot": None,
                           "done": False} for m in MILESTONES}
        self._cr = {c: {"res7": None, "align7": None, "bubbles": None, "score": None,
                        "shot": None} for c in CROSSINGS}
        self._crossed = set()

    def on_score(self, score):
        """Feed a confirmed score; returns the crossing events it triggers (in limit order)."""
        self.score = score
        self.scores_confirmed += 1
        self.max_score = max(self.max_score, score)
        events = []
        for limit in CROSSINGS:
            if limit in self._crossed or score < limit:
                continue
            self._crossed.add(limit)
            res7, align7, bubbles = self._counts
            self._cr[limit].update(res7=res7, align7=align7, bubbles=bubbles, score=score)
            events.append({"kind": "crossing", "limit": limit, "score": score, "res7": res7,
                           "align7": align7, "bubbles": bubbles,
                           "log": f"score crossed {limit} {_counts_text(res7, align7, bubbles)}"})
        return events

    def on_board(self, counts):
        """Feed confirmed counts {res7, align7, bubbles}; returns newly resolved milestone events."""
        res7, align7, bubbles = counts["res7"], counts["align7"], counts["bubbles"]
        self._counts = (res7, align7, bubbles)
        events = []
        for name, limit, need_res, need_align, need_bub in MILESTONES:
            st = self._ms[name]
            if st["done"] or res7 < need_res or align7 < need_align or bubbles < need_bub:
                continue
            st["done"] = True
            # AI-NOTE: an unknown score (no on_score yet) counts as 0, so it is never late.
            late = self.score is not None and self.score >= limit
            st.update(reached=not late, late=late, score=self.score)
            shown = "?" if self.score is None else self.score
            word = "late" if late else "reached"
            events.append({"kind": "milestone", "name": name, "score": self.score, "late": late,
                           "log": f"milestone {name} {word} at score {shown} "
                                  f"{_counts_text(res7, align7, bubbles)}"})
        return events

    def set_shot(self, event, path):
        """Store the screenshot path for an event returned by on_score/on_board."""
        if event["kind"] == "milestone":
            self._ms[event["name"]]["shot"] = path
        else:
            self._cr[event["limit"]]["shot"] = path

    def record(self):
        return {
            "milestones": {n: {k: s[k] for k in ("reached", "late", "score", "shot")}
                           for n, s in self._ms.items()},
            "crossings": {str(c): dict(v) for c, v in self._cr.items()},
            "max_score": self.max_score,
            "scores_confirmed": self.scores_confirmed,
        }
