"""Read-only window onto the house: ``python -m littlehouse --view``.

It only looks. The window polls the running house for its state and draws it;
keyboard and mouse input are ignored (closing the window is the one thing it
reacts to). Acting in the house is left to the resident.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from . import render  # noqa: E402
from . import scene as S  # noqa: E402
from .clock import Clock  # noqa: E402
from .world import World  # noqa: E402

POLL_SECONDS = 2.0
FPS = 8


def _discover(state_dir: Path) -> tuple[int, str] | None:
    try:
        info = json.loads((state_dir / "house.json").read_text(encoding="utf-8"))
        return int(info["port"]), str(info["token"])
    except (OSError, ValueError, KeyError):
        return None


def _fetch_state(state_dir: Path) -> dict | None:
    found = _discover(state_dir)
    if found is None:
        return None
    port, token = found
    req = urllib.request.Request(f"http://127.0.0.1:{port}/state")
    req.add_header("X-House-Token", token)
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read()).get("state")
    except (OSError, ValueError, urllib.error.URLError):
        return None


def _world_from(state: dict) -> World:
    w = World(Clock(), seed=0)
    w.load_json(state)
    return w


def _waiting(screen: pygame.Surface, t: float) -> None:
    screen.fill((40, 32, 30))
    cx, cy = screen.get_width() // 2, screen.get_height() // 2
    pygame.draw.polygon(screen, (196, 140, 92), [(cx - 40, cy), (cx, cy - 34), (cx + 40, cy)])
    pygame.draw.rect(screen, (245, 232, 200), (cx - 30, cy, 60, 40))
    pygame.draw.rect(screen, (166, 110, 72), (cx - 8, cy + 14, 16, 26))
    for i in range(3):  # "waiting" dots
        on = int(t * 2) % 3 >= i
        pygame.draw.circle(screen, (244, 200, 96) if on else (90, 70, 60), (cx - 14 + i * 14, cy + 60), 4)


def view(state_dir: Path, scale: int = 2) -> None:
    pygame.display.init()  # video only: no audio device needed
    size = (S.COLS * S.TILE * scale, (S.ROWS * S.TILE + S.HUD_H) * scale)
    screen = pygame.display.set_mode(size)
    pygame.display.set_caption("潮汐湾小屋（只读）")
    clock = pygame.time.Clock()
    world: World | None = None
    last_poll = 0.0
    while True:
        for event in pygame.event.get():  # input is deliberately ignored
            if event.type == pygame.QUIT:
                pygame.quit()
                return
        now = time.time()
        if now - last_poll >= POLL_SECONDS:
            last_poll = now
            state = _fetch_state(state_dir)
            world = _world_from(state) if state else None
        if world is None:
            _waiting(screen, now)
        else:
            frame = render.render(world, now)
            pygame.transform.scale(frame, size, screen)
        pygame.display.flip()
        clock.tick(FPS)
