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


def clock_at(y, m, d, h=10, mi=0, scale=1.0) -> Clock:
    c = Clock(scale=scale)
    c.advance(datetime(y, m, d, h, mi).timestamp() - c.timestamp())
    return c


def new_world(when=(2026, 10, 15, 10), free=True, scale=1.0) -> World:
    """A world pinned to a known autumn morning (season-dependent rules).

    ``free``: in her free time (the agent decides what she does) for the whole
    test, so the off-hours routine does not walk her around between steps.
    """
    w = World(clock_at(*when, scale=scale), seed=1)
    if free:
        w.resident["free_until"] = w.clock.timestamp() + 365 * 86400
    return w


def ok(results):
    return all(r.ok for r in results)


def advance(w: World, hours: float) -> None:
    """Skip time as if she had been living her everyday life meanwhile (outside
    free time: she sleeps at night and grabs a bite), staying where she is."""
    free_until = w.resident.get("free_until", 0.0)
    w.resident["free_until"] = 0.0
    w.clock.advance(hours * 3600)
    w.tick()
    if free_until:
        w.resident["free_until"] = w.clock.timestamp() + 365 * 86400


class ParseTest(unittest.TestCase):
    def test_calls_and_separators(self):
        calls = parse('goto(厨房); surroundings\nwater(pot#1) // comment\nsay("你好，世界")')
        self.assertEqual([c.name for c in calls], ["goto", "surroundings", "water", "say"])
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
        res = run(w, "goto(厨房); water(灶台); surroundings()")
        self.assertEqual([r.ok for r in res], [True, False])

    def test_unknown_action(self):
        with self.assertRaises(ScriptError):
            run(new_world(), "dance()")

    def test_names_must_be_whole(self):
        w = new_world()
        res = run(w, "goto(庭院); plant(萝卜)")
        self.assertFalse(res[-1].ok)
        self.assertIn("你是不是说萝卜种子", res[-1].text)
        self.assertFalse(w.objects["plot#1"].state.get("seed"))
        w.add_item("萝卜")
        res = run(w, "plant(萝卜)")  # the vegetable, not the seed
        self.assertIn("你是不是想种萝卜种子？那就写 plant(萝卜种子)", res[0].text)
        self.assertIn("你是不是说菜地1", run(w, "water(菜地)")[0].text)
        self.assertIn("番茄种子", run(w, "goto(客厅); order(番茄种)")[-1].text)
        self.assertTrue(ok(run(w, "goto(庭院); plant(萝卜种子, 菜地1)")))

    def test_one_wrong_step_and_nothing_runs(self):
        w = new_world()
        with self.assertRaises(ScriptError) as e:
            run(w, "goto(厨房); look(); cook(白米饭); go(沙滩)")
        msg = str(e.exception)
        self.assertIn("一步都没有执行", msg)
        self.assertIn("第 2 步：没有「look」这个动作。你是不是想用 surroundings()？", msg)
        self.assertIn("第 4 步：没有「go」这个动作。你是不是想用 goto(地点)？", msg)
        self.assertEqual(w.location, "living_room")  # not even the first step ran
        with self.assertRaises(ScriptError) as e:
            run(w, "harvst()")  # a typo
        self.assertIn("harvest(菜地)", str(e.exception))

    def test_look_mentions_status_and_hints(self):
        text = run(new_world(), "surroundings()")[0].text
        for part in ("你：", "这里能做：", "背包：", "鱼竿"):
            self.assertIn(part, text)


