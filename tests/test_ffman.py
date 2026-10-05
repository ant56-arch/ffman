import unittest

from ffman.models import Lineup, Player, Team, eligible_slots
from ffman.optimizer import optimal_lineup
from ffman.providers import espn, sleeper
from ffman.report import analyze, render


def player(pid, pos, proj, status=None):
    return Player(pid, f"Player {pid}", pos, "KC", eligible_slots({pos}), proj, status)


def team(slots, roster, current_ids):
    by_id = {p.id: p for p in roster}
    return Team("Test", "League", "Mine", 5, slots, roster,
                Lineup(slots, [by_id.get(i) for i in current_ids]))


class OptimizerTests(unittest.TestCase):
    def test_flex_takes_best_remaining(self):
        roster = [player("rb1", "RB", 15), player("rb2", "RB", 12), player("wr1", "WR", 14),
                  player("wr2", "WR", 9), player("te1", "TE", 8)]
        best = optimal_lineup(team(["RB", "WR", "TE", "FLEX"], roster, []))
        self.assertEqual([p.id for p in best.players], ["rb1", "wr1", "te1", "rb2"])

    def test_superflex_uses_second_qb(self):
        roster = [player("qb1", "QB", 22), player("qb2", "QB", 18), player("wr1", "WR", 10)]
        best = optimal_lineup(team(["QB", "WR", "SUPER_FLEX"], roster, []))
        self.assertEqual([p.id for p in best.players], ["qb1", "wr1", "qb2"])

    def test_non_nested_flex_slots_are_solved_exactly(self):
        # Greedy would put wr1 in REC_FLEX and leave WRRB_FLEX worse off.
        roster = [player("wr1", "WR", 20), player("te1", "TE", 10), player("rb1", "RB", 1)]
        best = optimal_lineup(team(["WRRB_FLEX", "REC_FLEX"], roster, []))
        self.assertAlmostEqual(best.total, 30)

    def test_out_player_is_benched(self):
        roster = [player("wr1", "WR", 18, "Out"), player("wr2", "WR", 7)]
        best = optimal_lineup(team(["WR"], roster, ["wr1"]))
        self.assertEqual(best.players[0].id, "wr2")

    def test_ties_keep_current_starter(self):
        roster = [player("a", "WR", 10), player("b", "WR", 10)]
        best = optimal_lineup(team(["WR"], roster, ["b"]))
        self.assertEqual(best.players[0].id, "b")

    def test_unfillable_slot_left_empty(self):
        best = optimal_lineup(team(["QB", "K"], [player("qb", "QB", 20)], []))
        self.assertIsNone(best.players[1])


class ReportTests(unittest.TestCase):
    def test_recommends_swap_and_warns(self):
        roster = [player("wr1", "WR", 18, "Out"), player("wr2", "WR", 7),
                  player("te1", "TE", 9, "Questionable")]
        report = analyze(team(["WR", "TE"], roster, ["wr1", "te1"]))
        self.assertTrue(report.needs_changes)
        self.assertEqual([(s.id, b.id) for s, b in report.start], [("wr2", "wr1")])
        self.assertTrue(any("Questionable" in w for w in report.warnings))
        text = render([report], 5)
        self.assertIn("START Player wr2", text)
        self.assertIn("1 of 1 leagues have changes", text)

    def test_small_gain_is_not_flagged(self):
        roster = [player("a", "WR", 10), player("b", "WR", 10.2)]
        report = analyze(team(["WR"], roster, ["a"]), min_gain=0.5)
        self.assertFalse(report.needs_changes)
        self.assertIn("No changes needed", render([report]))


