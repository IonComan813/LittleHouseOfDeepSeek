import unittest

from littlehouse import scene as S
from littlehouse.anim import EFFECT_SECONDS, Animator, snapshot_pose
from littlehouse.script import run
from littlehouse.world import World


class RouteTest(unittest.TestCase):
    def test_route_goes_through_doors(self):
        pts = S.route(["kitchen", "living_room", "yard"], (31, 5), (20, 16))
        self.assertEqual(pts[0], (31, 5))
        self.assertIn((26, 8), pts)
        self.assertIn((19.5, 13), pts)
        self.assertEqual(pts[-1], (20, 16))

    def test_beats_record_walks(self):
        w = World(seed=1)
        run(w, "goto(沙滩); fish()")
        goto, fish = w.beats[-2:]
        self.assertEqual(goto["action"], "goto")
        self.assertGreater(len(goto["waypoints"]), 3)
        self.assertEqual(fish["focus"], "rock")
        self.assertEqual(w.tile(), tuple(map(float, fish["waypoints"][-1])))

    def test_failed_action_records_no_beat(self):
        w = World(seed=1)
        n = len(w.beats)
        run(w, "water(沙发)")
        self.assertEqual(len(w.beats), n)


class PoseTest(unittest.TestCase):
    def test_still_picture_freezes_latest_action(self):
        w = World(seed=1)
        run(w, "goto(庭院); water()")
        pose = snapshot_pose(w)
        self.assertEqual(pose.effect, "water")
        self.assertTrue(pose.active)
        self.assertEqual((pose.x, pose.y), w.tile())

    def test_old_actions_are_not_shown(self):
        w = World(seed=1)
        run(w, "goto(庭院); water()")
        pose = snapshot_pose(w, now=w.beats[-1]["t"] + 3600)
        self.assertIsNone(pose.effect)

    def test_animator_walks_then_acts_then_rests(self):
        w = World(seed=1)
        anim = Animator(w)
        run(w, "goto(厨房); cook(煎蛋)")
        anim.feed(w.beats)
        t0 = 100.0
        anim.pose(w, t0)
        p = anim.pose(w, t0 + 0.3)
        self.assertTrue(p.walking)
        seen = set()
        t = t0
        while t < t0 + 30:
            p = anim.pose(w, t)
            seen.add(p.effect)
            t += 0.2
        self.assertIn("steam", seen)
        self.assertFalse(p.walking)
        self.assertEqual((p.x, p.y), w.tile())

    def test_backlog_plays_faster(self):
        w = World(seed=1)
        anim = Animator(w)
        for _ in range(5):
            run(w, "goto(沙滩); goto(卧室)")
        anim.feed(w.beats)
        t, t0 = 0.0, 0.0
        while anim.queue or anim.current is not None:
            anim.pose(w, t0 + t)
            t += 0.1
            self.assertLess(t, 40)
        self.assertLess(t, 15)

    def test_animator_does_not_replay_history(self):
        w = World(seed=1)
        run(w, "goto(沙滩)")
        anim = Animator(w)
        anim.feed(w.beats)
        self.assertFalse(anim.queue)


if __name__ == "__main__":
    unittest.main()
