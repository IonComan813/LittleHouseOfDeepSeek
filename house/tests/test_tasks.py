"""M3: actions take real time; some can be left running; free time vs. everyday life."""

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from littlehouse import content as C
from littlehouse.script import parse, run
from littlehouse.server import House, make_handler
from littlehouse.tasks import length
from littlehouse import scene as S

from test_world import new_world, ok


def start(w, src, deadline=None):
    w.update()
    return w.runner.reports[w.runner.submit(parse(src), deadline)]


def step(w, seconds):
    w.clock.advance(seconds)
    w.update()


def took(w, src) -> float:
    t0 = w.clock.timestamp()
    res = run(w, src)
    assert all(r.ok for r in res), res
    return w.clock.timestamp() - t0


class DurationTest(unittest.TestCase):
    def test_walking_time_matches_the_route_in_the_picture(self):
        w = new_world()
        w.location = "bedroom"
        w.stand_at(None)
        route = S.route(["bedroom", "living_room", "yard", "beach"], S.ANCHORS["bedroom"], S.ANCHORS["beach"])
        secs = took(w, "goto(沙滩)")
        self.assertAlmostEqual(secs, length(route) / C.WALK_TILES_PER_SEC, delta=0.5)

    def test_stir_fry_keeps_her_at_the_stove(self):
        w = new_world()
        run(w, "goto(厨房)")
        secs = took(w, "cook(荷包蛋)")
        self.assertGreaterEqual(secs, C.RECIPES["荷包蛋"].work)
        self.assertIn("荷包蛋", w.inventory)

    def test_simmering_lets_her_leave(self):
        w = new_world()
        w.add_item("萝卜")
        w.add_item("排骨")
        run(w, "goto(厨房)")
        secs = took(w, "cook(萝卜炖排骨)")
        self.assertLess(secs, C.RECIPES["萝卜炖排骨"].work + 15)  # only the prep keeps her busy
        self.assertNotIn("萝卜炖排骨", w.inventory)
        self.assertIn("萝卜炖排骨", w.look())  # "灶台上：萝卜炖排骨（正在炖……）"
        res = run(w, "goto(庭院); water(); goto(沙滩); pick()")
        self.assertTrue(ok(res), res)
        step(w, C.RECIPES["萝卜炖排骨"].wait)
        self.assertTrue(any("萝卜炖排骨炖好了" in e.text for e in w.news_since("")))
        self.assertNotIn("萝卜炖排骨", w.inventory)  # still on the stove: she is on the beach
        res = run(w, "goto(厨房)")
        self.assertIn("盛了出来", res[0].text)
        self.assertIn("萝卜炖排骨", w.inventory)

    def test_wait_for_the_pot(self):
        w = new_world()
        w.add_item("萝卜")
        w.add_item("排骨")
        res = run(w, "goto(厨房); cook(萝卜炖排骨); wait(); eat(萝卜炖排骨)")
        self.assertTrue(ok(res), res)
        self.assertIn("盛了出来", res[2].text)

    def test_two_burners(self):
        w = new_world()
        w.add_item("萝卜", 3)
        w.add_item("排骨", 3)
        res = run(w, "goto(厨房); cook(萝卜炖排骨); cook(萝卜炖排骨); cook(萝卜炖排骨)")
        self.assertEqual([r.ok for r in res], [True, True, True, False])
        self.assertIn("灶眼", res[-1].text)
        self.assertTrue(ok(run(w, "cook(荷包蛋)")) is False)  # frying needs a free ring too

    def test_a_round_of_the_usual_takes_about_twenty_minutes(self):
        w = new_world()
        w.add_item("萝卜")
        w.add_item("排骨")
        w.dirt["kitchen"] = 50
        t0 = w.clock.timestamp()
        res = run(w, "call(); feed(); goto(厨房); cook(萝卜炖排骨); clean(); goto(庭院); water(); open(邮箱)")
        self.assertTrue(ok(res), res)
        res = run(w, "goto(沙滩); pick(); fish(); fish(); goto(厨房); eat(萝卜炖排骨); goto(客厅); display()")
        self.assertTrue(ok(res), res)
        minutes = (w.clock.timestamp() - t0) / 60
        self.assertGreater(minutes, 12)
        self.assertLess(minutes, 28)