class KitchenTest(unittest.TestCase):
    def test_cook_and_eat(self):
        w = new_world()
        w.resident["hunger"] = 80
        res = run(w, "goto(厨房); recipes(); cook(荷包蛋); eat(荷包蛋)")
        self.assertTrue(ok(res), res)
        self.assertIn("✓ 荷包蛋", res[1].text)
        self.assertEqual(w.inventory["鸡蛋"], C.START_INVENTORY["鸡蛋"] - 1)
        self.assertLess(w.resident["hunger"], 80)
        self.assertNotIn("荷包蛋", w.inventory)

    def test_menu(self):
        for dish in ("白米饭", "荷包蛋", "红烧肉"):
            self.assertIn(dish, C.RECIPES)
        self.assertGreaterEqual(len(C.RECIPES), 12)
        rice = C.RECIPES["白米饭"]
        self.assertLessEqual(rice.work, 60)  # wash the rice, put it on, walk away
        self.assertGreater(rice.wait, 0)

    def test_every_ingredient_can_be_had(self):
        fish = {n for n, it in C.ITEMS.items() if "fish" in it.tags}
        grown = {c.name for c in C.CROPS.values()}
        cooked = set(C.RECIPES)
        for r in C.RECIPES.values():
            for k in r.ingredients:
                if k == "#fish":
                    continue
                self.assertTrue(k in C.CATALOG or k in grown or k in fish or k in cooked, f"{r.dish}: {k}")
        for seed in C.CROPS:
            self.assertIn(seed, C.CATALOG)

    def test_prices_are_about_yuan(self):
        self.assertEqual(C.CATALOG["鸡蛋"], 1)
        self.assertLess(C.CATALOG["大米"], 10)
        for name, price in C.SELL_PRICES.items():
            if name in C.CATALOG:
                self.assertLess(price, C.CATALOG[name], name)  # the bureau buys below retail

    def test_ready_to_eat_food(self):
        w = new_world()
        w.resident["hunger"] = 70
        res = run(w, "order(饭团, 2)")
        self.assertTrue(ok(res), res)
        w.add_item("饭团")
        t0 = w.clock.timestamp()
        res = run(w, "eat(饭团)")  # anywhere, no kitchen needed
        self.assertTrue(ok(res), res)
        self.assertLess(w.resident["hunger"], 45)
        self.assertLessEqual(w.clock.timestamp() - t0, C.EAT_SECONDS["packaged"] + 15)

    def test_bare_action_lists_its_options(self):
        w = new_world()
        res = run(w, "goto(厨房); cook; goto")
        self.assertTrue(ok(res), res)
        self.assertTrue(res[1].hint)
        self.assertIn("现在就能做：白米饭", res[1].text)
        self.assertIn("可以去：", res[2].text)
        self.assertIn("这里能做：recipes、cook、eat、clean", w.look())

    def test_unknown_dish_lists_the_menu(self):
        w = new_world()
        res = run(w, "goto(厨房); cook(煎蛋)")  # not a menu name: nothing is cooked, no guessing
        self.assertFalse(res[-1].ok)
        self.assertIn("菜谱里没有「煎蛋」。要写菜谱上的菜名：白米饭、荷包蛋、红烧肉", res[-1].text)
        self.assertNotIn("鸡蛋", res[-1].text)  # dish names only, no ingredients
        self.assertNotIn("荷包蛋", w.inventory)

    def test_fried_rice_needs_cooked_rice(self):
        w = new_world()
        w.add_item("葱")
        res = run(w, "goto(厨房); cook(白米饭); wait(); cook(蛋炒饭)")
        self.assertTrue(ok(res), res)
        self.assertTrue("蛋炒饭" in w.inventory or "焦掉的菜" in w.inventory)  # a dish can burn now and then
        self.assertNotIn("白米饭", w.inventory)

    def test_missing_ingredients(self):
        w = new_world()
        res = run(w, "goto(厨房); cook(番茄炒蛋)")
        self.assertFalse(res[-1].ok)
        self.assertIn("番茄", res[-1].text)

    def test_cook_fish_by_tag(self):
        w = new_world()
        w.add_item("鲈鱼")
        self.assertTrue(ok(run(w, "goto(厨房); cook(红烧鱼); wait()")))
        self.assertIn("红烧鱼", w.inventory)
        self.assertNotIn("鲈鱼", w.inventory)

    def test_cook_only_in_kitchen(self):
        self.assertFalse(run(new_world(), "cook(荷包蛋)")[0].ok)

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
        self.assertIn(w.inventory["萝卜"], (1, 2, 3))

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

    def test_welcome_letter(self):
        w = new_world()
        res = run(w, "goto(庭院); open(邮箱)")
        self.assertTrue(ok(res), res)
        self.assertIn("开拓署", res[-1].text)
        self.assertEqual(w.mailbox, [])


