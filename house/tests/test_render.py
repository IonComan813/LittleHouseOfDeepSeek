import os
import unittest
from datetime import datetime

from littlehouse import content as C
from littlehouse.clock import Clock
from littlehouse.script import run
from littlehouse.world import World

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
try:
    from littlehouse import render
except ImportError:  # pygame-ce is optional
    render = None


def world_at(*when) -> World:
    c = Clock()
    c.advance(datetime(*when).timestamp() - c.timestamp())
    return World(c, seed=2)


@unittest.skipIf(render is None, "pygame-ce not installed")
class RenderTest(unittest.TestCase):
    def test_every_season_hour_and_weather(self):
        for month in (1, 4, 7, 10):
            for hour in (3, 6, 10, 18, 21):
                w = world_at(2026, month, 10, hour)
                for weather in ("晴", "多云", "阴", "小雨", "雷阵雨", "小雪"):
                    w.weather = lambda dt=None, wt=weather: wt
                    surf = render.render(w, t=1.0)
                    self.assertEqual(surf.get_size(), (render.W, render.H + render.S.HUD_H))

    def test_busy_house(self):
        w = world_at(2026, 10, 16, 10)
        for item in [n for n, it in C.ITEMS.items() if "furniture" in it.tags]:
            w.add_item(item)
        run(w, "place(小地毯); place(花瓶); place(懒人沙发); place(挂画); place(风铃); place(小书桌); place(台灯)")
        for i, item in enumerate(C.BEACH_FINDS):
            w._spawn_find(item[0])
        for seed, plot in zip(("番茄种子", "南瓜种子", "萝卜种子"), ("plot#1", "plot#2", "plot#3")):
            w.objects[plot].state.update(seed=seed, growth=2, ripe=plot == "plot#2")
        w.shelf = {"白色扇贝壳": 5, "粉色海螺": 4, "绿色海玻璃": 9}
        w.parcels = {"鸡蛋": 1}
        w.sale_box = {"萝卜": 2}
        for room in w.dirt:
            w.dirt[room] = 90
        png = render.render_png(w, 2)
        self.assertTrue(png.startswith(b"\x89PNG"))

    def test_resident_follows_focus(self):
        from littlehouse import scene as S

        w = world_at(2026, 10, 16, 10)
        run(w, "goto(厨房); examine(灶台)")
        x, y = S.resident_tile(w.location, w.resident.get("focus"), {})
        sx, sy, sw, sh = S.FIXTURES["stove"]
        self.assertEqual((x, y), (sx + sw // 2, sy + sh))


if __name__ == "__main__":
    unittest.main()
