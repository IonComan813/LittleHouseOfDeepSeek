import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

from littlehouse import content as C
from littlehouse.clock import Clock
from littlehouse.script import ScriptError, parse, run
from littlehouse.server import House, make_handler
from littlehouse.world import World


def clock_at(y, m, d, h=10, mi=0) -> Clock:
    c = Clock()
    c.advance(datetime(y, m, d, h, mi).timestamp() - c.timestamp())
    return c


def new_world(when=(2026, 10, 15, 10)) -> World:
    """A world pinned to a known autumn morning (season-dependent rules)."""
    return World(clock_at(*when), seed=1)


def ok(results):
    return all(r.ok for r in results)


def advance(w: World, hours: float) -> None:
    w.clock.advance(hours * 3600)
    w.tick()


class ParseTest(unittest.TestCase):
    def test_calls_and_separators(self):
        calls = parse('goto(厨房); look\nwater(pot#1) // comment\nsay("你好，世界")')
        self.assertEqual([c.name for c in calls], ["goto", "look", "water", "say"])
        self.assertEqual(calls[0].args, ["厨房"])
        self.assertEqual(calls[2].args, ["pot#1"])
        self.assertEqual(calls[3].args, ["你好，世界"])

    def test_fullwidth_punctuation(self):
        calls = parse("goto（庭院）；plant(萝卜种子，菜地1)")
        self.assertEqual([c.name for c in calls], ["goto", "plant"])
        self.assertEqual(calls[1].args, ["萝卜种子", "菜地1"])

    def test_numbers(self):
        self.assertEqual(parse("wait(3.5)")[0].args, [3.5])
        self.assertEqual(parse("pick(find#2)")[0].args, ["find#2"])

    def test_errors(self):
        for bad in ["goto(厨房", 'say("abc)', "(look)", "look() !! look()"]:
            with self.assertRaises(ScriptError, msg=bad):
                parse(bad)

    def test_limits(self):
        with self.assertRaises(ScriptError):
            parse("look;" * 30)


class MovementTest(unittest.TestCase):
    def test_goto_finds_a_path(self):
        w = new_world()
        res = run(w, "goto(厨房); goto(沙滩)")
        self.assertTrue(ok(res), res)
        self.assertIn("客厅", res[1].text)
        self.assertEqual(w.location, "beach")

    def test_stops_at_first_error(self):
        w = new_world()
        res = run(w, "goto(厨房); water(灶台); look()")
        self.assertEqual([r.ok for r in res], [True, False])

    def test_unknown_action(self):
        self.assertFalse(run(new_world(), "dance()")[0].ok)

    def test_look_mentions_status_and_hints(self):
        text = run(new_world(), "look()")[0].text
        for part in ("你：", "这里能做：", "背包：", "鱼竿"):
            self.assertIn(part, text)


class KitchenTest(unittest.TestCase):
    def test_cook_and_eat(self):
        w = new_world()
        w.resident["hunger"] = 80
        res = run(w, "goto(厨房); recipes(); cook(煎蛋); eat(煎蛋)")
        self.assertTrue(ok(res), res)
        self.assertIn("✓ 煎蛋", res[1].text)
        self.assertEqual(w.inventory["鸡蛋"], 1)
        self.assertLess(w.resident["hunger"], 80)
        self.assertNotIn("煎蛋", w.inventory)

    def test_missing_ingredients(self):
        w = new_world()
        res = run(w, "goto(厨房); cook(番茄炒蛋)")
        self.assertFalse(res[-1].ok)
        self.assertIn("番茄", res[-1].text)

    def test_cook_fish_by_tag(self):
        w = new_world()
        w.add_item("鲈鱼")
        self.assertTrue(ok(run(w, "goto(厨房); cook(烤鱼)")))
        self.assertIn("烤鱼", w.inventory)
        self.assertNotIn("鲈鱼", w.inventory)

    def test_cook_only_in_kitchen(self):
        self.assertFalse(run(new_world(), "cook(煎蛋)")[0].ok)

    def test_cannot_eat_raw_rice(self):
        self.assertFalse(run(new_world(), "eat(大米)")[0].ok)


