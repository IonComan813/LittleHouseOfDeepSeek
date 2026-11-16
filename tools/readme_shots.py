"""Development only: the pictures in README.md (docs/screenshot-day.png, docs/screenshot-night.png,
docs/animation-strip.png), from a test world.   /opt/lh/venv/bin/python tools/readme_shots.py"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, os.path.join(ROOT, "house"))
from datetime import datetime  # noqa: E402

import pygame  # noqa: E402

from littlehouse import render  # noqa: E402
from littlehouse import scene as S  # noqa: E402
from littlehouse.anim import current_pose  # noqa: E402
from littlehouse.clock import Clock  # noqa: E402
from littlehouse.script import parse, run  # noqa: E402
from littlehouse.world import World  # noqa: E402


def lived(when: datetime) -> World:
    c = Clock()
    c.advance(when.timestamp() - c.timestamp())
    w = World(c, seed=2)
    w.resident["free_until"] = c.timestamp() + 6 * 3600
    for n in ("萝卜种子", "菠菜种子", "番茄种子"):
        w.add_item(n, 2)
    for n in ("台灯", "小地毯", "花瓶", "挂画"):
        w.add_item(n)
    w.add_item("粉色海螺", 2)
    w.add_item("带花纹的贝壳", 3)
    w.money += 300
    for line in ["goto(客厅); place(小地毯); place(花瓶); place(台灯); place(挂画); put_on_shelf()",
                 "goto(庭院); plant(萝卜种子, 菜地1); plant(菠菜种子, 菜地2); plant(番茄种子, 菜地3); water_plants()"]:
        for r in run(w, line):
            if not r.ok:
                print("!", r.call, r.text)
    for o in w.objects.values():  # a few weeks on: the garden has grown
        if o.kind == "plot" and o.state.get("seed"):
            o.state["growth"] = 4.0
    return w


def save(surf, name, scale=2):
    pygame.image.save(pygame.transform.scale(surf, (surf.get_width() * scale, surf.get_height() * scale)),
                      os.path.join(ROOT, "docs", name))


day = lived(datetime(2026, 9, 20, 15))
run(day, "goto(沙滩)")
day.runner.submit(parse("play_in_water()"))
day.rng.seed(4)
day.clock.advance(30)
day.update()
save(render.render(day, t=0.4), "screenshot-day.png")

night = lived(datetime(2026, 9, 20, 21))
run(night, "goto(客厅)")
save(render.render(night, t=0.4), "screenshot-night.png")

walk = lived(datetime(2026, 9, 20, 10))
run(walk, "goto(客厅)")
walk.runner.submit(parse("goto(沙滩)"))
frames = []
for _ in range(8):
    walk.update()
    pose = current_pose(walk)
    full = render.render(walk, t=walk.clock.timestamp() % 100)
    cx, cy = int(pose.x * S.TILE) + 8, int(pose.y * S.TILE)
    box = pygame.Rect(0, 0, 96, 72)
    box.center = (cx, cy)
    box.clamp_ip(full.get_rect())
    frames.append(full.subsurface(box).copy())
    walk.clock.advance(3.2)
strip = pygame.Surface((96 * len(frames), 72))
for i, f in enumerate(frames):
    strip.blit(f, (96 * i, 0))
save(strip, "animation-strip.png")
print("docs/screenshot-day.png docs/screenshot-night.png docs/animation-strip.png")
