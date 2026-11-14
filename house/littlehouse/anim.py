"""Where she is and what she is doing *right now*, as a pose (no pygame here).

Since M3 every action takes real time (tasks.py), so the picture needs no
replay: ``current_pose`` reads the phase the runner is playing at this moment —
walking along the route at ``content.WALK_TILES_PER_SEC``, or working at the
stove with steam rising — and the renderer draws it. The live window and the
still ``house_glance`` frame use the same function, so both always show the
true present. Outside free time she is settled into one of the everyday
activities (``content.IDLE_ACTIVITIES``): reading on the sofa, asleep in bed...
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import content as C
from .tasks import along

EFFECT_SECONDS = 1.6  # one loop of an effect animation

EFFECTS = {
    "water": "water", "cook": "steam", "clean": "sparkle", "pick": "sparkle", "display": "sparkle",
    "place": "sparkle", "stow": "sparkle", "plant": "dirt", "harvest": "pop", "fish": "fishing",
    "pet": "hearts", "feed": "hearts", "call": "hearts", "eat": "eat", "rest": "zzz",
    "open": "paper", "read": "paper", "catalog": "paper", "order": "coin",
    "sell": "coin", "say": "speech", "examine": "look",
}


@dataclass
class Pose:
    x: float
    y: float
    facing: int = 1  # 1 = right, -1 = left
    walking: bool = False
    step: int = 0  # walk frame
    effect: str | None = None
    effect_p: float = 0.0  # 0..1 progress of the effect loop
    focus: str | None = None
    active: bool = False  # doing something (as opposed to standing around)
    asleep: bool = False  # lying in bed


def current_pose(world, now: float | None = None) -> Pose:
    """The pose at game time ``now`` (default: the world clock)."""
    now = world.clock.timestamp() if now is None else now
    r = world.runner
    facing = int(world.resident.get("facing", 1)) or 1
    x, y = world.tile()
    phase = r.phase if r.gen is not None else None
    if phase is not None:
        elapsed = max(0.0, min(phase.seconds, now - r.phase_start))
        if phase.kind == "walk" and len(phase.points) >= 2:
            px, py, f = along(phase.points, elapsed * C.WALK_TILES_PER_SEC)
            return Pose(px, py, f, walking=True, step=int(elapsed * 4) % 2, active=True)
        if phase.kind == "work":
            effect = EFFECTS.get(phase.action)
            if phase.action == "rest" and phase.focus == "bed":
                return Pose(x, y, facing, focus="bed", asleep=True, active=True)
            return Pose(x, y, facing, effect=effect, effect_p=(elapsed % EFFECT_SECONDS) / EFFECT_SECONDS,
                        focus=phase.focus, active=True)
        return Pose(x, y, facing, active=True)  # waiting
    idle = world.current_idle()
    if idle is not None:
        if idle.focus == "bed":
            return Pose(x, y, facing, focus="bed", asleep=True)
        p = (time.time() % (EFFECT_SECONDS * 2)) / (EFFECT_SECONDS * 2)
        return Pose(x, y, facing, effect=idle.effect, effect_p=p, focus=idle.focus)
    return Pose(x, y, facing, active=world.free(now))