class InterruptTest(unittest.TestCase):
    def test_leaving_the_wok_burns_the_dish(self):
        w = new_world()
        run(w, "goto(厨房)")
        start(w, "cook(荷包蛋)")
        step(w, 30)
        report = start(w, "goto(客厅)")
        self.assertIn("焦掉的菜", w.inventory)
        self.assertNotIn("荷包蛋", w.inventory)
        step(w, 60)
        self.assertTrue(report.done)

    def test_cleaning_keeps_its_progress(self):
        w = new_world()
        w.dirt["living_room"] = 100.0  # four minutes of sweeping
        start(w, "clean()")
        step(w, 120)
        start(w, "goto(庭院)")  # leave half-way
        self.assertAlmostEqual(w.dirt["living_room"], 50, delta=5)
        res = run(w, "goto(客厅); clean()")
        self.assertTrue(ok(res), res)
        self.assertLess(res[1].end, "10:15")
        self.assertEqual(w.dirt["living_room"], 0.0)

    def test_clean_for_a_while(self):
        w = new_world()
        w.dirt["living_room"] = 100.0
        res = run(w, "clean(1)")
        self.assertIn("没扫完", res[0].text)
        self.assertAlmostEqual(w.dirt["living_room"], 75, delta=1)

    def test_free_time_ends_mid_script(self):
        w = new_world()
        deadline = w.clock.timestamp() + 90
        res = run(w, "goto(沙滩); fish(); fish(); fish()", deadline=deadline)
        self.assertLess(len(res), 4)
        report = w.runner.reports[max(w.runner.reports)]
        self.assertEqual(report.stopped, "自由活动时间到了")


class EverydayLifeTest(unittest.TestCase):
    def test_she_settles_into_something_outside_free_time(self):
        w = new_world(when=(2026, 10, 15, 14), free=False)
        for _ in range(12):
            step(w, 10)
        idle = w.current_idle()
        self.assertIsNotNone(idle)
        self.assertEqual(w.location, idle.room)

    def test_free_time_interrupts_the_routine(self):
        w = new_world(when=(2026, 10, 15, 14), free=False)
        step(w, 1)
        self.assertTrue(w.runner.routine)
        w.set_free(w.clock.timestamp() + 40 * 60)
        self.assertFalse(w.runner.busy())
        self.assertIn("自由活动还剩 40 分钟", w.look())

    def test_off_hours_needs_stay_reasonable(self):
        w = new_world(free=False)
        w.clock.advance(20 * 3600)
        w.tick()
        self.assertLessEqual(w.resident["hunger"], C.OFF_HOURS_HUNGER_CAP)
        self.assertGreaterEqual(w.resident["energy"], C.OFF_HOURS_ENERGY_FLOOR - 0.01)

    def test_pots_survive_a_restart(self):
        w = new_world()
        w.add_item("萝卜")
        w.add_item("排骨")
        run(w, "goto(厨房); cook(萝卜炖排骨)")
        w2 = new_world()
        w2.load_json(json.loads(json.dumps(w.to_json())))
        self.assertEqual([j["dish"] for j in w2.jobs], ["萝卜炖排骨"])


class ServerRealTimeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.house = House(Path(self.tmp.name), new_world(free=False, scale=300))
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.house, "secret"))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()

    def post(self, path, body):
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=json.dumps(body).encode())
        r.add_header("X-House-Token", "secret")
        r.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(r) as resp:
            return json.loads(resp.read())

    def test_session_and_do(self):
        now = self.house.world.clock.timestamp()
        body = self.post("/session", {"free_until": now + 40 * 60})
        self.assertTrue(body["free"])
        body = self.post("/do", {"script": "goto(厨房); cook(荷包蛋)"})
        self.assertTrue(body["ok"], body)
        self.assertTrue(body["done"])
        self.assertIn("自由活动还剩", body["text"])
        self.assertIn("荷包蛋", self.house.world.inventory)
        body = self.post("/session", {"free_until": 0})
        self.assertFalse(body["free"])

    def test_do_returns_early_and_the_script_goes_on(self):
        now = self.house.world.clock.timestamp()
        self.post("/session", {"free_until": now + 3600})
        body = self.post("/do", {"script": "goto(沙滩); fish(); fish()", "wait": 0.05})
        self.assertFalse(body["done"])
        self.assertIn("还在进行", body["text"])
        body = self.post("/interrupt", {})
        self.assertFalse(body["busy"])


if __name__ == "__main__":
    unittest.main()
