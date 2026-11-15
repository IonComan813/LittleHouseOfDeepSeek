"""Where she is and what she is doing *right now*, as a pose (no pygame here).

Since M3 every action takes real time (tasks.py), so the picture needs no
replay: ``current_pose`` reads the phase the runner is playing at this moment —
walking along the route at ``content.WALK_TILES_PER_SEC``, or working at the
stove with steam rising — and the renderer draws it. The live window and the
still ``house_photo`` frame use the same function, so both always show the
true present. Outside free time she is settled into one of the everyday
activities (``content.IDLE_ACTIVITIES``): tidying up, playing with the cat, asleep in bed...
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from . import content as C
from .tasks import along

EFFECT_SECONDS = 1.6  # one loop of an effect animation

EFFECTS = {
    "water_plants": "water", "cook": "steam", "clean": "sparkle", "pick_up": "sparkle", "put_on_shelf": "sparkle",
    "place": "sparkle", "stow": "sparkle", "plant": "dirt", "harvest": "pop", "fish": "fishing",
    "stroke_cat": "hearts", "feed_cat": "hearts", "call_cat": "hearts", "play_with_cat": "hearts", "tidy_mess": "sparkle", "eat": "eat", "rest": "zzz",
    "open": "paper", "catalog": "paper", "order": "coin",
    "sell": "coin", "examine": "look", "look_at_sky": "look", "play_in_water": "wade",
}


@dataclass
class Pose:
    x: float
    y: float
    facing: int = 1  # 1 = right, -1 = left
    walking: bool = False
    step: int = 0  # walk frame (0-7, eight steps a second)
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
            return Pose(px, py, f, walking=True, step=int(elapsed * 8) % 8, active=True)
        if phase.kind == "work":
            effect = EFFECTS.get(phase.action)
            focus = phase.focus
            if phase.action == "play_in_water" and world.resident.get("wade_fish"):
                focus = "fish"  # small fish gathered round her feet
            return Pose(x, y, facing, effect=effect, effect_p=(elapsed % EFFECT_SECONDS) / EFFECT_SECONDS,
                        focus=focus, active=True)
        return Pose(x, y, facing, active=True)  # waiting
    idle = world.current_idle()
    if idle is not None:
        if idle.focus == "bed":
            return Pose(x, y, facing, focus="bed", asleep=True)
        p = (time.time() % (EFFECT_SECONDS * 2)) / (EFFECT_SECONDS * 2)
        focus = idle.focus
        if idle.story == "play_in_water":  # fish only if the story told when someone asked had them
            kept = world.resident.get("idle_story")
            if kept and kept[0] == world.resident.get("idle_key") and C.fish_seen(kept[1]):
                focus = "fish"
        return Pose(x, y, facing, effect=idle.effect, effect_p=p, focus=focus)
    return Pose(x, y, facing, active=world.free(now))
