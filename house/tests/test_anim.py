import unittest

from littlehouse import content as C
from littlehouse import scene as S
from littlehouse.anim import current_pose
from littlehouse.script import parse

from test_world import new_world


def start(w, src):
    """Submit a script in real time (no fast-forward)."""
    w.update()
    return w.runner.submit(parse(src))


def step(w, seconds):
    w.clock.advance(seconds)
    w.update()


class RouteTest(unittest.TestCase):
    def test_route_goes_through_doors(self):
        pts = S.route(["kitchen", "living_room", "yard"], (31, 5), (20, 16))
        self.assertEqual(pts[0], (31, 5))
        self.assertIn((26, 8), pts)
        self.assertIn((19.5, 13), pts)
        self.assertEqual(pts[-1], (20, 16))


class PoseTest(unittest.TestCase):
    def test_walking_is_drawn_where_she_really_is(self):
        w = new_world()
        start(w, "goto(沙滩)")
        p0 = current_pose(w)
        self.assertTrue(p0.walking)
        step(w, 3)
        p1 = current_pose(w)
        self.assertTrue(p1.walking)
        self.assertAlmostEqual(abs(p1.y - p0.y) + abs(p1.x - p0.x), 3 * C.WALK_TILES_PER_SEC, delta=0.6)
        self.assertEqual(w.location, "living_room")  # still on her way
        step(w, 60)
        p2 = current_pose(w)
        self.assertFalse(p2.walking)
        self.assertEqual(w.location, "beach")
        self.assertEqual((p2.x, p2.y), w.tile())

    def test_working_shows_the_effect_while_it_lasts(self):
        w = new_world()
        start(w, "goto(厨房); cook(煎蛋)")
        step(w, 30)  # past the walk: frying at the stove
        p = current_pose(w)
        self.assertEqual(p.effect, "steam")
        self.assertEqual(p.focus, "stove")
        step(w, 200)
        self.assertIsNone(current_pose(w).effect)
        self.assertIn("煎蛋", w.inventory)

    def test_resting_in_bed_is_drawn_asleep(self):
        w = new_world()
        start(w, "goto(卧室); rest(床)")
        step(w, 60)
        self.assertTrue(current_pose(w).asleep)

    def test_outside_free_time_she_sleeps_at_night(self):
        w = new_world(when=(2026, 10, 15, 2), free=False)
        for _ in range(10):
            step(w, 10)
        self.assertEqual(w.location, "bedroom")
        self.assertEqual(w.resident["idle"], "在床上睡觉")
        self.assertTrue(current_pose(w).asleep)


if __name__ == "__main__":
    unittest.main()