class SleeperTests(unittest.TestCase):
    def test_build_team(self):
        league = {
            "name": "Dynasty",
            "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "DEF", "BN", "BN", "IR"],
            "scoring_settings": {"pass_yd": 0.04, "pass_td": 4, "rush_yd": 0.1, "rec": 1,
                                 "rec_yd": 0.1, "bonus_rec_te": 0.5},
        }
        roster = {"players": ["1", "2", "3", "4", "5", "6", "KC", "9"],
                  "starters": ["1", "2", "3", "4", "5", "KC"], "reserve": ["9"],
                  "metadata": {"team_name": "Bros"}}
        players = {
            "1": {"full_name": "QB One", "position": "QB", "fantasy_positions": ["QB"], "team": "BUF"},
            "2": {"full_name": "RB One", "position": "RB", "fantasy_positions": ["RB"], "team": "SF",
                  "injury_status": "Out"},
            "3": {"full_name": "WR One", "position": "WR", "fantasy_positions": ["WR"], "team": "MIA"},
            "4": {"full_name": "TE One", "position": "TE", "fantasy_positions": ["TE"], "team": "KC"},
            "5": {"full_name": "WR Two", "position": "WR", "fantasy_positions": ["WR"], "team": "DET"},
            "6": {"full_name": "RB Two", "position": "RB", "fantasy_positions": ["RB"], "team": "DAL"},
            "KC": {"first_name": "Kansas City", "last_name": "Chiefs", "position": "DEF",
                   "fantasy_positions": ["DEF"], "team": "KC"},
            "9": {"full_name": "Hurt Guy", "position": "RB", "fantasy_positions": ["RB"]},
        }
        projections = {
            "1": {"pass_yd": 250, "pass_td": 2},          # 18
            "2": {"rush_yd": 90},                          # 9 but Out
            "3": {"rec": 6, "rec_yd": 80},                 # 14
            "4": {"rec": 4, "rec_yd": 40, "bonus_rec_te": 4},  # 8 + 2 TE premium
            "5": {"rec": 3, "rec_yd": 30},                 # 6
            "6": {"rush_yd": 70, "rec": 2, "rec_yd": 10},  # 10
            "KC": {"pts_ppr": 7.0, "gp": 1},               # fallback to pts_ppr
        }
        # Live status from the projections feed overrides the cached player file.
        t = sleeper.build_team(league, roster, players, projections, 5, {"3": "Questionable"})
        self.assertEqual(t.slots, ["QB", "RB", "WR", "TE", "FLEX", "DEF"])
        self.assertNotIn("9", [p.id for p in t.roster])
        by_id = {p.id: p for p in t.roster}
        self.assertAlmostEqual(by_id["1"].projection, 18)
        self.assertAlmostEqual(by_id["4"].projection, 10)
        self.assertAlmostEqual(by_id["KC"].projection, 7)
        self.assertEqual(by_id["KC"].name, "Kansas City Chiefs")
        self.assertEqual(by_id["3"].injury_status, "Questionable")

        report = analyze(t)
        best = {slot: p.id for slot, p in zip(report.best.slots, report.best.players)}
        self.assertEqual(best["RB"], "6")
        self.assertEqual(best["FLEX"], "5")
        self.assertEqual([(s.id, b.id) for s, b in report.start], [("6", "2")])


class EspnTests(unittest.TestCase):
    def entry(self, pid, name, pos_id, slots, lineup_slot, proj, status="ACTIVE"):
        return {"lineupSlotId": lineup_slot, "playerPoolEntry": {"player": {
            "id": pid, "fullName": name, "defaultPositionId": pos_id, "eligibleSlots": slots,
            "proTeamId": 12, "injuryStatus": status,
            "stats": [{"statSourceId": 0, "scoringPeriodId": 5, "appliedTotal": 99},
                      {"statSourceId": 1, "scoringPeriodId": 5, "appliedTotal": proj}]}}}

    def test_build_team(self):
        data = {
            "scoringPeriodId": 5,
            "settings": {"name": "Work", "rosterSettings": {"lineupSlotCounts": {
                "0": 1, "2": 1, "4": 1, "23": 1, "20": 3, "21": 1}}},
            "teams": [
                {"id": 1, "name": "Other", "owners": ["{X}"], "roster": {"entries": []}},
                {"id": 3, "location": "Big", "nickname": "Dogs", "owners": ["{ABC}"], "roster": {"entries": [
                    self.entry(10, "Quarter Back", 1, [0, 7, 20, 21], 0, 20.5),
                    self.entry(11, "Run Ner", 2, [2, 3, 23, 7, 20, 21], 2, 4.0, "DOUBTFUL"),
                    self.entry(12, "Wide Out", 3, [3, 4, 5, 23, 7, 20, 21], 4, 12.0),
                    self.entry(13, "Bench Back", 2, [2, 3, 23, 7, 20, 21], 20, 11.0),
                    self.entry(14, "Bench Wide", 3, [3, 4, 5, 23, 7, 20, 21], 23, 8.0),
                    self.entry(15, "Injured", 3, [3, 4, 5, 23, 7, 20, 21], 21, 30.0),
                ]}},
            ],
        }
        t = espn.build_team(data, {"league_id": 1, "swid": "{abc}"}, 5)
        self.assertEqual(t.team_name, "Big Dogs")
        self.assertEqual(t.slots, ["QB", "RB", "WR", "FLEX"])
        self.assertNotIn("15", [p.id for p in t.roster])
        self.assertEqual([p.name for p in t.current.players],
                         ["Quarter Back", "Run Ner", "Wide Out", "Bench Wide"])
        self.assertEqual(t.current.players[0].projection, 20.5)
        self.assertEqual(t.current.players[0].team, "KC")

        report = analyze(t)
        self.assertEqual([(s.name, b.name) for s, b in report.start], [("Bench Back", "Run Ner")])

    def test_team_id_overrides_swid(self):
        data = {"settings": {"rosterSettings": {"lineupSlotCounts": {}}},
                "teams": [{"id": 1, "name": "A", "roster": {"entries": []}}]}
        self.assertEqual(espn.build_team(data, {"league_id": 1, "team_id": 1}, 5).team_name, "A")


if __name__ == "__main__":
    unittest.main()
