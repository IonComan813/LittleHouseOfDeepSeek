"""Development only: render a still of the house.  /opt/lh/venv/bin/python tools/shot.py <out.png> [YYYY-mm-dd-HH] [lived]"""
import os, sys
from datetime import datetime
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "house"))
from littlehouse.clock import Clock
from littlehouse.world import World
from littlehouse.script import run
from littlehouse import render

out = sys.argv[1]
when = datetime.strptime(sys.argv[2], "%Y-%m-%d-%H") if len(sys.argv) > 2 else datetime(2026, 11, 14, 10)
c = Clock(); c.advance(when.timestamp() - c.timestamp())
w = World(c, seed=2)
w.resident["free_until"] = c.timestamp() + 3600
if "lived" in sys.argv:
    for n in ("萝卜种子", "菠菜种子"): w.add_item(n, 2)
    for n in ("台灯", "小地毯", "花瓶"): w.add_item(n)
    w.money += 200
    for line in ["goto(客厅); place(小地毯); place(花瓶); place(台灯)", "goto(庭院); plant(萝卜种子, 菜地1); plant(菠菜种子, 菜地2); water()",
                 "goto(沙滩)", "pick()", "goto(客厅); display()", "goto(厨房)"]:
        for r in run(w, line):
            if not r.ok: print("!", r.call, r.text)
open(out, "wb").write(render.render_png(w, scale=2))
print(out)