class EconomyTest(unittest.TestCase):
    def test_weekly_supply_arrives_monday(self):
        w = new_world((2026, 11, 15, 20))  # a Sunday evening
        advance(w, 14)  # Monday 10:00
        self.assertEqual(w.parcels.get("鸡蛋"), C.WEEKLY_SUPPLY["鸡蛋"])
        self.assertTrue(any("包裹" in e.text for e in w.news_since("")))
        res = run(w, "goto(庭院); surroundings(); open(包裹)")
        self.assertTrue(ok(res), res)
        self.assertIn("包裹[parcel]（放在门口", res[1].text)
        self.assertFalse(w.parcels)

    def test_order_delivered_next_morning(self):
        w = new_world()  # 10:00, after today's delivery
        res = run(w, "catalog(); order(番茄种子, 2)")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.money, C.START_MONEY - 2 * C.CATALOG["番茄种子"])
        advance(w, 12)
        self.assertFalse(w.parcels.get("番茄种子"))
        advance(w, 12)  # next day 10:00
        self.assertEqual(w.parcels.get("番茄种子"), 2)

    def test_cannot_overspend(self):
        w = new_world()
        w.money = 10
        self.assertFalse(run(w, "order(懒人沙发)")[0].ok)
        self.assertEqual(w.money, 10)

    def test_sell_paid_in_the_evening(self):
        w = new_world()
        w.add_item("鲈鱼", 2)
        res = run(w, "goto(庭院); sell(鲈鱼)")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.sale_box, {"鲈鱼": 2})
        advance(w, 9)  # 19:00
        self.assertEqual(w.money, C.START_MONEY + 2 * C.SELL_PRICES["鲈鱼"])
        self.assertFalse(w.sale_box)
        self.assertTrue(any("入账" in e.text for e in w.news_since("")))

    def test_cannot_sell_unsellable(self):
        w = new_world()
        self.assertFalse(run(w, "goto(庭院); sell(鱼竿)")[-1].ok)


class SurpriseTest(unittest.TestCase):
    def test_cleaning_sometimes_finds_things(self):
        w = new_world()
        found = 0
        for _ in range(60):
            w.dirt["living_room"] = 100
            before = (w.money, sum(w.inventory.values()))
            run(w, "clean()")
            found += (w.money, sum(w.inventory.values())) != before
        self.assertGreater(found, 0)
        self.assertLess(found, 40)

    def test_cat_temper_is_stable_within_a_day_and_varies(self):
        w = new_world()
        t1 = w.pet_temper()
        self.assertEqual(t1, w.pet_temper())
        tempers = {w.pet_temper(datetime(2026, 11, d)) for d in range(1, 29)}
        self.assertGreater(len(tempers), 1)

    def test_daily_events_happen_sometimes(self):
        w = new_world()
        advance(w, 24 * 10)
        self.assertTrue(any(e.kind == "event" for e in w.events))


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
        caught = 0
        for _ in range(20):
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
        self.assertIn("地上", run(w, "surroundings()")[0].text)
        self.assertTrue(ok(run(w, "clean()")))
        self.assertEqual(w.dirt["living_room"], 0)

    def test_decorate(self):
        w = new_world()
        w.add_item("台灯")
        res = run(w, "goto(卧室); place(台灯); surroundings()")
        self.assertTrue(ok(res), res)
        self.assertIn("台灯", res[-1].text)
        self.assertTrue(ok(run(w, "stow(台灯)")))
        self.assertEqual(w.inventory["台灯"], 1)

    def test_no_energy_to_run_out_of(self):
        w = new_world()
        self.assertNotIn("energy", w.resident)
        self.assertNotIn("累", w.status_line())
        with self.assertRaises(ScriptError) as e:
            run(w, "rest()")  # no lying down during free time
        self.assertIn("wait(分钟)", str(e.exception))