class FarmTest(unittest.TestCase):
    def test_plant_water_grow_harvest(self):
        w = new_world()
        res = run(w, "goto(庭院); plant(萝卜种子); water()")
        self.assertTrue(ok(res), res)
        plot = w.objects["plot#1"]
        self.assertEqual(plot.state["seed"], "萝卜种子")
        for _ in range(8):  # keep it watered for a few days
            advance(w, 12)
            run(w, "water()")
        self.assertTrue(plot.state["ripe"], plot.state)
        self.assertTrue(any("成熟" in e.text for e in w.news_since("")))
        res = run(w, "harvest()")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.inventory["萝卜"], 2)

    def test_dry_soil_stops_growth(self):
        w = new_world()
        run(w, "goto(庭院); plant(萝卜种子, 菜地2)")
        w.objects["plot#2"].state["water"] = 0
        # skip rainy days: force dry weather for the test
        w.raining = lambda dt=None: False
        advance(w, 72)
        self.assertLess(w.objects["plot#2"].state.get("growth", 0), 0.5)

    def test_out_of_season(self):
        w = new_world()
        w.add_item("草莓种子")
        res = run(w, "goto(庭院); plant(草莓种子)")
        self.assertIn("不太适合", res[-1].text)

    def test_mail_arrives_daily(self):
        w = new_world()
        advance(w, 24)
        self.assertTrue(w.mailbox)
        res = run(w, "goto(庭院); open(邮箱)")
        self.assertTrue(ok(res), res)
        self.assertFalse(w.mailbox)


class BeachTest(unittest.TestCase):
    def test_pick_all_and_display(self):
        w = new_world()
        res = run(w, "goto(沙滩); pick(); goto(客厅); display()")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.shelf.get("白色扇贝壳"), 1)
        self.assertIn("1 件", res[-1].text)

    def test_finds_wash_up(self):
        w = new_world()
        run(w, "goto(沙滩); pick()")
        advance(w, 72)
        self.assertGreater(sum(1 for o in w.objects.values() if o.kind == "find"), 0)

    def test_fishing(self):
        w = new_world()
        w.raining = lambda dt=None: False
        w.weather = lambda dt=None: "晴"
        run(w, "goto(沙滩)")
        w.resident["energy"] = 100
        caught = 0
        for _ in range(20):
            w.resident["energy"] = 100
            r = run(w, "fish()")[0]
            self.assertTrue(r.ok, r)
        caught = sum(n for k, n in w.inventory.items() if k in C.ITEMS and ("fish" in C.ITEMS[k].tags or k in ("旧靴子", "漂流瓶")))
        self.assertGreater(caught, 0)

    def test_fishing_needs_rod(self):
        w = new_world()
        del w.inventory["鱼竿"]
        self.assertFalse(run(w, "goto(沙滩); fish()")[-1].ok)

    def test_read_bottle(self):
        w = new_world()
        w.add_item("漂流瓶")
        r = run(w, "read(漂流瓶)")[0]
        self.assertTrue(r.ok)
        self.assertIn("纸条", r.text)


class HouseworkTest(unittest.TestCase):
    def test_dirt_and_clean(self):
        w = new_world()
        advance(w, 24 * 7)
        self.assertIn("地上", run(w, "look()")[0].text)
        self.assertTrue(ok(run(w, "clean()")))
        self.assertEqual(w.dirt["living_room"], 0)

    def test_decorate(self):
        w = new_world()
        w.add_item("台灯")
        res = run(w, "goto(卧室); place(台灯); look()")
        self.assertTrue(ok(res), res)
        self.assertIn("台灯", res[-1].text)
        self.assertTrue(ok(run(w, "stow(台灯)")))
        self.assertEqual(w.inventory["台灯"], 1)

    def test_tired_blocks_effort(self):
        w = new_world()
        w.resident["energy"] = 0
        self.assertFalse(run(w, "clean()")[0].ok)
        self.assertTrue(run(w, "look()")[0].ok)  # free actions still work

    def test_rest_restores_energy_once_an_hour(self):
        w = new_world()
        w.resident["energy"] = 30
        run(w, "rest()")
        self.assertAlmostEqual(w.resident["energy"], 45, places=2)
        run(w, "rest()")
        self.assertAlmostEqual(w.resident["energy"], 45, places=2)


