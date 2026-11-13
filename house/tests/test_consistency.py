"""The picture and the words must describe the same things."""

import unittest

from littlehouse import content as C
from littlehouse import scene as S
from littlehouse.script import run
from littlehouse.world import World


class ConsistencyTest(unittest.TestCase):
    def test_everything_drawn_has_an_appearance(self):
        drawn = set(S.FIXTURES) | set(S.EXTRAS)
        drawn -= {"catalog", "plot#1", "plot#2", "plot#3"}  # catalog is described in the room text; plots by state
        missing = sorted(k for k in drawn if k not in C.APPEARANCE)
        self.assertEqual(missing, [], "drawn but not described")

    def test_every_furniture_item_has_an_appearance(self):
        furniture = [n for n, it in C.ITEMS.items() if "furniture" in it.tags]
        for name in furniture:
            self.assertIn(name, C.APPEARANCE)
            self.assertEqual(C.ITEMS[name].desc, C.APPEARANCE[name])

    def test_scenery_is_a_real_object_you_can_examine(self):
        w = World(seed=1)
        for oid, (name, room) in C.SCENERY.items():
            self.assertIn(oid, w.objects)
            room_name = C.ROOMS[room].name
            res = run(w, f"goto({room_name}); examine({name})")
            self.assertTrue(all(r.ok for r in res), res)
            self.assertEqual(res[-1].text, C.APPEARANCE[oid])
            self.assertIn(name, C.ROOMS[room].description.replace("水槽的台面", "水槽"))

    def test_examine_fixtures(self):
        w = World(seed=1)
        self.assertIn("红色", run(w, "examine(沙发)")[0].text)
        res = run(w, "goto(庭院); examine(邮箱)")
        self.assertTrue(res[-1].ok, res)
        self.assertIn("信", res[-1].text)


if __name__ == "__main__":
    unittest.main()
