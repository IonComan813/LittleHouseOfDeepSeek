"""World state and passive simulation.

Plain data plus small rules, so it runs headless and is unit-testable. The
agent protocol (HTTP + pseudo-code, see actions.py/script.py) and rendering
(Pygame, later) both sit on top of this module.

Time is game time from ``Clock`` (1:1 with reality by default). ``tick()``
advances the passive simulation — plants drying, crops growing, dirt, hunger,
the cat, the daily mail — in steps of at most one game hour, so a long
absence (DSH closed for a weekend) is simulated faithfully but cheaply.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from . import content as C
from . import scene as S
from .clock import SEASON_ZH, Clock, is_dark, period_of, season_of

SAVE_VERSION = 4
MAX_CATCHUP_HOURS = 24 * 14  # beyond two weeks away, older time is skipped

# Rates are per game hour unless noted.
POT_DRAIN_PER_DAY = 30.0
PLOT_DRAIN_PER_DAY = 50.0
DIRT_PER_DAY = 6.0
HUNGER_PER_HOUR = 5.0
ENERGY_DRAIN_PER_HOUR = 3.0
ENERGY_SLEEP_PER_HOUR = 12.0
PET_HUNGER_PER_HOUR = 4.0
PET_AFFECTION_DECAY_PER_DAY = 2.0
BEACH_FINDS_PER_DAY = 2.0
BEACH_FINDS_PER_RAINY_DAY = 4.0
MAX_BEACH_FINDS = 4


class ActionError(Exception):
    """An action could not be performed; the message is shown to the agent."""


@dataclass
class Obj:
    id: str
    name: str
    kind: str  # plant | plot | fixture | decor | find
    room: str
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class Event:
    t: str
    kind: str
    text: str
    actor: str = "resident"  # resident | world


def _fixtures() -> list[Obj]:
    return [
        Obj("pot#1", "绿萝", "plant", "living_room", {"water": 70.0}),
        Obj("pot#2", "小多肉", "plant", "bedroom", {"water": 40.0}),
        Obj("sofa", "沙发", "fixture", "living_room"),
        Obj("shelf", "收藏架", "fixture", "living_room"),
        Obj("bed", "床", "fixture", "bedroom"),
        Obj("bookshelf", "书架", "fixture", "bedroom"),
        Obj("stove", "灶台", "fixture", "kitchen"),
        Obj("table", "木桌", "fixture", "kitchen"),
        Obj("mailbox", "邮箱", "fixture", "yard"),
        Obj("parcel", "门口的包裹", "fixture", "yard"),
        Obj("consign", "寄售箱", "fixture", "yard"),
        Obj("plot#1", "菜地1", "plot", "yard", {"water": 60.0}),
        Obj("plot#2", "菜地2", "plot", "yard", {"water": 60.0}),
        Obj("plot#3", "菜地3", "plot", "yard", {"water": 60.0}),
        Obj("rock", "礁石", "fixture", "beach"),
        *(Obj(oid, name, "fixture", room) for oid, (name, room) in C.SCENERY.items()),
    ]


def _day(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d")


def _days_due(last_day: str, now: datetime, hour: int, cap: int = 7) -> list[datetime]:
    """Days after ``last_day`` whose ``hour`` has already passed, oldest first (at most ``cap``)."""
    start = datetime.strptime(last_day, "%Y-%m-%d")
    out = []
    d = start + timedelta(days=1)
    while _day(d) < _day(now) or (_day(d) == _day(now) and now.hour >= hour):
        out.append(d)
        d += timedelta(days=1)
    return out[-cap:]


def night(hour: int) -> bool:
    """Her night outside free time (asleep in bed)."""
    start, end = C.NIGHT_HOURS
    return hour >= start or hour < end


def _weighted(rng: random.Random, table: list[tuple[Any, int]]) -> Any:
    total = sum(w for _, w in table)
    r = rng.uniform(0, total)
    for value, w in table:
        r -= w
        if r <= 0:
            return value
    return table[-1][0]


class World:
    def __init__(self, clock: Clock | None = None, seed: int | None = None) -> None:
        self.clock = clock or Clock()
        self.rng = random.Random(seed)
        self.location = "living_room"
        self.inventory: dict[str, int] = dict(C.START_INVENTORY)
        self.objects: dict[str, Obj] = {o.id: o for o in _fixtures()}
        self.objects["find#1"] = Obj("find#1", "白色扇贝壳", "find", "beach", {"item": "白色扇贝壳"})
        self._next_id = 2
        self.resident = {"hunger": 30.0, "energy": 80.0, "last_rest": 0.0}
        self.pet = {"name": C.PET_NAME, "room": "living_room", "hunger": 30.0, "affection": 30.0,
                    "last_pet": 0.0, "hungry_noted": False}
        self.dirt: dict[str, float] = {r: 10.0 for r in C.INDOOR_ROOMS}
        self.money = C.START_MONEY
        self.mailbox: list[str] = [C.WELCOME_LETTER]  # unread letters
        self.parcels: dict[str, int] = {}  # deliveries waiting at the door
        self.sale_box: dict[str, int] = {}  # consignment box, emptied at PICKUP_HOUR
        self.orders: list[dict[str, Any]] = []  # {"item", "n", "due": "YYYY-MM-DD"}
        self.shelf: dict[str, int] = {}
        self.last_tick = self.clock.timestamp()
        now = self.now()
        self.last_morning_day = _day(now if now.hour >= C.DELIVERY_HOUR else now - timedelta(days=1))
        self.last_evening_day = _day(now if now.hour >= C.PICKUP_HOUR else now - timedelta(days=1))
        self.events: list[Event] = []
        self.event_sink: Callable[[Event], None] | None = None
        # Pots on the stove that cook by themselves: {"dish", "method", "done", "outcome", "use", "ready"}.
        self.jobs: list[dict[str, Any]] = []
        self._kitchen_note = ""  # dishes taken off the stove while she was in the kitchen
        from .tasks import Runner  # tasks imports this module

        # Plays her actions in real time (in memory only: a restart drops a half-run script).
        self.runner = Runner(self)

    # ================================================================== time

    def now(self) -> datetime:
        return self.clock.now()

    def season(self, dt: datetime | None = None) -> str:
        return season_of(dt or self.now())

    def weather(self, dt: datetime | None = None) -> str:
        dt = dt or self.now()
        h = int(hashlib.sha256(dt.strftime("%Y-%m-%d").encode()).hexdigest(), 16)
        table = C.WEATHER_TABLE[season_of(dt)]
        r = h % sum(w for _, w in table)
        for name, w in table:
            if r < w:
                return name
            r -= w
        return table[-1][0]

    def raining(self, dt: datetime | None = None) -> bool:
        return self.weather(dt) in C.RAINY

    def tick(self) -> None:
        """Advance the passive simulation to the current game time."""
        now_ts = self.clock.timestamp()
        start = max(self.last_tick, now_ts - MAX_CATCHUP_HOURS * 3600)
        t = start
        while t < now_ts:
            step = min(3600.0, now_ts - t)
            self._step(datetime.fromtimestamp(t), step / 3600.0)
            t += step
        self.last_tick = now_ts
        self._daily(self.now())
        self.update_jobs()

    def update(self) -> None:
        """Bring everything to the current game time: the world, the pots, her current action."""
        self.tick()
        self.runner.advance()
        self.update_jobs()
        self._routine()

    def _step(self, at: datetime, hours: float) -> None:
        days = hours / 24.0
        rain = self.raining(at)
        season = season_of(at)

        for o in self.objects.values():
            if o.kind == "plant":
                o.state["water"] = max(0.0, o.state.get("water", 50.0) - POT_DRAIN_PER_DAY * days)
            elif o.kind == "plot":
                self._grow_plot(o, days, rain, season, at)

        # beach finds wash up (more when it rains)
        rate = (BEACH_FINDS_PER_RAINY_DAY if rain else BEACH_FINDS_PER_DAY) * days
        if self.rng.random() < rate and self._count_finds() < MAX_BEACH_FINDS:
            self._spawn_find(_weighted(self.rng, C.BEACH_FINDS))

        for room in self.dirt:
            self.dirt[room] = min(100.0, self.dirt[room] + DIRT_PER_DAY * days)

        r = self.resident
        free = self.free(at.timestamp())
        r["hunger"] = min(100.0, r["hunger"] + HUNGER_PER_HOUR * hours)
        if not free:  # living her everyday life: she grabs a bite when hungry
            r["hunger"] = min(r["hunger"], C.OFF_HOURS_HUNGER_CAP)
        if not free and night(at.hour):
            r["energy"] = min(100.0, r["energy"] + ENERGY_SLEEP_PER_HOUR * hours)
        else:
            r["energy"] = max(0.0, r["energy"] - ENERGY_DRAIN_PER_HOUR * hours)
            if not free:
                r["energy"] = max(r["energy"], min(C.OFF_HOURS_ENERGY_FLOOR, r["energy"] + ENERGY_DRAIN_PER_HOUR * hours))

        p = self.pet
        p["hunger"] = min(100.0, p["hunger"] + PET_HUNGER_PER_HOUR * hours)
        p["affection"] = max(0.0, p["affection"] - PET_AFFECTION_DECAY_PER_DAY * days)
        if self.rng.random() < min(1.0, hours):
            p["room"] = self.rng.choice(C.INDOOR_ROOMS)
        self.dirt[p["room"]] = min(100.0, self.dirt[p["room"]] + 2.0 * days)
        if p["hunger"] >= 80 and not p["hungry_noted"]:
            p["hungry_noted"] = True
            self.log("pet", f"{p['name']}饿得在{C.ROOMS[p['room']].name}喵喵叫", actor="world", at=at)

    def _grow_plot(self, o: Obj, days: float, rain: bool, season: str, at: datetime) -> None:
        before = o.state.get("water", 0.0)
        if rain:
            o.state["water"] = 100.0
            watered = 1.0
        else:
            drain = PLOT_DRAIN_PER_DAY * days
            watered = 1.0 if drain <= 0 else min(1.0, before / drain)
            o.state["water"] = max(0.0, before - drain)
        seed = o.state.get("seed")
        if not seed or o.state.get("ripe"):
            return
        crop = C.CROPS[seed]
        if season not in crop.seasons:
            return
        o.state["growth"] = o.state.get("growth", 0.0) + days * watered
        if o.state["growth"] >= crop.days:
            o.state["ripe"] = True
            self.log("farm", f"{o.name}里的{crop.name}成熟了", actor="world", at=at)

    def _daily(self, now: datetime) -> None:
        """Morning deliveries and evening pickups for every day that has passed."""
        for d in _days_due(self.last_morning_day, now, C.DELIVERY_HOUR):
            self._morning(d)
            self.last_morning_day = _day(d)
        for d in _days_due(self.last_evening_day, now, C.PICKUP_HOUR):
            self._evening(d)
            self.last_evening_day = _day(d)

    def _morning(self, d: datetime) -> None:
        at = d.replace(hour=C.DELIVERY_HOUR, minute=0, second=0, microsecond=0)
        delivered: dict[str, int] = {}
        due = [o for o in self.orders if o["due"] <= _day(d)]
        self.orders = [o for o in self.orders if o["due"] > _day(d)]
        for o in due:
            delivered[o["item"]] = delivered.get(o["item"], 0) + int(o["n"])
        if d.weekday() == C.SUPPLY_WEEKDAY:
            for item, n in C.WEEKLY_SUPPLY.items():
                delivered[item] = delivered.get(item, 0) + n
            self.mailbox.append(C.SUPPLY_LETTER)
        for item, n in delivered.items():
            self.parcels[item] = self.parcels.get(item, 0) + n
        if delivered:
            self.log("mail", f"{C.COURIER}把包裹放在了门口", actor="world", at=at)
        rng = random.Random(_day(d) + "morning")
        if rng.random() < 0.15:
            self.mailbox.append(rng.choice(C.LETTERS))
            self.log("mail", "邮箱里多了一封信", actor="world", at=at)
        if rng.random() < 0.5:
            text, spawn, _ = _weighted(rng, [((t, sp, w), w) for t, sp, w in C.DAILY_EVENTS])
            if spawn and self._count_finds() < MAX_BEACH_FINDS + 1:
                self._spawn_find(spawn)
            self.log("event", text, actor="world", at=d.replace(hour=7, minute=0, second=0, microsecond=0))

    def _evening(self, d: datetime) -> None:
        if not self.sale_box:
            return
        total = sum(C.SELL_PRICES.get(n, 0) * c for n, c in self.sale_box.items())
        sold = self.format_items(self.sale_box)
        self.money += total
        self.sale_box.clear()
        at = d.replace(hour=C.PICKUP_HOUR, minute=0, second=0, microsecond=0)
        self.log("trade", f"{C.COURIER}收走了寄售箱里的{sold}，入账 {total} {C.CURRENCY}", actor="world", at=at)

    def pet_temper(self, dt: datetime | None = None) -> str:
        """The cat's mood for the day: rolled once per date, stable all day."""
        rng = random.Random(_day(dt or self.now()) + "temper")
        return _weighted(rng, C.PET_TEMPERS)

    # ================================================================== objects

    def new_id(self, prefix: str) -> str:
        oid = f"{prefix}#{self._next_id}"
        self._next_id += 1
        return oid

    def _count_finds(self) -> int:
        return sum(1 for o in self.objects.values() if o.kind == "find")

    def _spawn_find(self, item: str) -> Obj:
        o = Obj(self.new_id("find"), item, "find", "beach", {"item": item})
        self.objects[o.id] = o
        return o

    def here(self) -> list[Obj]:
        return [o for o in self.objects.values()
                if o.room == self.location and not (o.id == "parcel" and not self.parcels)]

    def resolve(self, ref: str) -> Obj:
        """An object in the current room by id ('pot#1') or name ('绿萝')."""
        ref = str(ref).strip()
        here = self.here()
        for match in (lambda o: o.id == ref, lambda o: o.name == ref, lambda o: ref in o.name):
            found = [o for o in here if match(o)]
            if found:
                self.stand_at(found[0].id)
                return found[0]
        pet = self.pet["name"]
        if ref in (pet, "猫", "小猫", "橘猫"):
            if self.pet["room"] == self.location:
                raise ActionError(f"用 pet()/feed() 和{pet}互动吧。")
            raise ActionError(f"{pet}在{C.ROOMS[self.pet['room']].name}。可以 goto({pet}) 走过去。")
        elsewhere = [o for o in self.objects.values() if o.room != self.location and (o.id == ref or o.name == ref)]
        if elsewhere and not (elsewhere[0].id == "parcel" and not self.parcels):
            room = C.ROOMS[elsewhere[0].room].name
            raise ActionError(f"「{ref}」在{room}，不在这里。先 goto({room})。")
        raise ActionError(f"这里没有「{ref}」。")

    # ================================================================== where she is (for the picture)

    def tile(self) -> tuple[float, float]:
        t = self.resident.get("tile")
        if t and self.resident.get("tile_room") == self.location:
            return float(t[0]), float(t[1])
        return S.ANCHORS[self.location]

    def stand_at(self, obj_id: str | None) -> None:
        """Remember what she is using, and stand next to it."""
        self.resident["focus"] = obj_id
        if obj_id is None:
            spot = S.ANCHORS[self.location]
        else:
            finds = [o.id for o in self.objects.values() if o.kind == "find"]
            decor = [o.id for o in self.objects.values() if o.kind == "decor" and o.room == self.location]
            spot = S.spot_of(obj_id, self.location, S.find_spots(finds), S.decor_spots(self.location, decor))
        self.resident["tile"] = [spot[0], spot[1]]
        self.resident["tile_room"] = self.location

    def stand_near(self, point: tuple[float, float]) -> None:
        self.resident["tile"] = [point[0], point[1]]
        self.resident["tile_room"] = self.location

    def resolve_room(self, ref: str) -> C.Room:
        ref = str(ref).strip()
        for r in C.ROOMS.values():
            if ref in (r.id, r.name):
                return r
        if ref in (self.pet["name"], "猫", "小猫", "橘猫"):  # goto(团子): to wherever the cat is
            return C.ROOMS[self.pet["room"]]
        things = [o for o in self.objects.values() if o.kind != "find" and (o.id == ref or o.name == ref)]
        if things:  # goto(灶台): to the room it is in
            return C.ROOMS[things[0].room]
        raise ActionError(f"没有叫「{ref}」的地方。可去：{'、'.join(r.name for r in C.ROOMS.values())}，或者 goto({self.pet['name']})")

    def path_to(self, target: str) -> list[str]:
        """Rooms walked through from the current location to ``target`` (BFS)."""
        prev: dict[str, str | None] = {self.location: None}
        queue = [self.location]
        while queue:
            cur = queue.pop(0)
            for nxt in C.ROOMS[cur].exits:
                if nxt not in prev:
                    prev[nxt] = cur
                    queue.append(nxt)
        if target not in prev:
            raise ActionError(f"去不了{C.ROOMS[target].name}。")
        path: list[str] = []
        node: str | None = target
        while node is not None and node != self.location:
            path.append(node)
            node = prev[node]
        return list(reversed(path))

    # ================================================================== free time and the everyday routine

    def free(self, ts: float | None = None) -> bool:
        """Whether this is her free time (the agent is awake and choosing what to do)."""
        ts = self.clock.timestamp() if ts is None else ts
        return self.resident.get("free_until", 0.0) > ts

    def set_free(self, until: float) -> str:
        """Start (until > now) or end (until <= now) free time. Returns what she was doing before."""
        before = self.resident.get("idle", "")
        now = self.clock.timestamp()
        self.resident["free_until"] = float(until) if until > now else 0.0
        if self.runner.routine:
            self.runner.interrupt("自由活动开始了")
        if until > now:
            self.resident["idle"] = ""
        return before

    def idle_activity(self, dt: datetime | None = None) -> C.Idle:
        """What she does outside free time this hour (stable within the hour)."""
        dt = dt or self.now()
        if night(dt.hour):
            return next(a for a in C.IDLE_ACTIVITIES if a.when == "night")
        ok = [a for a in C.IDLE_ACTIVITIES if a.when == "day" or (a.when == "dry" and not self.raining(dt) and not is_dark(dt))]
        rng = random.Random(dt.strftime("%Y-%m-%d %H") + "idle")
        return _weighted(rng, [(a, a.weight) for a in ok])

    def _routine(self) -> None:
        if self.free() or self.runner.busy():
            return
        act = self.idle_activity()
        if self.resident.get("idle") == act.text and self.location == act.room:
            return
        from .tasks import Call

        self.runner.submit([Call("_settle", [act.room, act.focus, act.text])], routine=True)

    def current_idle(self) -> C.Idle | None:
        """The everyday thing she is settled into right now (None during free time or on her way)."""
        if self.free() or self.runner.busy():
            return None
        text = self.resident.get("idle")
        return next((a for a in C.IDLE_ACTIVITIES if a.text == text), None)

    # ================================================================== the stove

    def burners_free(self) -> int:
        return C.STOVE_BURNERS - sum(1 for j in self.jobs if not j["ready"])

    def start_job(self, dish: str, method: str, seconds: float, outcome: str, use: dict[str, int]) -> None:
        self.jobs.append({"dish": dish, "method": method, "done": self.clock.timestamp() + seconds,
                          "outcome": outcome, "use": dict(use), "ready": False})

    def update_jobs(self) -> None:
        now = self.clock.timestamp()
        for j in self.jobs:
            if not j["ready"] and j["done"] <= now:
                j["ready"] = True
                at = datetime.fromtimestamp(j["done"])
                if j["outcome"] == "burnt":
                    self.log("cook", f"灶台上的{j['dish']}{j['method']}过头，有点糊了", actor="world", at=at)
                else:
                    self.log("cook", f"灶台上的{j['dish']}{j['method']}好了", actor="world", at=at)
        if self.location == "kitchen" and any(j["ready"] for j in self.jobs) and not self.runner.routine:
            self._kitchen_note = self.collect_dishes()

    def collect_dishes(self) -> str:
        """In the kitchen, take finished dishes off the stove. Returns a note ('' if none)."""
        if self.location != "kitchen":
            return ""
        ready = [j for j in self.jobs if j["ready"]]
        if not ready:
            return ""
        self.jobs = [j for j in self.jobs if not j["ready"]]
        got = []
        for j in ready:
            if j["outcome"] == "burnt":
                self.add_item("焦掉的菜")
                self.log("cook", f"{j['dish']}{j['method']}糊了，只盛出一份焦掉的菜")
                got.append(f"{j['dish']}（糊了，成了一份焦掉的菜）")
                continue
            self.add_item(j["dish"])
            extra = "，火候刚刚好，格外好吃" if j["outcome"] == "great" else ""
            self.log("cook", f"用{self.format_items(j['use'])}{j['method']}了{j['dish']}{extra}")
            got.append(j["dish"] + ("（火候刚刚好，香极了）" if extra else ""))
        return f"（你把灶台上的{'、'.join(got)}盛了出来。）"

    def take_kitchen_note(self) -> str:
        note, self._kitchen_note = getattr(self, "_kitchen_note", ""), ""
        return note

    # ================================================================== inventory

    def item_name(self, ref: str, pool: dict[str, int] | None = None) -> str:
        """Resolve a (possibly partial) item name against a pool (default: inventory)."""
        pool = self.inventory if pool is None else pool
        ref = str(ref).strip()
        if pool.get(ref, 0) > 0:
            return ref
        partial = [n for n, c in pool.items() if c > 0 and ref in n]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise ActionError(f"「{ref}」指的是哪一个？{'、'.join(partial)}")
        how = []
        if ref in C.CATALOG:
            how.append(f"可以在客厅的订货目录上买（order({ref}, 数量)）")
        if any(c.name == ref for c in C.CROPS.values()):
            how.append("也可以自己种")
        if ref in C.RECIPES or ref in C.DISH_ALIASES:
            how.append(f"可以在厨房 cook({ref})")
        raise ActionError(f"背包里没有「{ref}」。" + ("，".join(how) + "。" if how else ""))

    def add_item(self, name: str, n: int = 1) -> None:
        self.inventory[name] = self.inventory.get(name, 0) + n

    def take_item(self, name: str, n: int = 1) -> None:
        have = self.inventory.get(name, 0)
        if have < n:
            raise ActionError(f"{name}不够（有 {have}，需要 {n}）。")
        if have == n:
            del self.inventory[name]
        else:
            self.inventory[name] = have - n

    def items_with_tag(self, tag: str) -> list[str]:
        return [n for n, c in self.inventory.items() if c > 0 and tag in C.ITEMS.get(n, C.Item(n)).tags]

    @staticmethod
    def format_items(pool: dict[str, int]) -> str:
        return "、".join(f"{n}×{c}" if c > 1 else n for n, c in pool.items() if c > 0) or "空"

    # ================================================================== events

    def log(self, kind: str, text: str, actor: str = "resident", at: datetime | None = None) -> None:
        ev = Event((at or self.now()).isoformat(timespec="seconds"), kind, text, actor)
        self.events.append(ev)
        del self.events[:-300]
        if self.event_sink is not None:
            self.event_sink(ev)

    def news_since(self, since_iso: str) -> list[Event]:
        return [e for e in self.events if e.actor == "world" and e.t > since_iso]

    # ================================================================== views

    def describe_obj(self, o: Obj) -> str:
        s = o.state
        if o.kind == "plant":
            w = s.get("water", 0)
            mood = "叶子很精神" if w >= 60 else "土有点干了" if w >= 30 else "蔫蔫的，很缺水"
            return f"{o.name}[{o.id}]（{mood}）"
        if o.kind == "plot":
            seed = s.get("seed")
            w = s.get("water", 0)
            wet = "湿润" if w >= 40 else "有点干" if w > 0 else "干透了"
            if not seed:
                return f"{o.name}[{o.id}]（空着，土{wet}）"
            crop = C.CROPS[seed]
            if s.get("ripe"):
                return f"{o.name}[{o.id}]（{crop.name}成熟了，可以收获）"
            g = s.get("growth", 0)
            stage = "刚发芽" if g < crop.days * 0.34 else "长高了" if g < crop.days * 0.75 else "快熟了"
            off = "，但不太适应这个季节" if self.season() not in crop.seasons else ""
            return f"{o.name}[{o.id}]（{crop.name}{stage}，土{wet}{off}）"
        if o.id == "mailbox":
            return f"邮箱[mailbox]（{f'有 {len(self.mailbox)} 封信' if self.mailbox else '空的'}）"
        if o.id == "parcel":
            return f"门口的包裹[parcel]（{sum(self.parcels.values())} 件东西）"
        if o.id == "consign":
            return f"寄售箱[consign]（{'放着 ' + self.format_items(self.sale_box) + '，傍晚收走' if self.sale_box else '空的'}）"
        if o.id == "shelf":
            n = sum(self.shelf.values())
            return f"收藏架[shelf]（{'摆着 ' + str(n) + ' 件收藏' if n else '还空着'}）"
        return f"{o.name}[{o.id}]"

    def status_line(self) -> str:
        h, e = self.resident["hunger"], self.resident["energy"]
        hunger = "很饿" if h >= 75 else "有点饿" if h >= 45 else "不饿"
        energy = "很困" if e <= 20 else "有点累" if e <= 45 else "精神不错"
        return f"{hunger}，{energy}，钱包里有 {self.money} {C.CURRENCY}"

    def look(self) -> str:
        now = self.now()
        room = C.ROOMS[self.location]
        objs = [self.describe_obj(o) for o in self.here()]
        if self.pet["room"] == self.location:
            p = self.pet
            mood = "饿得直叫" if p["hunger"] >= 80 else "在打盹" if p["affection"] >= 50 else "在角落里看着你"
            temper = {"黏人": "，今天好像特别黏人", "傲娇": "，今天有点爱答不理", "烦躁": "，今天脾气不太好"}.get(self.pet_temper(), "")
            objs.append(f"橘猫{p['name']}（{mood}{temper}）")
        dark = "，屋里有点暗" if is_dark(now) and not room.outdoor else ""
        lines = [
            f"时间：{now:%Y-%m-%d %H:%M}（{period_of(now)}，{SEASON_ZH[season_of(now)]}季），天气：{self.weather()}{dark}",
            f"位置：{room.name} —— {room.description}",
            "看到：" + ("、".join(objs) if objs else "没什么特别的东西"),
        ]
        if not room.outdoor and self.dirt[self.location] >= 40:
            lines.append("地上：" + ("很脏了，该打扫了" if self.dirt[self.location] >= 70 else "有点灰"))
        if self.jobs:
            lines.append("灶台上：" + self.stove_text())
        lines += [
            "这里能做：" + "、".join(self.actions_here()) + "；随时能做：goto、look、examine、inventory、wait、say、help",
            "可去：" + "、".join(C.ROOMS[e].name for e in room.exits),
            *([f"{self.pet['name']}：在{C.ROOMS[self.pet['room']].name}（goto({self.pet['name']}) 可以走过去）"]
              if self.pet["room"] != self.location else []),
            f"你：{self.status_line()}",
            "背包：" + self.format_items(self.inventory),
        ]
        free_line = self.free_time_text()
        if free_line:
            lines.append(free_line)
        return "\n".join(lines)

    def actions_here(self) -> list[str]:
        from .actions import actions_here

        return actions_here(self)

    def stove_text(self) -> str:
        now = self.clock.timestamp()
        parts = []
        for j in self.jobs:
            if j["ready"]:
                parts.append(f"{j['dish']}（{j['method']}好了，回厨房就能盛出来）")
            else:
                parts.append(f"{j['dish']}（正在{j['method']}，还要大约 {max(1, round((j['done'] - now) / 60))} 分钟）")
        return "、".join(parts)

    def free_time_text(self) -> str:
        """'现在 08:12，自由活动还剩 28 分钟（到 08:40）' while free; '' otherwise."""
        if not self.free():
            return ""
        until = self.resident["free_until"]
        left = max(0, round((until - self.clock.timestamp()) / 60))
        return f"现在 {self.now():%H:%M}，自由活动还剩 {left} 分钟（到 {datetime.fromtimestamp(until):%H:%M}）"

    # ================================================================== persistence

    def to_json(self) -> dict[str, Any]:
        return {
            "version": SAVE_VERSION,
            "location": self.location,
            "inventory": self.inventory,
            "objects": [asdict(o) for o in self.objects.values()],
            "resident": self.resident,
            "pet": self.pet,
            "dirt": self.dirt,
            "money": self.money,
            "mailbox": self.mailbox,
            "parcels": self.parcels,
            "sale_box": self.sale_box,
            "orders": self.orders,
            "shelf": self.shelf,
            "last_tick": self.last_tick,
            "last_morning_day": self.last_morning_day,
            "last_evening_day": self.last_evening_day,
            "next_id": self._next_id,
            "jobs": self.jobs,
        }

    def load_json(self, data: dict[str, Any]) -> None:
        version = int(data.get("version", 1))
        self.location = data.get("location", self.location)
        if self.location not in C.ROOMS:
            self.location = "living_room"
        self.last_tick = float(data.get("last_tick", self.last_tick))
        if version < 2:
            self._migrate_v1(data)
            return
        self.inventory = {k: int(v) for k, v in data.get("inventory", {}).items() if int(v) > 0}
        self.objects = {o["id"]: Obj(**o) for o in data.get("objects", [])}
        for o in _fixtures():  # fixtures added in newer versions appear in old saves too
            self.objects.setdefault(o.id, o)
        self.resident.update(data.get("resident", {}))
        self.pet.update(data.get("pet", {}))
        self.dirt.update(data.get("dirt", {}))
        self.shelf = dict(data.get("shelf", {}))
        self._next_id = int(data.get("next_id", self._next_id))
        if version < 3:
            # v2 (M1): the mailbox held free daily parcels; the economy did not exist yet.
            self.parcels = {k: int(v) for k, v in (data.get("mailbox") or {}).items()}
            self.mailbox = [C.WELCOME_LETTER]
            last = data.get("last_mail_day")
            if last:
                self.last_morning_day = self.last_evening_day = last
            return
        self.jobs = [dict(j) for j in data.get("jobs", [])]  # v4
        self.money = int(data.get("money", self.money))
        self.mailbox = list(data.get("mailbox", []))
        self.parcels = {k: int(v) for k, v in data.get("parcels", {}).items()}
        self.sale_box = {k: int(v) for k, v in data.get("sale_box", {}).items()}
        self.orders = list(data.get("orders", []))
        self.last_morning_day = data.get("last_morning_day", self.last_morning_day)
        self.last_evening_day = data.get("last_evening_day", self.last_evening_day)

    def _migrate_v1(self, data: dict[str, Any]) -> None:
        """v1 (M0): inventory was a list of object ids; shells lived as objects."""
        old = {o["id"]: o for o in data.get("objects", [])}
        for oid in data.get("inventory", []):
            name = old.get(oid, {}).get("name")
            if name:
                self.add_item(name if name in C.ITEMS else "白色扇贝壳")
        for oid, o in old.items():
            if oid in self.objects and o.get("kind") == "plant":
                self.objects[oid].state.update(o.get("state", {}))
        self._next_id = max(self._next_id, int(data.get("next_item", 0)) + 1)

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