class CatTest(unittest.TestCase):
    def test_call_feed_pet(self):
        w = new_world()
        w.pet["room"] = "bedroom"
        w.pet["hunger"] = 90
        res = run(w, "call(); feed(); pet()")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.pet["room"], "living_room")
        self.assertLess(w.pet["hunger"], 50)
        self.assertEqual(w.inventory["猫粮"], 2)

    def test_cat_gets_hungry_and_news(self):
        w = new_world()
        advance(w, 24)
        self.assertTrue(any("喵喵" in e.text for e in w.news_since("")))


class TimeTest(unittest.TestCase):
    def test_needs_change_over_a_day(self):
        w = new_world()
        h0 = w.resident["hunger"]
        advance(w, 6)
        self.assertGreater(w.resident["hunger"], h0)

    def test_long_absence_is_bounded(self):
        w = new_world()
        advance(w, 24 * 60)  # two months away: must not loop forever or crash
        self.assertLessEqual(w.resident["hunger"], 100)


class SaveTest(unittest.TestCase):
    def test_roundtrip(self):
        w = new_world()
        run(w, "goto(庭院); plant(萝卜种子); goto(卧室)")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "world.json"
            w.save(p)
            w2 = new_world()
            self.assertTrue(w2.load(p))
            self.assertEqual(w2.location, "bedroom")
            self.assertEqual(w2.objects["plot#1"].state["seed"], "萝卜种子")
            self.assertEqual(w2.inventory, w.inventory)

    def test_migrate_v1_save(self):
        v1 = {
            "version": 1, "location": "yard", "inventory": ["shell#1"], "last_tick": 0, "next_item": 5,
            "objects": [
                {"id": "pot#1", "name": "绿萝", "kind": "plant", "room": "living_room", "state": {"water": 12.0}},
                {"id": "shell#1", "name": "白色扇贝壳", "kind": "shell", "room": "inventory", "state": {}},
            ],
        }
        w = new_world()
        w.load_json(v1)
        self.assertEqual(w.location, "yard")
        self.assertEqual(w.inventory.get("白色扇贝壳"), 1)
        self.assertEqual(w.objects["pot#1"].state["water"], 12.0)
        self.assertIn("plot#3", w.objects)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.house = House(Path(self.tmp.name), new_world())
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.house, "secret"))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def req(self, path, body=None, token="secret"):
        data = None if body is None else json.dumps(body).encode()
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data)
        if token:
            r.add_header("X-House-Token", token)
        if data is not None:
            r.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(r) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_auth(self):
        self.assertEqual(self.req("/health", token=None)[0], 200)
        self.assertEqual(self.req("/look", token=None)[0], 401)
        self.assertEqual(self.req("/look", token="wrong")[0], 401)

    def test_look_and_do(self):
        status, body = self.req("/look")
        self.assertEqual(status, 200)
        self.assertIn("客厅", body["text"])
        status, body = self.req("/do", {"script": "water(绿萝); goto(厨房)"})
        self.assertTrue(body["ok"], body)
        self.assertTrue((Path(self.tmp.name) / "events.jsonl").exists())
        status, body = self.req("/do", {"script": "goto("})
        self.assertFalse(body["ok"])

    def test_news_survives_restart(self):
        self.house.world.log("mail", "邮箱里来了包裹", actor="world")
        status, body = self.req("/news?since=2000-01-01T00:00:00")
        self.assertEqual([n["text"] for n in body["news"]], ["邮箱里来了包裹"])
        reloaded = House(Path(self.tmp.name), new_world())
        self.assertTrue(any(e.text == "邮箱里来了包裹" for e in reloaded.world.news_since("")))


if __name__ == "__main__":
    unittest.main()
