"""Turning action beats into poses (no pygame here).

Every successful action appends a *beat* to ``world.beats``: the waypoints she
walked and what she did. Two ways to show them:

* ``snapshot_pose(world)`` — the still picture (``house_glance``, screenshots):
  her at the end of the latest beat, frozen mid-action (e.g. water drops still
  falling) if it happened recently. Costs one frame, only when asked.
* ``Animator`` — the live window: plays beats in order, walking between
  waypoints and holding each action for a moment. Only runs while a window is
  open; a backlog is played faster so the picture never lags far behind.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

WALK_TILES_PER_SEC = 5.0
EFFECT_SECONDS = 1.6
MAX_BACKLOG_SECONDS = 12.0
RECENT_SECONDS = 15 * 60  # a still picture still shows an action this fresh

EFFECTS = {
    "water": "water", "cook": "steam", "clean": "sparkle", "pick": "sparkle", "display": "sparkle",
    "place": "sparkle", "stow": "sparkle", "plant": "dirt", "harvest": "pop", "fish": "fishing",
    "pet": "hearts", "feed": "hearts", "call": "hearts", "eat": "eat", "rest": "zzz",
    "open": "paper", "read": "paper", "catalog": "paper", "recipes": "paper", "order": "coin",
    "sell": "coin", "say": "speech", "look": "look", "examine": "look",
}


@dataclass
class Pose:
    x: float
    y: float
    facing: int = 1  # 1 = right, -1 = left
    walking: bool = False
    step: int = 0  # walk frame
    effect: str | None = None
    effect_p: float = 0.0  # 0..1 progress of the effect
    focus: str | None = None
    active: bool = False  # she did something recently (not asleep in bed)


def _length(points: list[tuple[float, float]]) -> float:
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _along(points: list[tuple[float, float]], d: float) -> tuple[float, float, int]:
    """Point at distance d along the polyline, and the facing there."""
    facing = 1
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if b[0] != a[0]:
            facing = 1 if b[0] > a[0] else -1
        if d <= seg:
            k = 0 if seg == 0 else d / seg
            return a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, facing
        d -= seg
    end = points[-1]
    return end[0], end[1], facing


def _last_facing(points: list[tuple[float, float]]) -> int:
    for a, b in reversed(list(zip(points, points[1:]))):
        if b[0] != a[0]:
            return 1 if b[0] > a[0] else -1
    return 1


def snapshot_pose(world, now: float | None = None) -> Pose:
    """The still picture: where she is, frozen in her latest action if recent."""
    now = time.time() if now is None else now
    x, y = world.tile()
    beat = world.beats[-1] if world.beats else None
    if beat and now - beat["t"] < RECENT_SECONDS and beat["room"] == world.location:
        effect = EFFECTS.get(beat["action"])
        return Pose(x, y, _last_facing(beat["waypoints"]), effect=effect, effect_p=0.5,
                    focus=beat.get("focus"), active=True)
    return Pose(x, y)


class Animator:
    """Plays beats in the live window.

    Playback advances by real time x ``speed``; whenever new beats arrive the
    speed is chosen so the whole backlog plays within ``MAX_BACKLOG_SECONDS``,
    so the picture never lags far behind what she actually did.
    """

    def __init__(self, world) -> None:
        self.queue: list[dict] = []
        self.seen = world.beats[-1]["seq"] if world.beats else 0  # don't replay history
        self.current: dict | None = None
        self.elapsed = 0.0  # playback seconds into the current beat
        self.speed = 1.0
        self.last_now: float | None = None
        self.rest: Pose | None = None
        self.last_active = 0.0

    def feed(self, beats: list[dict]) -> None:
        added = False
        for b in beats:
            if b["seq"] > self.seen:
                self.queue.append(b)
                self.seen = b["seq"]
                added = True
        if added:
            backlog = sum(self._duration(b) for b in self.queue)
            if self.current is not None:
                backlog += max(0.0, self._duration(self.current) - self.elapsed)
            self.speed = max(1.0, backlog / MAX_BACKLOG_SECONDS)

    @staticmethod
    def _duration(beat: dict) -> float:
        walk = _length(beat["waypoints"]) / WALK_TILES_PER_SEC
        return walk + (EFFECT_SECONDS if EFFECTS.get(beat["action"]) else 0.0)

    def pose(self, world, now: float) -> Pose:
        dt = 0.0 if self.last_now is None else max(0.0, min(1.0, now - self.last_now))
        self.last_now = now
        if self.current is not None:
            self.elapsed += dt * self.speed
            if self.elapsed >= self._duration(self.current):
                self.current = None
        if self.current is None and self.queue:
            self.current = self.queue.pop(0)
            self.elapsed = 0.0
        if self.current is None:
            self.speed = 1.0
            x, y = world.tile()
            recent = now - self.last_active < RECENT_SECONDS
            return Pose(x, y, self.rest.facing if self.rest else 1, active=recent)
        beat = self.current
        self.last_active = now
        points = beat["waypoints"]
        walk_time = _length(points) / WALK_TILES_PER_SEC
        effect = EFFECTS.get(beat["action"])
        if self.elapsed < walk_time:
            x, y, facing = _along(points, self.elapsed * WALK_TILES_PER_SEC)
            pose = Pose(x, y, facing, walking=True, step=int(self.elapsed * 6) % 2, active=True)
        else:
            x, y = points[-1]
            p = 0.0 if not effect else min(1.0, (self.elapsed - walk_time) / EFFECT_SECONDS)
            pose = Pose(x, y, _last_facing(points), effect=effect, effect_p=p, focus=beat.get("focus"), active=True)
        self.rest = pose
        return pose
