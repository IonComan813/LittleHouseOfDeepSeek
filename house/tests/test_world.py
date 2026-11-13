import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from littlehouse.clock import Clock
from littlehouse.script import ScriptError, parse, run
from littlehouse.server import House, make_handler
from littlehouse.world import World


def new_world() -> World:
    return World(Clock(), seed=1)


class ParseTest(unittest.TestCase):
    def test_calls_and_separators(self):
        calls = parse('goto(厨房); look\nwater(pot#1) // comment\nsay("你好，世界")')
        self.assertEqual([c.name for c in calls], ["goto", "look", "water", "say"])
        self.assertEqual(calls[0].args, ["厨房"])
        self.assertEqual(calls[2].args, ["pot#1"])
        self.assertEqual(calls[3].args, ["你好，世界"])

    def test_fullwidth_brackets_and_numbers(self):
        calls = parse("goto（庭院）；look()")
        self.assertEqual([c.name for c in calls], ["goto", "look"])
        self.assertEqual(calls[0].args, ["庭院"])

    def test_numbers(self):
        self.assertEqual(parse("wait(3.5)")[0].args, [3.5])
        self.assertEqual(parse("pick(shell#2)")[0].args, ["shell#2"])

    def test_errors(self):
        for bad in ["goto(厨房", 'say("abc)', "(look)", "look() !! look()"]:
            with self.assertRaises(ScriptError, msg=bad):
                parse(bad)

    def test_limits(self):
        with self.assertRaises(ScriptError):
            parse("look;" * 30)


class WorldTest(unittest.TestCase):
    def test_goto_and_water(self):
        w = new_world()
        res = run(w, "goto(卧室); water(小多肉); examine(pot#2)")
        self.assertTrue(all(r.ok for r in res), res)
        self.assertEqual(w.objects["pot#2"].state["water"], 100.0)
        self.assertEqual(w.location, "bedroom")
        self.assertEqual([e.kind for e in w.events], ["move", "care"])

    def test_stops_at_first_error(self):
        w = new_world()
        res = run(w, "goto(厨房); water(沙发); look()")
        self.assertEqual([r.ok for r in res], [True, False])

    def test_goto_finds_a_path(self):
        w = new_world()
        res = run(w, "goto(厨房); goto(沙滩)")
        self.assertTrue(all(r.ok for r in res), res)
        self.assertIn("客厅", res[1].text)
        self.assertIn("庭院", res[1].text)
        self.assertEqual(w.location, "beach")

    def test_unknown_action(self):
        res = run(new_world(), "dance()")
        self.assertFalse(res[0].ok)

    def test_plants_dry_over_time_and_shells_appear(self):
        w = new_world()
        w.clock.advance(2 * 86400)
        w.tick()
        self.assertLess(w.objects["pot#1"].state["water"], 70.0)
        shells = [o for o in w.objects.values() if o.kind == "shell"]
        self.assertGreater(len(shells), 0)
        res = run(w, f"goto(沙滩); pick({shells[0].id}); inventory()")
        self.assertTrue(all(r.ok for r in res), res)
        self.assertIn(shells[0].id, w.inventory)

    def test_save_load_roundtrip(self):
        w = new_world()
        run(w, "goto(卧室); water(pot#2)")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "world.json"
            w.save(p)
            w2 = new_world()
            self.assertTrue(w2.load(p))
            self.assertEqual(w2.location, "bedroom")
            self.assertEqual(w2.objects["pot#2"].state["water"], 100.0)


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


if __name__ == "__main__":
    unittest.main()
