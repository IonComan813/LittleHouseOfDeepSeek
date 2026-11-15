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
        res = run(w, "goto(庭院); look_at_sky()")
        self.assertTrue(res[-1].ok, res)
        self.assertIn("新月", res[-1].text)
        self.assertIn("look_at_sky", w.actions_here())
        seen = 0
        for seed in range(30):  # the Perseids: meteors on most nights that are not cloudy
            w.rng.seed(seed)
            seen += "流星" in run(w, "look_at_sky()")[0].text
        self.assertGreater(seen, 5)
        w = new_world()  # 10:00
        self.assertNotIn("look_at_sky", w.actions_here())
        self.assertIn("天还亮着", run(w, "goto(庭院); look_at_sky()")[-1].text)
        self.assertIn("到外面去", run(new_world(when=(2026, 8, 12, 22)), "look_at_sky()")[0].text)

    def test_wade_and_the_light_on_the_sea(self):
        w = new_world(when=(2026, 11, 14, 17))
        res = run(w, "goto(沙滩); play_in_water()")
        self.assertTrue(res[-1].ok, res)
        self.assertIn("夕阳", res[-1].text)
        self.assertIn("这件事要在沙滩做", run(new_world(), "play_in_water()")[0].text)

    def wade(self, when, seed=0):
        w = new_world(when=when)
        w.rng.seed(seed)
        res = run(w, "goto(沙滩); play_in_water()")
        self.assertTrue(res[-1].ok, res)
        return w, res[-1].text

    def test_the_water_is_warm_on_a_sunny_afternoon(self):
        from littlehouse import content as C
        w, text = self.wade((2026, 7, 20, 15))  # a sunny summer day
        self.assertEqual(w.weather(), "晴")
        self.assertTrue(text.startswith(C.WATER_FEEL["summer"][0]), text)
        w, text = self.wade((2026, 7, 20, 9))  # the same day in the morning
        self.assertTrue(text.startswith(C.WATER_FEEL["summer"][1]), text)
        w, text = self.wade((2026, 11, 24, 15))  # rain: never warm
        self.assertEqual(w.weather(), "小雨")
        self.assertTrue(text.startswith(C.WATER_FEEL_WEATHER["小雨"]), text)

    def test_the_moonlight_names_no_phase_but_the_full_moon_gets_more(self):
        from littlehouse import sky
        phases = {p for p, _, _ in sky.PHASES} - {"满月"}
        _, text = self.wade((2026, 11, 15, 21))  # a waxing moon, still up
        self.assertIn("月光", text)
        self.assertFalse([p for p in phases if p in text], text)
        w, full = self.wade((2026, 11, 25, 22))
        self.assertEqual((w.weather(), sky.moon_phase(w.now())), ("晴", "满月"))
        self.assertIn("月亮圆圆的", full)
        self.assertGreater(len(full), len(text))

    def test_fish_come_by_sometimes(self):
        from littlehouse import content as C
        names = [who for who, _, _ in C.SHALLOW_FISH]
        seen = sum(any(n in self.wade((2026, 7, 20, 15), seed)[1] for n in names) for seed in range(40))
        self.assertTrue(5 < seen < 35, seen)
        dark = sum(C.FISH_IN_THE_DARK in self.wade((2026, 11, 15, 21), seed)[1] for seed in range(40))
        self.assertGreater(dark, 0)  # at night (not full moon) she cannot see what it was
        for seed in range(20):  # winter: only what lives there in winter
            text = self.wade((2027, 1, 12, 14), seed)[1]
            self.assertNotIn("沙丁鱼", text)

    def test_fishing_in_everyday_life_needs_the_rod(self):
        from littlehouse import content as C
        w = new_world(when=(2026, 10, 15, 14), free=False)
        act = next(a for a in C.IDLE_ACTIVITIES if a.story == "fish")
        self.assertEqual(w.idle_room(act), "beach")
        del w.inventory["鱼竿"]
        self.assertIsNone(w.idle_room(act))
