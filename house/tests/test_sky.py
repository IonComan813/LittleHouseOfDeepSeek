import unittest
from datetime import datetime

from littlehouse import sky
from littlehouse.script import run

from test_world import new_world


class SkyTest(unittest.TestCase):
    def test_moon_phase_follows_the_real_calendar(self):
        # 2026: new moon on 9 November, full moon on 24 November
        self.assertEqual(sky.moon_phase(datetime(2026, 11, 9, 20)), "新月")
        self.assertEqual(sky.moon_phase(datetime(2026, 11, 14, 20)), "蛾眉月")
        self.assertEqual(sky.moon_phase(datetime(2026, 11, 24, 20)), "满月")
        self.assertGreater(sky.moon_light(datetime(2026, 11, 24, 20)), 0.9)
        self.assertTrue(sky.moon_up(datetime(2026, 11, 24, 23)))  # a full moon is up all night
        self.assertFalse(sky.moon_up(datetime(2026, 11, 24, 12)))

    def test_meteor_showers_on_their_nights(self):
        self.assertEqual(sky.meteor_shower(datetime(2026, 8, 12, 23)), "英仙座流星雨")
        self.assertEqual(sky.meteor_shower(datetime(2026, 12, 15, 2)), "双子座流星雨")  # after midnight: the 14th's night
        self.assertIsNone(sky.meteor_shower(datetime(2026, 11, 14, 22)))

    def test_stargaze(self):
        w = new_world(when=(2026, 8, 12, 22))
        res = run(w, "goto(庭院); stargaze()")
        self.assertTrue(res[-1].ok, res)
        self.assertIn("新月", res[-1].text)
        self.assertIn("stargaze", w.actions_here())
        seen = 0
        for seed in range(30):  # the Perseids: meteors on most nights that are not cloudy
            w.rng.seed(seed)
            seen += "流星" in run(w, "stargaze()")[0].text
        self.assertGreater(seen, 5)
        w = new_world()  # 10:00
        self.assertNotIn("stargaze", w.actions_here())
        self.assertIn("天还亮着", run(w, "goto(庭院); stargaze()")[-1].text)
        self.assertIn("到外面去", run(new_world(when=(2026, 8, 12, 22)), "stargaze()")[0].text)
