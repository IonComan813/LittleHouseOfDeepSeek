"""World model: rooms, objects, the resident's position and inventory.

Everything here is plain data plus small rules, so it runs headless and can be
unit-tested without a window. Rendering (Pygame) and the agent protocol
(HTTP + pseudo-code) both sit on top of this module.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .clock import SEASON_ZH, Clock, is_dark, period_of, season_of

# --------------------------------------------------------------------------- data


@dataclass
class Room:
    id: str
    name: str
    description: str
    exits: list[str]
    outdoor: bool = False


@dataclass
class Obj:
    id: str
    name: str
    kind: str
    room: str
    state: dict[str, Any] = field(default_factory=dict)


ROOMS: dict[str, Room] = {
    r.id: r
    for r in (
        Room("living_room", "客厅", "朝南的小客厅，有一张旧沙发和一扇大窗。", ["kitchen", "bedroom", "yard"]),
        Room("kitchen", "厨房", "小小的厨房，灶台擦得还算干净。", ["living_room"]),
        Room("bedroom", "卧室", "放着一张床和一个书架的卧室。", ["living_room"]),
        Room("yard", "庭院", "屋前的小院子，有一块菜地。往前走就是沙滩。", ["living_room", "beach"], outdoor=True),
        Room("beach", "沙滩", "细细的白沙滩，海浪会把贝壳冲上岸。", ["yard"], outdoor=True),
    )
}


def _default_objects() -> list[Obj]:
    return [
        Obj("pot#1", "绿萝", "plant", "living_room", {"water": 70.0}),
        Obj("pot#2", "小多肉", "plant", "bedroom", {"water": 40.0}),
        Obj("sofa", "沙发", "furniture", "living_room"),
        Obj("bed", "床", "furniture", "bedroom"),
        Obj("bookshelf", "书架", "furniture", "bedroom"),
        Obj("stove", "灶台", "furniture", "kitchen"),
        Obj("plot#1", "菜地", "plot", "yard", {"crop": None}),
        Obj("shell#1", "白色扇贝壳", "shell", "beach"),
    ]


# Plant water drains this many points per game day.
PLANT_DRAIN_PER_DAY = 30.0
MAX_SHELLS_ON_BEACH = 3
SHELL_SPAWN_PER_DAY = 2.0
SHELL_NAMES = ("白色扇贝壳", "粉色海螺", "带花纹的贝壳", "小小的蛤蜊壳", "光滑的鹅卵石")
WEATHERS = ("晴", "晴", "多云", "多云", "阴", "小雨")


class ActionError(Exception):
    """An action could not be performed; the message is shown to the agent."""


@dataclass
class Event:
    t: str
    kind: str
    text: str
    actor: str = "resident"


# --------------------------------------------------------------------------- world


class World:
    def __init__(self, clock: Clock | None = None, seed: int | None = None) -> None:
        self.clock = clock or Clock()
        self.rng = random.Random(seed)
        self.location = "living_room"
        self.inventory: list[str] = []
        self.objects: dict[str, Obj] = {o.id: o for o in _default_objects()}
        self.last_tick = self.clock.timestamp()
        self.events: list[Event] = []
        self._next_item = 2
        self.event_sink: Callable[[Event], None] | None = None

    # ---------------------------------------------------------------- time

    def now(self) -> datetime:
        return self.clock.now()

    def weather(self) -> str:
        day = self.now().strftime("%Y-%m-%d")
        h = int(hashlib.sha256(day.encode()).hexdigest(), 16)
        return WEATHERS[h % len(WEATHERS)]

    def tick(self) -> None:
        """Advance passive simulation to the current game time."""
        now = self.clock.timestamp()
        dt_days = max(0.0, now - self.last_tick) / 86400.0
        self.last_tick = now
        if dt_days <= 0:
            return
        raining = self.weather() == "小雨"
        for o in self.objects.values():
            if o.kind == "plant":
                drain = PLANT_DRAIN_PER_DAY * dt_days
                if raining and ROOMS[o.room].outdoor:
                    drain = -drain
                o.state["water"] = max(0.0, min(100.0, o.state.get("water", 50.0) - drain))
        # Shells wash up on the beach over time.
        expected = SHELL_SPAWN_PER_DAY * dt_days
        spawns = int(expected) + (1 if self.rng.random() < expected % 1 else 0)
        for _ in range(spawns):
            if self._count_kind("shell", "beach") >= MAX_SHELLS_ON_BEACH:
                break
            self._spawn("shell", self.rng.choice(SHELL_NAMES), "beach")

    def _count_kind(self, kind: str, room: str) -> int:
        return sum(1 for o in self.objects.values() if o.kind == kind and o.room == room)

    def _spawn(self, kind: str, name: str, room: str) -> Obj:
        oid = f"{kind}#{self._next_item}"
        self._next_item += 1
        obj = Obj(oid, name, kind, room)
        self.objects[oid] = obj
        return obj

    # ---------------------------------------------------------------- events

    def log(self, kind: str, text: str, actor: str = "resident") -> None:
        ev = Event(self.now().isoformat(timespec="seconds"), kind, text, actor)
        self.events.append(ev)
        del self.events[:-200]
        if self.event_sink is not None:
            self.event_sink(ev)

    # ---------------------------------------------------------------- lookup

    def resolve(self, ref: str, *, here_only: bool = True) -> Obj:
        """Find an object by id ('pot#1') or by name ('绿萝')."""
        ref = ref.strip()
        candidates = [
            o for o in self.objects.values()
            if (o.id == ref or o.name == ref) and (o.room in (self.location, "inventory") or not here_only)
        ]
        if not candidates:
            raise ActionError(f"这里没有「{ref}」。")
        return candidates[0]

    def path_to(self, target: str) -> list[str]:
        """Rooms to walk through from the current location to ``target`` (BFS)."""
        prev: dict[str, str | None] = {self.location: None}
        queue = [self.location]
        while queue:
            cur = queue.pop(0)
            if cur == target:
                break
            for nxt in ROOMS[cur].exits:
                if nxt not in prev:
                    prev[nxt] = cur
                    queue.append(nxt)
        if target not in prev:
            raise ActionError(f"去不了{ROOMS[target].name}。")
        path = []
        node: str | None = target
        while node is not None and node != self.location:
            path.append(node)
            node = prev[node]
        return list(reversed(path))

    def resolve_room(self, ref: str) -> Room:
        for r in ROOMS.values():
            if ref in (r.id, r.name):
                return r
        raise ActionError(f"没有叫「{ref}」的地方。可去：{'、'.join(r.name for r in ROOMS.values())}")

    # ---------------------------------------------------------------- views

    def describe_obj(self, o: Obj) -> str:
        if o.kind == "plant":
            w = o.state.get("water", 0)
            mood = "叶子很精神" if w >= 60 else "土有点干了" if w >= 30 else "蔫蔫的，很缺水"
            return f"{o.name}[{o.id}]（{mood}）"
        if o.kind == "plot":
            crop = o.state.get("crop")
            return f"{o.name}[{o.id}]（{'种着' + crop if crop else '空着'}）"
        return f"{o.name}[{o.id}]"

    def look(self) -> str:
        now = self.now()
        room = ROOMS[self.location]
        here = [o for o in self.objects.values() if o.room == self.location]
        light = "，屋里有点暗" if is_dark(now) and not room.outdoor else ""
        lines = [
            f"时间：{now:%Y-%m-%d %H:%M}（{period_of(now)}，{SEASON_ZH[season_of(now)]}季），天气：{self.weather()}{light}",
            f"位置：{room.name} —— {room.description}",
            "看到：" + ("、".join(self.describe_obj(o) for o in here) if here else "没什么特别的东西"),
            "可去：" + "、".join(ROOMS[e].name for e in room.exits),
            "背包：" + ("、".join(self.objects[i].name for i in self.inventory) if self.inventory else "空"),
        ]
        return "\n".join(lines)

    # ---------------------------------------------------------------- persistence

    def to_json(self) -> dict[str, Any]:
        return {
            "version": 1,
            "location": self.location,
            "inventory": self.inventory,
            "objects": [asdict(o) for o in self.objects.values()],
            "last_tick": self.last_tick,
            "next_item": self._next_item,
        }

    def load_json(self, data: dict[str, Any]) -> None:
        self.location = data.get("location", self.location)
        if self.location not in ROOMS:
            self.location = "living_room"
        self.inventory = list(data.get("inventory", []))
        objs = data.get("objects")
        if objs:
            self.objects = {o["id"]: Obj(**o) for o in objs}
            # Fixtures added in newer versions appear in old saves too.
            for o in _default_objects():
                if o.kind != "shell" and o.id not in self.objects:
                    self.objects[o.id] = o
        self.last_tick = float(data.get("last_tick", self.last_tick))
        self._next_item = int(data.get("next_item", self._next_item))
        self.inventory = [i for i in self.inventory if i in self.objects]

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(path)

    def load(self, path: Path) -> bool:
        if not path.exists():
            return False
        self.load_json(json.loads(path.read_text(encoding="utf-8")))
        return True