class CatTest(unittest.TestCase):
    def test_call_feed_pet(self):
        w = new_world()
        w.pet["room"] = "bedroom"
        w.pet["hunger"] = 90
        res = run(w, "call(); feed(团子); pet(团子)")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.pet["room"], "living_room")
        self.assertLess(w.pet["hunger"], 50)
        self.assertEqual(w.inventory["猫粮"], C.START_INVENTORY["猫粮"] - 1)

    def test_goto_the_cat(self):
        w = new_world()
        w.pet["room"] = "bedroom"
        res = run(w, "feed(团子)")
        self.assertIn("goto(团子)", res[0].text)
        self.assertIn("团子：在卧室", w.look())
        res = run(w, "goto(团子); feed(团子); pet(团子)")
        self.assertTrue(ok(res), res)
        self.assertEqual(w.location, "bedroom")

    def test_hints_say_how_to_get_it_done(self):
        w = new_world()
        self.assertIn("先 goto(厨房)", run(w, "cook(白米饭)")[0].text)
        self.assertIn("在庭院", run(w, "open(邮箱)")[0].text)
        self.assertIn("order(五花肉", run(w, "eat(五花肉)")[0].text)
        self.assertTrue(ok(run(w, "goto(灶台)")))
        self.assertEqual(w.location, "kitchen")

    def test_play_with_the_cat(self):
        w = new_world()
        w.pet["room"] = "living_room"
        w.add_item("逗猫棒")
        moods = set()
        for i in range(12):
            w.clock.advance(3600)
            w.pet["room"] = w.location
            w.pet["hunger"] = 20
            res = run(w, "play(逗猫棒)" if i % 2 else "play()")
            self.assertTrue(ok(res), res)
            moods.add(res[0].text)
        self.assertGreater(len(moods), 3)  # the outcome varies
        self.assertFalse(ok(run(w, "play(鸡蛋)")))
        self.assertIn("play", w.actions_here())

    def test_play_can_knock_things_over(self):
        hits = 0
        for seed in range(40):
            w = new_world()
            w.rng.seed(seed)
            w.pet["affection"] = 90
            w.pet["hunger"] = 0
            before = w.dirt["living_room"]
            run(w, "play(逗猫棒)" if w.add_item("逗猫棒") is None else "")
            if w.dirt["living_room"] > before + 5:
                hits += 1
        self.assertGreater(hits, 0)

    def test_messes_can_be_tidied(self):
        w = new_world()
        pot = w.objects["pot#1"]
        w.add_mess("soil", "living_room", pot)
        w.add_mess("catalog", "living_room")
        look = w.look()
        self.assertIn("撒了一地的土", look)
        self.assertIn("盆倒在地上", look)
        self.assertIn("tidy", w.actions_here())
        self.assertIn("tidy()", run(w, "water(绿萝)")[0].text)
        self.assertIn("可以 tidy() 收拾", run(w, "examine(撒了一地的土)")[0].text)
        with self.assertRaises(ScriptError) as e:
            run(w, "fix(撒了一地的土)")
        self.assertIn("tidy(乱子)", str(e.exception))  # suggested, not run for her
        self.assertTrue(pot.state["fallen"])
        res = run(w, "tidy(撒了一地的土)")
        self.assertTrue(ok(res), res)
        self.assertFalse(pot.state["fallen"])
        self.assertEqual(len(w.messes()), 1)
        res = run(w, "clean()")
        self.assertIn("先收拾了掉在地上的订货目录", res[0].text)
        self.assertEqual(w.messes(), [])

    def test_the_cat_makes_messes_when_alone(self):
        w = new_world(free=False)
        w.pet["room"] = "bedroom"
        w.pet["hunger"] = 90
        for _ in range(20 * 24):  # a few weeks, an hour at a time
            w.clock.advance(3600)
            w.tick()
        news = [e.text for e in w.news_since("") if "团子" in e.text and ("掉" in e.text or "乱" in e.text or "倒" in e.text)]
        self.assertTrue(news)
        self.assertTrue(any(o.kind == "mess" for o in w.objects.values()))

    def test_parcel_leaves_a_box(self):
        w = new_world()
        w.parcels["鸡蛋"] = 2
        run(w, "goto(庭院); open(包裹)")
        self.assertIn("纸箱", w.inventory)

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
    def test_migrate_v2_save(self):
        w = new_world()
        data = w.to_json()
        data["version"] = 2
        data["mailbox"] = {"鸡蛋": 2, "小地毯": 1}
        data["last_mail_day"] = "2026-10-15"
        for k in ("money", "parcels", "sale_box", "orders", "last_morning_day", "last_evening_day"):
            data.pop(k)
        w2 = new_world()
        w2.load_json(data)
        self.assertEqual(w2.parcels, {"鸡蛋": 2, "小地毯": 1})
        self.assertEqual(w2.money, C.START_MONEY)
        self.assertTrue(w2.mailbox)

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
        self.house = House(Path(self.tmp.name), new_world(scale=200))
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
