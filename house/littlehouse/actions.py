"""Actions the resident can take. Each one is callable from the pseudo-code.

An action is either *simple* — a function that checks, changes the world and
returns a line of text, after which she spends ``content.ACTION_SECONDS`` on it
— or a *process* (``proc=True``): a generator that yields the phases it takes
in real time (walk to the stove, stir-fry for two minutes, ...) and returns the
text. ``process()`` wraps both, so the runner (tasks.py) plays every action
the same way, and the picture shows exactly the phase that is running.

Many actions take an optional argument: without it they act on everything that
fits here (``water()`` waters every plant/plot in the room), which saves the
agent turns.
"""

from __future__ import annotations

import difflib
import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable

from . import content as C
from . import scene as S
from .tasks import Interrupted, Phase, Proc, walk
from .world import ActionError, Obj, World, _weighted



@dataclass
class ActionSpec:
    name: str
    signature: str
    help: str
    fn: Callable[..., object]
    min_args: int
    max_args: int
    proc: bool  # fn is a generator of phases


PET_WORDS = ("猫", "小猫", "橘猫")

ACTIONS: dict[str, ActionSpec] = {}
# Steps only the off-hours routine may run (not callable from her scripts).
INTERNAL: dict[str, Callable[..., Proc]] = {}


def action(signature: str, help: str, min_args: int = 0, max_args: int = 0, proc: bool = False):
    def wrap(fn):
        name = signature.split("(")[0]
        ACTIONS[name] = ActionSpec(name, signature, help, fn, min_args, max_args, proc)
        return fn

    return wrap


def help_text() -> str:
    return "\n".join(f"{a.signature:<20} {a.help}" for a in ACTIONS.values())


# Where she goes for simple actions that do not name an object.
ACTION_SPOTS = {"catalog": "catalog", "order": "catalog", "sell": "consign"}


def process(w: World, name: str, args: list) -> Proc:
    """One action as a sequence of phases; returns the text of what happened."""
    spec = ACTIONS[name]
    if spec.proc:
        text = yield from spec.fn(w, *args)
    else:
        start = w.tile()
        text = spec.fn(w, *args)
        spot = ACTION_SPOTS.get(name)
        if spot:
            w.stand_at(spot)
        elif name in ("pet", "feed", "call") and w.pet["room"] == w.location:
            ax, ay = S.ANCHORS[w.pet["room"]]
            w.stand_near((ax + 1, ay))
        yield from walk_from(w, start, name)
        secs = C.ACTION_SECONDS.get(name, 0)
        secs = secs[0] if isinstance(secs, tuple) else secs
        if secs:
            yield Phase("work", float(secs), name, w.resident.get("focus"))
    return text


def walk_from(w: World, start: tuple[float, float], action: str = "goto") -> Proc:
    """Walk (within this room) from ``start`` to where she now stands."""
    end = w.tile()
    if math.dist(start, end) > 0.05:
        yield walk([start, end], action)
    return ""


def walk_to(w: World, obj_id: str | None, action: str = "goto") -> Proc:
    start = w.tile()
    w.stand_at(obj_id)
    yield from walk_from(w, start, action)
    return ""


def work(seconds: float, action: str, focus: str | None = None, label: str = "") -> Phase:
    return Phase("work", float(seconds), action, focus, label=label)


def visit(w: World, targets: list[Obj], action: str, apply: Callable[[Obj], None]) -> Proc:
    """Go to each target in turn and work on it; returns how many were done."""
    first, each = C.ACTION_SECONDS[action]
    done = 0
    try:
        for i, o in enumerate(targets):
            yield from walk_to(w, o.id, action)
            yield work(first if i == 0 else each, action, o.id)
            apply(o)
            done += 1
    except Interrupted:
        pass
    return done


# ---------------------------------------------------------------- helpers


def _need_room(w: World, *rooms: str) -> None:
    if w.location not in rooms:
        names = "或".join(C.ROOMS[r].name for r in rooms)
        raise ActionError(f"这件事要在{names}做，先 goto({C.ROOMS[rooms[0]].name})。")


def _need_indoor(w: World) -> None:
    if C.ROOMS[w.location].outdoor:
        raise ActionError("这件事要在屋里做（客厅、厨房、卧室），先 goto(客厅) 之类的走进屋。")


def _pet_here(w: World) -> dict:
    p = w.pet
    if p["room"] != w.location:
        raise ActionError(f"{p['name']}在{C.ROOMS[p['room']].name}，不在这里。可以 goto({p['name']}) 走过去，或者在屋里 call() 叫它过来。")
    p["last_with"] = w.clock.timestamp()
    return p


def _minutes_since(w: World, ts: float) -> float:
    return (w.clock.timestamp() - ts) / 60.0


# ---------------------------------------------------------------- looking around


@action("surroundings()", "看看四周：时间、位置、看到的东西、这里能做什么、你的状态和背包")
def _surroundings(w: World) -> str:
    return w.look()


@action("help()", "列出所有动作")
def _help(w: World) -> str:
    return help_text()


@action("goto(地点)", "走到某处（自动穿过中间的房间，按路程花时间），如 goto(沙滩)；也可以 goto(团子) 走到猫身边、goto(灶台) 走到某样东西所在的房间", 1, 1, proc=True)
def _goto(w: World, place: str) -> Proc:
    room = w.resolve_room(place)
    if room.id == w.location and str(place).strip() not in PET_WORDS + (w.pet["name"],):
        return f"你已经在{room.name}了。"
    to_pet = str(place).strip() in PET_WORDS + (w.pet["name"],)
    if to_pet:
        ax, ay = S.ANCHORS[room.id]
        end = (ax + 1, ay)
        if room.id == w.location:
            start = w.tile()
            w.stand_near(end)
            yield from walk_from(w, start)
            return f"你走到了{w.pet['name']}身边。"
    path = w.path_to(room.id)
    yield from walk_route(w, path, end if to_pet else None)
    w.log("move", f"走到了{room.name}")
    via = "、".join(C.ROOMS[r].name for r in path[:-1])
    note = w.collect_dishes()
    return f"你{'穿过' + via + '，' if via else ''}来到了{room.name}。" + note


def walk_route(w: World, path: list[str], end: tuple[float, float] | None = None) -> Proc:
    """Walk room by room through the doors, ending at ``end`` (default: the room's anchor)."""
    for nxt in path:
        pts = [w.tile(), *S.door_points(w.location, nxt)]
        yield walk(pts)
        w.location = nxt
        w.resident["focus"] = None
        w.stand_near(pts[-1])
    start = w.tile()
    if end is None:
        w.stand_at(None)
    else:
        w.stand_near(end)
    yield from walk_from(w, start)
    return ""


def _settle(w: World, room: str, focus: str | None, text: str) -> Proc:
    """Off-hours routine: go and do one of the everyday things (content.IDLE_ACTIVITIES)."""
    if room != w.location:
        yield from walk_route(w, w.path_to(room))
    yield from walk_to(w, focus)
    w.resident["idle"] = text
    return ""


INTERNAL["_settle"] = _settle


@action("examine(东西)", "仔细看某样东西（也可以是背包里的物品）", 1, 1)
def _examine(w: World, ref: str) -> str:
    ref = str(ref)
    try:
        o = w.resolve(ref)
    except ActionError:
        name = w.item_name(ref)
        item = C.ITEMS.get(name)
        return f"{name}：{item.desc or '没什么特别的。'}" if item else f"{name}。"
    if o.kind == "mess":
        target = w.objects.get(o.state.get("target") or "")
        return C.MESSES[o.state["kind"]][3].format(target=target.name if target else "") + "可以 tidy() 收拾。"
    look = C.APPEARANCE.get(o.id) or C.APPEARANCE.get(o.name, "")
    if o.id == "shelf":
        return look + "上面摆着：" + (w.format_items(w.shelf) if w.shelf else "什么都还没有。")
    if o.id == "mailbox":
        return look + (f"里面有 {len(w.mailbox)} 封信，可以 open(邮箱)。" if w.mailbox else "里面是空的。")
    if o.id == "parcel":
        return look + f"里面是：{w.format_items(w.parcels)}。"
    if o.id == "consign":
        return look + ("里面放着：" + w.format_items(w.sale_box) + "，傍晚收走。" if w.sale_box else "里面是空的。")
    if o.kind == "plant":
        return f"{look}{w.describe_obj(o)}，土壤湿度大约 {o.state.get('water', 0):.0f}%。"
    if o.kind == "plot" and o.state.get("seed"):
        crop = C.CROPS[o.state["seed"]]
        pct = min(100, o.state.get("growth", 0) / crop.days * 100)
        return f"{w.describe_obj(o)}，长到了大约 {pct:.0f}%。{crop.name}适合{'、'.join(_season_names(crop.seasons))}种。"
    if o.kind == "find":
        return f"沙滩上的{o.name}，被海水冲得很干净。"
    if look:
        return look
    return w.describe_obj(o) + "。"


def _season_names(seasons) -> list[str]:
    from .clock import SEASON_ZH

    order = (C.SPRING, C.SUMMER, C.AUTUMN, C.WINTER)
    return [SEASON_ZH[s] + "天" for s in order if s in seasons]


@action("inventory()", "查看背包")
def _inventory(w: World) -> str:
    return "背包：" + w.format_items(w.inventory)


@action("say(内容)", "自言自语（会被记下来）", 1, 1)
def _say(w: World, text: str) -> str:
    w.log("say", f"自言自语：「{text}」")
    return f"你小声说：「{text}」"


# ---------------------------------------------------------------- self care


@action("eat(食物)", "吃东西（一顿饭约 2 分钟，零嘴不到 1 分钟）", 1, 1, proc=True)
def _eat(w: World, ref: str) -> Proc:
    name = w.item_name(ref)
    item = C.ITEMS.get(name)
    if item is None or item.fill <= 0:
        raise ActionError(f"{name}不能直接吃。看看 recipes() 能做成什么。")
    w.take_item(name)
    if w.location == "kitchen":
        yield from walk_to(w, "table", "eat")
    secs = C.EAT_SECONDS["dish" if "dish" in item.tags else "packaged" if "packaged" in item.tags else "other"]
    w.resident["hunger"] = max(0.0, w.resident["hunger"] - item.fill)
    w.log("eat", f"吃了{name}")
    try:
        yield work(secs, "eat", w.resident.get("focus"), f"吃{name}")
    except Interrupted:
        return f"你匆匆吃了几口{name}。"
    full = "饱饱的" if w.resident["hunger"] < 20 else "垫了垫肚子"
    return f"你吃了{name}，{full}。"


@action("wait(分钟)", f"原地等一会儿：wait(5) 等 5 分钟（最多 {C.MAX_WAIT_MINUTES}）；wait() 等到灶台上最先好的那道菜好（还要多久就等多久）", 0, 1, proc=True)
def _wait(w: World, minutes: float = 0) -> Proc:
    now = w.clock.timestamp()
    if minutes:
        secs = max(1.0, min(float(minutes), C.MAX_WAIT_MINUTES)) * 60
        what = ""
    else:
        pending = [j for j in w.jobs if not j["ready"]]
        if not pending:
            raise ActionError("现在没有在等的东西。wait(分钟) 可以等一会儿。")
        job = min(pending, key=lambda j: j["done"])
        secs = max(1.0, job["done"] - now + 1)
        what = job["dish"]
    free_until = w.resident.get("free_until", 0.0)
    if free_until > now:
        secs = min(secs, max(1.0, free_until - now))
    try:
        yield Phase("wait", secs, "wait", label=f"等{what}" if what else "等一会儿")
    except Interrupted as e:
        return f"你等了{_waited(e.done)}。"
    note = w.collect_dishes()
    return f"你等了{_waited(secs)}{'，等到' + what + '好了' if what else ''}。" + note


def _waited(secs: float) -> str:
    if secs < 60:
        return f" {max(1, round(secs))} 秒"
    m, sec = divmod(round(secs), 60)
    return f" {m} 分 {sec} 秒" if sec else f" {m} 分钟"


# ---------------------------------------------------------------- kitchen


def _recipe_status(w: World, ingredients: dict[str, int]) -> tuple[bool, dict[str, int], list[str]]:
    """(can_cook, items_to_use, missing descriptions)."""
    use: dict[str, int] = {}
    missing: list[str] = []
    for key, n in ingredients.items():
        if key.startswith("#"):
            cands = [x for x in w.items_with_tag(key[1:]) if w.inventory[x] >= n]
            if cands:
                use[cands[0]] = use.get(cands[0], 0) + n
            else:
                missing.append({"#fish": "任意一条鱼"}.get(key, key))
        elif w.inventory.get(key, 0) >= n:
            use[key] = use.get(key, 0) + n
        else:
            missing.append(f"{key}×{n}" if n > 1 else key)
    return not missing, use, missing


def method_note(dish: str) -> str:
    """How a dish is cooked and how long it takes, e.g. '炖：先忙 2 分钟，再自己炖 5 分钟'."""
    r = C.RECIPES[dish]
    if not r.wait:
        return f"{r.method}，{'要一直守着，' if r.stove else ''}约 {_duration(r.work)}"
    return f"{r.method}，先忙 {_duration(r.work)}，再自己{'煮' if r.method == '包' else r.method} {_duration(r.wait)}，期间可以走开"


def _duration(secs: float) -> str:
    return f"{secs:g} 秒" if secs < 60 else f"{secs / 60:g} 分钟"


def _minutes(secs: float) -> str:
    return f"{secs / 60:g}"


@action("recipes()", "看看会做哪些菜、怎么做、要多久，以及现在缺什么")
def _recipes(w: World) -> str:
    lines = ["（油盐酱醋糖、姜蒜、蚝油、香油这些调料厨房里都有；葱要自己种或者买。）"]
    for dish, r in C.RECIPES.items():
        ok, _, missing = _recipe_status(w, r.ingredients)
        need = "、".join(f"{'任意一条鱼' if k == '#fish' else k}{'×' + str(n) if n > 1 else ''}" for k, n in r.ingredients.items())
        how = f"，{r.how}" if r.how else ""
        lines.append(f"{'✓' if ok else '✗'} {dish}（{need}；{method_note(dish)}{how}）" + ("" if ok else f" 缺：{'、'.join(missing)}"))
    return "\n".join(lines)


def _cook_outcome(w: World) -> str:
    """Roll how the dish turns out: 'burnt', 'great' or 'ok'."""
    burn_chance = 0.05
    roll = w.rng.random()
    return "burnt" if roll < burn_chance else "great" if roll > 0.93 else "ok"


@action("cook(菜名)", "在厨房做菜，如 cook(番茄炒蛋)。炒、煎要一直守在灶台边；煮饭、炖、蒸先忙一会儿，之后自己熟，期间可以去做别的", 1, 1, proc=True)
def _cook(w: World, dish: str) -> Proc:
    _need_room(w, "kitchen")
    dish = str(dish).strip()
    if dish not in C.RECIPES:
        raise ActionError(f"菜谱里没有「{dish}」。要写菜谱上的菜名：{'、'.join(C.RECIPES)}。")
    r = C.RECIPES[dish]
    ok, use, missing = _recipe_status(w, r.ingredients)
    if not ok:
        raise ActionError(f"做{dish}还缺：{'、'.join(missing)}。可以在客厅的订货目录上买，有些也能自己种。")
    if r.stove and w.burners_free() < 1:
        cooking = "、".join(j["dish"] for j in w.jobs if not j["ready"])
        raise ActionError(f"灶台的两个灶眼都占着（{cooking}）。等一个好了再做，或者做不用火的。")
    for name, n in use.items():
        w.take_item(name, n)
    yield from walk_to(w, "stove" if r.stove else "counter", "cook")
    focus = w.resident.get("focus")
    w.dirt["kitchen"] = min(100.0, w.dirt["kitchen"] + 8.0)
    outcome = _cook_outcome(w)
    label = f"{r.method}{dish}" if r.method not in ("包",) else f"包{dish}"
    if not r.wait:
        try:
            yield work(r.work, "cook", focus, label)
        except Interrupted:
            if r.stove:
                w.add_item("焦掉的菜")
                w.log("cook", f"{r.method}{dish}的时候走开了，菜糊了")
                return f"你离开了灶台，锅里的{dish}糊了……只剩一份焦掉的菜。"
            for name, n in use.items():
                w.add_item(name, n)
            return "你停下了手里的活，把食材收了回去。"
        return _serve(w, dish, use, outcome)
    try:
        yield work(r.work, "cook", focus, label)
    except Interrupted:
        for name, n in use.items():
            w.add_item(name, n)
        return "你停下了手里的活，食材还没下锅，先收了回去。"
    verb = "煮" if r.method == "包" else r.method
    w.start_job(dish, verb, r.wait, outcome, use)
    return (f"{dish}已经{'上锅' if r.method == '蒸' else '下锅'}了，接下来让它自己{verb}，"
            f"大约 {_minutes(r.wait)} 分钟后好。这段时间可以去做别的，好了以后回厨房就能盛出来（或者 wait() 等着）。")


def _serve(w: World, dish: str, use: dict[str, int], outcome: str) -> str:
    if outcome == "burnt":
        w.add_item("焦掉的菜")
        w.log("cook", f"想做{dish}，结果做焦了")
        return f"一走神，锅里的{dish}焦了……只得到一份焦掉的菜。"
    w.add_item(dish)
    if outcome == "great":
        w.log("cook", f"用{w.format_items(use)}做了{dish}，火候刚刚好，格外好吃")
        return f"今天手感特别好，{dish}的火候刚刚好，闻起来香极了。"
    w.log("cook", f"用{w.format_items(use)}做了{dish}")
    return f"灶台上冒起热气，你做好了{dish}。"


# ---------------------------------------------------------------- housework


@action("clean(分钟)", "打扫当前房间（越脏越久，最脏约 4 分钟）；clean(2) 只扫 2 分钟，没扫完的下次接着扫", 0, 1, proc=True)
def _clean(w: World, minutes: float = 0) -> Proc:
    _need_indoor(w)
    before = w.dirt[w.location]
    room = C.ROOMS[w.location].name
    rate = C.CLEAN_DIRT_PER_MINUTE / 60.0  # dirt per second
    tidied = ""
    if w.messes():  # put things back first, then sweep
        done = yield from tidy_messes(w, w.messes())
        if done:
            w.log("clean", "收拾了" + "、".join(done))
            tidied = "你先收拾了" + "、".join(done) + "。"
        before = w.dirt[w.location]
    need = max(20.0, before / rate)
    secs = min(need, float(minutes) * 60) if minutes else need
    yield from walk_to(w, None, "clean")
    try:
        yield work(secs, "clean", None, f"打扫{room}")
    except Interrupted as e:
        return tidied + _clean_partly(w, room, e.done, rate)
    if secs < need:
        return tidied + _clean_partly(w, room, secs, rate)
    w.dirt[w.location] = 0.0
    w.log("clean", f"打扫了{room}")
    text = tidied + (f"你把{room}打扫得干干净净。" if before >= 40 else f"{room}本来就挺干净，你又擦了擦。")
    if w.rng.random() < 0.04 + before / 400:  # dirtier rooms hide more
        found = _weighted(w.rng, C.CLEAN_FINDS)
        if found == "@coins":
            coins = w.rng.randint(5, 20)
            w.money += coins
            w.log("find", f"打扫{room}时在地板缝里找到了 {coins} {C.CURRENCY}")
            text += f"扫到沙发底下时，在地板缝里找到了 {coins} {C.CURRENCY}！"
        else:
            w.add_item(found)
            w.log("find", f"打扫{room}时找到了{found}")
            text += f"扫着扫着，从角落里扫出来一个{found}。"
    return text


def _clean_partly(w: World, room: str, secs: float, rate: float) -> str:
    w.dirt[w.location] = max(0.0, w.dirt[w.location] - rate * secs)
    left = w.dirt[w.location] / rate / 60
    w.log("clean", f"打扫了一部分{room}")
    return f"你扫了 {secs / 60:.1f} 分钟，{room}还有一部分没扫完（大约还要 {max(0.5, left):.1f} 分钟）。"


@action("place(家具)", "把背包里的家具摆在当前房间", 1, 1)
def _place(w: World, ref: str) -> str:
    _need_indoor(w)
    name = w.item_name(ref)
    if "furniture" not in C.ITEMS.get(name, C.Item(name)).tags:
        raise ActionError(f"{name}不是家具。")
    w.take_item(name)
    o = Obj(w.new_id("decor"), name, "decor", w.location)
    w.objects[o.id] = o
    room = C.ROOMS[w.location].name
    w.log("decorate", f"在{room}摆上了{name}")
    return f"你把{name}摆在了{room}，看起来更像家了。"


@action("stow(家具)", "把摆着的家具收回背包", 1, 1)
def _stow(w: World, ref: str) -> str:
    o = w.resolve(ref)
    if o.kind != "decor":
        raise ActionError(f"{o.name}收不起来。")
    del w.objects[o.id]
    w.add_item(o.name)
    w.log("decorate", f"把{o.name}收了起来")
    return f"你把{o.name}收进了背包。"


@action("water(植物)", "浇水；不写参数就挨个浇这里所有的植物和菜地", 0, 1, proc=True)
def _water(w: World, ref: str = "") -> Proc:
    start = w.tile()
    targets = [w.resolve(ref)] if ref else [o for o in w.here() if o.kind in ("plant", "plot")]
    if not targets:
        raise ActionError("这里没有需要浇水的东西。")
    for o in targets:
        if o.kind not in ("plant", "plot"):
            raise ActionError(f"{o.name}不需要浇水。")
    fallen = [o for o in targets if o.state.get("fallen")]
    if fallen and len(fallen) == len(targets):
        raise ActionError(f"{fallen[0].name}的盆倒在地上，先 tidy() 把它扶起来。")
    targets = [o for o in targets if not o.state.get("fallen")]
    w.stand_near(start)
    watered: list[Obj] = []

    def apply(o: Obj) -> None:
        o.state["water"] = 100.0
        watered.append(o)

    yield from visit(w, targets, "water", apply)
    if not watered:
        return "你还没来得及浇水。"
    names = "、".join(o.name for o in watered)
    w.log("care", f"给{names}浇了水")
    text = f"你给{names}浇了水。"
    if len(watered) < len(targets):
        text += "还有" + "、".join(o.name for o in targets if o not in watered) + "没浇到。"
    pots = [o for o in watered if o.kind == "plant"]
    if pots and w.rng.random() < 0.05:
        lucky = w.rng.choice(pots)
        w.log("care", f"发现{lucky.name}冒出了一片新叶")
        text += f"仔细一看，{lucky.name}冒出了一片嫩嫩的新叶。"
    return text


# ---------------------------------------------------------------- yard


@action("open(邮箱/包裹)", "看邮箱里的信，或拆开门口的包裹", 1, 1)
def _open(w: World, ref: str) -> str:
    o = w.resolve(ref)
    if o.id == "mailbox":
        if not w.mailbox:
            return "邮箱是空的。"
        letters = list(w.mailbox)
        w.mailbox.clear()
        for letter in letters:
            w.log("mail", f"读了一封信：{letter}")
        return "你从邮箱里取出了信：\n" + "\n".join(letters)
    if o.id == "parcel":
        got = dict(w.parcels)
        for name, n in got.items():
            w.add_item(name, n)
        w.parcels.clear()
        w.log("mail", f"拆开门口的包裹，拿到了{w.format_items(got)}")
        box = ""
        if w.inventory.get("纸箱", 0) < 1:
            w.add_item("纸箱")
            box = "空纸箱留下了，团子大概会喜欢。"
        return f"你拆开包裹：{w.format_items(got)}。{box}"
    raise ActionError(f"{o.name}打不开。")


# ---------------------------------------------------------------- money


@action("catalog()", "翻开开拓署的订货目录：能买什么、多少钱，以及你手上东西的收购价")
def _catalog(w: World) -> str:
    _need_indoor(w)
    buy = "、".join(f"{n} {p}" + (f"/{C.ITEMS[n].unit}" if n in C.ITEMS and C.ITEMS[n].unit else "")
                    for n, p in C.CATALOG.items())
    have = [n for n in w.inventory if n in C.SELL_PRICES]
    sell = "、".join(f"{n} {C.SELL_PRICES[n]}" for n in have) or "（背包里暂时没有能卖的东西）"
    return (f"订购（{C.CURRENCY}，第二天上午送到门口）：{buy}\n"
            f"收购价（放进院子的寄售箱，傍晚 {C.PICKUP_HOUR} 点收走）：{sell}\n"
            f"钱包：{w.money} {C.CURRENCY}")


@action("order(物品, 数量)", "在订货目录上下单，如 order(番茄种子, 2)", 1, 2)
def _order(w: World, ref: str, n: float = 1) -> str:
    _need_indoor(w)
    name = str(ref).strip()
    if name not in C.CATALOG:
        cands = [k for k in C.CATALOG if name and (name in k or k in name)]
        hint = f"你是不是说{'、'.join(cands)}？要写全名。" if cands else "用 catalog() 看看。"
        raise ActionError(f"目录里没有「{name}」。{hint}")
    count = int(n)
    if count < 1 or count > 20:
        raise ActionError("数量要在 1 到 20 之间。")
    cost = C.CATALOG[name] * count
    if cost > w.money:
        raise ActionError(f"钱不够：{name}×{count} 要 {cost} {C.CURRENCY}，你只有 {w.money}。")
    w.money -= cost
    now = w.now()
    due = now if now.hour < C.DELIVERY_HOUR else now + timedelta(days=1)
    w.orders.append({"item": name, "n": count, "due": due.strftime("%Y-%m-%d")})
    when = "今天上午" if due.date() == now.date() else "明天上午"
    w.log("trade", f"订购了{name}×{count}，花了 {cost} {C.CURRENCY}")
    return f"你订了{name}×{count}，花了 {cost} {C.CURRENCY}（还剩 {w.money}），{when}送到门口。"


@action("sell(物品, 数量)", "把东西放进院子的寄售箱，傍晚收走后入账；不写数量就放全部", 1, 2)
def _sell(w: World, ref: str, n: float = 0) -> str:
    _need_room(w, "yard")
    name = w.item_name(ref)
    price = C.SELL_PRICES.get(name)
    if not price:
        raise ActionError(f"开拓署不收{name}。")
    count = int(n) or w.inventory[name]
    w.take_item(name, count)
    w.sale_box[name] = w.sale_box.get(name, 0) + count
    w.log("trade", f"把{name}×{count}放进了寄售箱")
    when = "今天傍晚" if w.now().hour < C.PICKUP_HOUR else "明天傍晚"
    return f"你把{name}×{count}放进寄售箱，{when}收走后能入账 {price * count} {C.CURRENCY}。"


@action("plant(种子, 菜地)", "在菜地播种，如 plant(萝卜种子)；不写菜地就种在第一块空地", 1, 2)
def _plant(w: World, seed_ref: str, plot_ref: str = "") -> str:
    _need_room(w, "yard")
    seed = w.item_name(seed_ref)
    if seed not in C.CROPS:
        seeds = [s for s in w.items_with_tag("seed") if seed in s]
        hint = f"你是不是想种{seeds[0]}？那就写 plant({seeds[0]})。" if seeds else ""
        raise ActionError(f"{seed}不是种子。{hint}")
    if plot_ref:
        plot = w.resolve(plot_ref)
        if plot.kind != "plot":
            raise ActionError(f"{plot.name}不是菜地。")
        if plot.state.get("seed"):
            raise ActionError(f"{plot.name}里已经种着东西了。")
    else:
        empty = [o for o in w.here() if o.kind == "plot" and not o.state.get("seed")]
        if not empty:
            raise ActionError("菜地都种满了。")
        plot = empty[0]
    crop = C.CROPS[seed]
    w.take_item(seed)
    plot.state.update({"seed": seed, "growth": 0.0, "ripe": False})
    w.log("farm", f"在{plot.name}种下了{crop.name}")
    hint = "" if w.season() in crop.seasons else f"（不过{crop.name}不太适合这个季节，可能长不起来）"
    return f"你在{plot.name}种下了{crop.name}，大约 {crop.days:g} 天后成熟，记得浇水。{hint}"


@action("harvest(菜地)", "收获成熟的作物；不写参数就挨个收这里所有熟了的", 0, 1, proc=True)
def _harvest(w: World, ref: str = "") -> Proc:
    start = w.tile()
    plots = [w.resolve(ref)] if ref else [o for o in w.here() if o.kind == "plot" and o.state.get("ripe")]
    if not plots:
        raise ActionError("这里没有可以收获的作物。")
    for p in plots:
        if p.kind != "plot":
            raise ActionError(f"{p.name}不是菜地。")
        if not p.state.get("ripe"):
            raise ActionError(f"{p.name}里的东西还没熟。")
    w.stand_near(start)
    got: dict[str, int] = {}
    seeds: list[str] = []

    def apply(p: Obj) -> None:
        crop = C.CROPS[p.state["seed"]]
        seeds.append(p.state["seed"])
        n = max(1, crop.yield_count + w.rng.choice((-1, 0, 0, 0, 1)))
        w.add_item(crop.name, n)
        got[crop.name] = got.get(crop.name, 0) + n
        p.state.update({"seed": None, "growth": 0.0, "ripe": False})

    yield from visit(w, plots, "harvest", apply)
    if not got:
        return "你还没来得及收。"
    w.log("farm", f"收获了{w.format_items(got)}")
    extra = "今年长得特别好！" if sum(got.values()) > sum(C.CROPS[s].yield_count for s in seeds) else ""
    return f"你收获了{w.format_items(got)}！{extra}"


# ---------------------------------------------------------------- beach


@action("pick(东西)", "捡起地上的小东西；不写参数就挨个捡这里所有的", 0, 1, proc=True)
def _pick(w: World, ref: str = "") -> Proc:
    start = w.tile()
    finds = [w.resolve(ref)] if ref else [o for o in w.here() if o.kind == "find"]
    if not finds:
        raise ActionError("这里没有可以捡的东西。")
    for o in finds:
        if o.kind != "find":
            raise ActionError(f"{o.name}拿不起来。")
    w.stand_near(start)
    if not ref:  # walk along the beach from left to right, not back and forth
        pos = S.find_spots([o.id for o in w.objects.values() if o.kind == "find"])
        finds.sort(key=lambda o: pos.get(o.id, (0, 0))[0])
    names: dict[str, int] = {}

    def apply(o: Obj) -> None:
        del w.objects[o.id]
        w.add_item(o.state["item"])
        names[o.state["item"]] = names.get(o.state["item"], 0) + 1

    yield from visit(w, finds, "pick", apply)
    if not names:
        return "你还没来得及捡。"
    text = w.format_items(names)
    w.log("collect", f"在{C.ROOMS[w.location].name}捡到了{text}")
    return f"你捡起了{text}。"


@action("fish()", f"在沙滩的礁石上钓鱼（需要鱼竿；每一竿等 {C.FISH_SECONDS[0] // 60}–{C.FISH_SECONDS[1] // 60} 分钟）", proc=True)
def _fish(w: World) -> Proc:
    _need_room(w, "beach")
    if w.inventory.get("鱼竿", 0) < 1:
        raise ActionError("你没有鱼竿。")
    weather = w.weather()
    if weather == "雷阵雨":
        raise ActionError("在打雷，礁石上太危险了，改天再钓吧。")
    yield from walk_to(w, "rock", "fish")
    try:
        yield work(w.rng.uniform(*C.FISH_SECONDS), "fish", "rock", "钓鱼")
    except Interrupted:
        w.log("fish", "钓了一会儿鱼，没等到鱼上钩就收竿了")
        return "你收起了鱼竿，这一竿什么也没钓到。"
    table = list(C.FISH_TABLE[w.season()])
    if w.raining():  # fish bite better in the rain
        table = [(k, v if k is None else int(v * 1.3)) for k, v in table]
    catch = _weighted(w.rng, table)
    if catch is None:
        w.log("fish", "钓了一会儿鱼，什么也没钓到")
        return w.rng.choice(("鱼漂动了动，又没动静了。", "等了好久，什么也没钓到。", "鱼饵被偷吃了，空钩。"))
    w.add_item(catch)
    w.log("fish", f"钓到了{catch}")
    if catch == "旧靴子":
        return "钩上来一只湿漉漉的旧靴子……"
    if catch == "漂流瓶":
        return "钩上来一个漂流瓶！里面好像有纸条，可以 read(漂流瓶)。"
    return f"钓到了一条{catch}！"


@action("read(东西)", "读漂流瓶里的纸条", 1, 1)
def _read(w: World, ref: str) -> str:
    name = w.item_name(ref)
    if "readable" not in C.ITEMS.get(name, C.Item(name)).tags:
        raise ActionError(f"{name}上没有可以读的东西。")
    count = w.resident.get("bottles_read", 0)
    note = C.BOTTLE_NOTES[count % len(C.BOTTLE_NOTES)]
    w.resident["bottles_read"] = count + 1
    w.take_item(name)
    w.log("read", f"读了漂流瓶里的纸条：{note}")
    return f"你展开纸条：{note}"


@action("display(收藏品)", "把收藏品摆到客厅的收藏架上；不写参数就全部摆上", 0, 1)
def _display(w: World, ref: str = "") -> str:
    _need_room(w, "living_room")
    if ref:
        names = [w.item_name(ref)]
    else:
        names = [n for n in w.items_with_tag("collectible") if "readable" not in C.ITEMS[n].tags]
    if not names:
        raise ActionError("背包里没有可以摆的收藏品。")
    w.stand_at("shelf")
    moved: dict[str, int] = {}
    for n in names:
        if "collectible" not in C.ITEMS.get(n, C.Item(n)).tags:
            raise ActionError(f"{n}不算收藏品。")
        count = w.inventory[n]
        w.take_item(n, count)
        w.shelf[n] = w.shelf.get(n, 0) + count
        moved[n] = count
    w.log("collect", f"把{w.format_items(moved)}摆上了收藏架")
    return f"你把{w.format_items(moved)}摆上了收藏架。架子上一共有 {sum(w.shelf.values())} 件收藏了。"


# ---------------------------------------------------------------- the cat


@action("call()", "叫猫咪过来")
def _call(w: World) -> str:
    p = w.pet
    if p["room"] == w.location:
        return f"{p['name']}就在你身边。"
    if C.ROOMS[w.location].outdoor:
        return f"你朝屋里喊了一声，{p['name']}没有出来。它不喜欢出门。"
    if p["affection"] < 15 and p["hunger"] < 60:
        return f"你叫了{p['name']}，它在{C.ROOMS[p['room']].name}懒洋洋地甩了甩尾巴，没过来。"
    came_from = C.ROOMS[p["room"]].name
    p["room"] = w.location
    p["last_with"] = w.clock.timestamp()
    return f"{p['name']}从{came_from}小跑着过来了。"


@action("feed(食物)", "喂猫（默认用猫粮，鱼也行）", 0, 1)
def _feed(w: World, ref: str = "") -> str:
    p = _pet_here(w)
    if str(ref).strip() in (p["name"], "猫", "小猫", "橘猫"):  # feed(团子) means "feed the cat"
        ref = ""
    if ref:
        food = w.item_name(ref)
        if food != "猫粮" and "fish" not in C.ITEMS.get(food, C.Item(food)).tags:
            raise ActionError(f"{p['name']}不吃{food}。")
    else:
        if w.inventory.get("猫粮", 0) < 1:
            raise ActionError("没有猫粮了。邮箱里可能会有，鱼也可以。")
        food = "猫粮"
    w.take_item(food)
    was_hungry = p["hunger"] >= 50
    p["hunger"] = max(0.0, p["hunger"] - (70 if food != "猫粮" else 60))
    p["hungry_noted"] = False
    temper = w.pet_temper()
    gain = (8 if food != "猫粮" else 4) + {"黏人": 2, "烦躁": -3}.get(temper, 0)
    p["affection"] = min(100.0, p["affection"] + max(1, gain))
    w.log("pet", f"喂{p['name']}吃了{food}")
    if temper == "烦躁" and not was_hungry:
        return f"{p['name']}闻了闻{food}，吃了两口就甩着尾巴走开了。"
    if temper == "黏人":
        return f"{p['name']}吃完{food}，绕着你的脚转圈，一直蹭个不停。"
    return f"{p['name']}{'狼吞虎咽地' if was_hungry else '慢悠悠地'}吃完了{food}，蹭了蹭你的手。"


@action("pet()", "摸摸猫咪", 0, 1)
def _pet(w: World, ref: str = "") -> str:
    p = _pet_here(w)
    if ref and str(ref).strip() not in (p["name"], "猫", "小猫", "橘猫"):
        raise ActionError(f"pet() 是摸{p['name']}的。")
    if _minutes_since(w, p.get("last_pet", 0.0)) < 30:
        return f"{p['name']}已经被摸够了，甩甩尾巴走开了两步。"
    p["last_pet"] = w.clock.timestamp()
    temper = w.pet_temper()
    if temper == "烦躁" and w.rng.random() < 0.5:
        w.log("pet", f"想摸{p['name']}，被它不耐烦地拍开了手")
        return f"{p['name']}「啪」地拍开了你的手，跳到一边去了。今天还是别惹它了。"
    if temper == "傲娇" and w.rng.random() < 0.5:
        p["affection"] = min(100.0, p["affection"] + 3)
        w.log("pet", f"摸了摸{p['name']}，它假装不在意")
        return f"{p['name']}扭过头假装不在意，尾巴却悄悄翘了起来。"
    p["affection"] = min(100.0, p["affection"] + (9 if temper == "黏人" else 6))
    w.log("pet", f"摸了摸{p['name']}")
    if temper == "黏人":
        return f"{p['name']}一下子躺倒在你手边，翻出肚皮呼噜呼噜地要你继续摸。"
    if p["affection"] >= 60:
        return f"{p['name']}翻过肚皮，发出呼噜呼噜的声音。"
    return f"{p['name']}眯起眼睛，蹭了蹭你的手。"


# ---------------------------------------------------------------- what can I do here / with what


ALWAYS = ("goto", "surroundings", "examine", "inventory", "wait", "say", "help")


def actions_here(w: World) -> list[str]:
    """Action names that make sense where she is (beyond the ALWAYS ones)."""
    room = C.ROOMS[w.location]
    names = [h.split("(")[0] for h in room.hints]
    if not room.outdoor:
        names += ["call"] if w.pet["room"] != w.location else ["feed", "pet", "play"]
        if w.items_with_tag("furniture"):
            names.append("place")
        if any(o.kind == "decor" for o in w.here()):
            names.append("stow")
    if w.items_with_tag("food") or w.items_with_tag("dish"):
        names.append("eat")
    if w.items_with_tag("readable"):
        names.append("read")
    if w.messes():
        names.insert(0, "tidy")
    return list(dict.fromkeys(n for n in names if n in ACTIONS))


def _bag(w: World, names: list[str], price: dict[str, int] | None = None) -> str:
    return "、".join(f"{n}×{w.inventory[n]}" + (f"（{price[n]}{C.CURRENCY}）" if price else "") for n in names)


def options(w: World, name: str) -> str:
    """What to put in the brackets of ``name`` right now (shown when she writes it without arguments)."""
    spec = ACTIONS[name]
    head = f"{spec.signature}：{spec.help}\n"
    here = C.ROOMS[w.location]
    if name == "goto":
        return head + f"可以去：{'、'.join(r.name for r in C.ROOMS.values() if r.id != w.location)}（你在{here.name}）"
    if name == "examine":
        things = [o.name for o in w.here()]
        return head + f"这里有：{'、'.join(things) or '没什么特别的'}；也可以看背包里的东西：{w.format_items(w.inventory)}"
    if name == "say":
        return head + '例如 say("今天的海很安静")'
    if name == "eat":
        food = [n for n in w.inventory if C.ITEMS.get(n, C.Item(n)).fill > 0]
        return head + (f"背包里能吃的：{_bag(w, food)}" if food else "背包里没有能直接吃的。去厨房 cook 一道菜吧。")
    if name == "cook":
        can = [d for d, r in C.RECIPES.items() if _recipe_status(w, r.ingredients)[0]]
        lack = [f"{d}（缺{'、'.join(_recipe_status(w, r.ingredients)[2])}）" for d, r in C.RECIPES.items() if d not in can]
        where = "" if w.location == "kitchen" else "（做饭要先 goto(厨房)）\n"
        return (head + where + f"现在就能做：{'、'.join(f'{d}（{method_note(d)}）' for d in can) or '没有，原料不够'}\n"
                f"还缺原料的：{'、'.join(lack)}\n例如 cook({can[0] if can else '白米饭'})。recipes() 有完整菜谱。")
    if name == "place":
        return head + (f"背包里的家具：{_bag(w, w.items_with_tag('furniture'))}" if w.items_with_tag("furniture") else "背包里没有家具，可以在客厅的订货目录上买。")
    if name == "stow":
        decor = [o.name for o in w.here() if o.kind == "decor"]
        return head + (f"这里摆着：{'、'.join(decor)}" if decor else "这里没有摆你自己的家具。")
    if name == "open":
        return head + "在庭院里：open(邮箱) 看信，open(包裹) 拆门口的快递。"
    if name == "order":
        return head + "目录：" + "、".join(f"{n} {p}" for n, p in C.CATALOG.items()) + f"\n钱包：{w.money} {C.CURRENCY}。例如 order(五花肉, 1)"
    if name == "sell":
        goods = [n for n in w.inventory if n in C.SELL_PRICES]
        return head + (f"背包里能卖的（收购价）：{_bag(w, goods, C.SELL_PRICES)}" if goods else "背包里暂时没有开拓署收的东西（作物、鱼、海边捡的东西）。")
    if name == "plant":
        seeds = w.items_with_tag("seed")
        plots = [o.name for o in w.objects.values() if o.kind == "plot" and not o.state.get("seed")]
        return head + (f"背包里的种子：{_bag(w, seeds)}；空着的菜地：{'、'.join(plots) or '没有'}" if seeds else "背包里没有种子，可以订购。")
    if name == "read":
        return head + (f"能读的：{_bag(w, w.items_with_tag('readable'))}" if w.items_with_tag("readable") else "背包里没有能读的东西。")
    return head.rstrip()



# ---------------------------------------------------------------- playing with the cat


@action("play(玩具)", "陪猫玩；玩具可选（逗猫棒、小铃铛球、猫薄荷玩偶、毛线球、纸箱），不写就用手逗它", 0, 1, proc=True)
def _play(w: World, ref: str = "") -> Proc:
    p = _pet_here(w)
    toy = ""
    if ref and str(ref).strip() not in (p["name"],) + PET_WORDS:
        toy = w.item_name(ref)
        if "toy" not in C.ITEMS.get(toy, C.Item(toy)).tags:
            raise ActionError(f"{toy}不是猫玩具。可以用：{'、'.join(n for n in C.PLAY_WITH if n) }。")
    start = w.tile()
    ax, ay = S.ANCHORS[p["room"]]
    w.stand_near((ax + 1, ay))
    yield from walk_from(w, start, "play")
    try:
        yield work(w.rng.uniform(*C.PLAY_SECONDS), "play", None, f"陪{p['name']}玩")
    except Interrupted:
        return f"你刚逗了{p['name']}两下就停下了。"
    mood, interest = _play_mood(w, toy)
    name = p["name"]
    lines = [f"你{C.PLAY_WITH.get(toy, '拿着' + toy + '逗它')}。"]
    if mood != "meh" and toy in C.PLAY_TOY_LINES and w.rng.random() < 0.6:
        lines.append(C.PLAY_TOY_LINES[toy].format(pet=name))
    else:
        lines.append(w.rng.choice(C.PLAY_MOODS[mood]).format(pet=name))
    event = _play_event(w, mood) if mood != "meh" else ""
    if event:
        lines.append(event)
    gain = {"happy": 10, "ok": 5, "meh": 1}[mood]
    p["affection"] = min(100.0, p["affection"] + gain)
    p["hunger"] = min(100.0, p["hunger"] + (6 if mood == "happy" else 2))
    p["last_play"] = w.clock.timestamp()
    w.log("pet", f"陪{name}玩{'了' + toy if toy else ''}：" + {"happy": "它玩得很开心", "ok": "它玩了一会儿", "meh": "它不太感兴趣"}[mood]
          + (f"；{event}" if event else ""))
    return "".join(lines)


def _play_mood(w: World, toy: str) -> tuple[str, float]:
    """How keen the cat is: today's temper, hunger, the toy, and whether it just played."""
    p = w.pet
    interest = {"黏人": 0.7, "平常": 0.5, "傲娇": 0.35, "烦躁": 0.2}.get(w.pet_temper(), 0.5)
    if toy:
        interest += 0.15
    favourite = p.setdefault("favourite", w.rng.choice([n for n in C.PLAY_WITH if n]))
    if toy == favourite:
        interest += 0.25
    if p["hunger"] >= 70:
        interest -= 0.3  # too hungry to play
    if _minutes_since(w, p.get("last_play", 0.0)) < 30:
        interest -= 0.25  # just played
    interest += w.rng.uniform(-0.25, 0.25)
    return ("happy" if interest >= 0.65 else "ok" if interest >= 0.35 else "meh"), interest


def _play_event(w: World, mood: str) -> str:
    """Maybe something happens in the room while they play (more likely when the cat is excited)."""
    if w.rng.random() > (0.55 if mood == "happy" else 0.3):
        return ""
    pots = [o for o in w.here() if o.kind == "plant" and not o.state.get("fallen")]
    vases = [o for o in w.here() if o.kind == "decor" and o.name == "花瓶" and not o.state.get("fallen")]
    have = {o.state.get("kind") for o in w.messes()}
    options = [(t, eff) for t, eff, wt in C.PLAY_EVENTS.get(w.location, []) for _ in range(wt)
               if (eff != "soil" or pots) and (eff != "water" or vases) and eff not in have]
    if not options:
        return ""
    text, effect = w.rng.choice(options)
    target = w.rng.choice(pots) if effect == "soil" else vases[0] if effect == "water" else None
    if effect == "dirt":
        w.dirt[w.location] = min(100.0, w.dirt[w.location] + 10)
    elif effect:
        w.add_mess(effect, w.location, target)
    return text.format(pet=w.pet["name"], pot=target.name if target else "")


# ---------------------------------------------------------------- tidying up after the cat

@action("tidy(乱子)", "收拾乱子（猫弄倒的盆、洒的水、掉在地上的书……）；不写参数就收拾这里所有的", 0, 1, proc=True)
def _tidy(w: World, ref: str = "") -> Proc:
    if ref:
        o = w.resolve(ref)
        if o.kind != "mess" and not o.state.get("fallen"):
            raise ActionError(f"{o.name}好好的，不用收拾。")
        messes = [m for m in w.messes() if m is o or m.state.get("target") == o.id]
    else:
        messes = w.messes()
    if not messes:
        raise ActionError("这里没有要收拾的东西。")
    done = yield from tidy_messes(w, messes)
    if not done:
        return "你还没来得及收拾。"
    w.log("clean", "收拾了" + "、".join(done))
    return "你收拾好了" + "、".join(done) + "。"


def tidy_messes(w: World, messes: list[Obj]) -> Proc:
    """Go to each mess and put things right; returns the names of what got done."""
    done: list[str] = []
    try:
        for m in messes:
            yield from walk_to(w, m.state.get("spot") or None, "tidy")
            yield work(C.MESSES[m.state["kind"]][1], "tidy", m.state.get("spot"), f"收拾{m.name}")
            _put_right(w, m)
            done.append(m.name)
    except Interrupted:
        pass
    return done


def _put_right(w: World, m: Obj) -> None:
    target = w.objects.get(m.state.get("target") or "")
    if target is not None:
        target.state["fallen"] = False
    w.dirt[m.room] = max(0.0, w.dirt[m.room] - C.MESSES[m.state["kind"]][2])
    del w.objects[m.id]


# A few words on each action, for the menu after every script.
SHORT = {
    "surroundings": "看看四周", "help": "全部动作", "goto": "走到某处", "examine": "仔细看", "inventory": "看背包", "say": "自言自语",
    "eat": "吃东西", "wait": "等一会儿", "recipes": "看菜谱", "cook": "做菜", "clean": "打扫",
    "place": "摆家具", "stow": "收家具", "water": "浇水", "open": "看信 / 拆包裹", "catalog": "看订货目录", "order": "订货",
    "sell": "放进寄售箱", "plant": "播种", "harvest": "收获", "pick": "捡东西", "fish": "钓鱼", "read": "读纸条",
    "display": "摆上收藏架", "call": "叫猫过来", "feed": "喂猫", "pet": "摸猫", "play": "陪猫玩", "tidy": "收拾乱子",
}


def menu_line(w: World) -> str:
    """'在厨房可以：recipes 看菜谱、cook 做菜……；可去：客厅' — shown after every script."""
    room = C.ROOMS[w.location]
    here = "、".join(f"{n} {SHORT.get(n, '')}".strip() for n in actions_here(w))
    exits = "、".join(C.ROOMS[e].name for e in room.exits)
    return f"在{room.name}可以：{here}；可去：{exits}（只写动作名会列出能填什么）"



# ---------------------------------------------------------------- checking a script before it runs
#
# A script runs only if every step names a real action with a sensible number of
# arguments; otherwise nothing runs and she is told what to write instead. A
# wrong name is never quietly replaced by the right one.

SYNONYMS = {
    "look": "surroundings", "see": "surroundings", "view": "surroundings", "observe": "surroundings",
    "lookaround": "surroundings", "around": "surroundings", "status": "surroundings", "看": "surroundings",
    "fix": "tidy", "repair": "tidy", "tidyup": "tidy", "cleanup": "tidy", "收拾": "tidy",
    "rest": "wait", "sleep": "wait", "nap": "wait", "idle": "wait", "relax": "wait",
    "go": "goto", "walk": "goto", "move": "goto", "travel": "goto", "enter": "goto",
    "buy": "order", "purchase": "order", "shop": "order", "shopping": "catalog", "menu": "recipes",
    "make": "cook", "cooking": "cook", "fry": "cook", "boil": "cook",
    "drink": "eat", "consume": "eat", "meal": "eat",
    "sweep": "clean", "wash": "clean", "mop": "clean",
    "grab": "pick", "collect": "pick", "pickup": "pick", "take": "pick", "gather": "pick",
    "sow": "plant", "seed": "plant", "reap": "harvest",
    "put": "place", "decorate": "place", "store": "stow",
    "pat": "pet", "stroke": "pet", "cuddle": "pet", "toy": "play", "plaything": "play",
    "talk": "say", "speak": "say", "bag": "inventory", "inv": "inventory", "items": "inventory",
    "fishing": "fish", "mail": "open", "letter": "open", "parcel": "open", "inspect": "examine", "check": "examine",
}


def suggest(name: str) -> str | None:
    """The real action a wrong name probably meant, if any."""
    key = name.strip().lower().replace("_", "")
    if key in SYNONYMS:
        return SYNONYMS[key]
    close = difflib.get_close_matches(key, list(ACTIONS), n=1, cutoff=0.6)
    return close[0] if close else None


def check_calls(calls) -> list[str]:
    """Problems that keep a script from running at all (empty if it can run)."""
    problems = []
    for i, c in enumerate(calls, 1):
        spec = ACTIONS.get(c.name)
        if spec is None:
            guess = suggest(c.name)
            hint = f"你是不是想用 {ACTIONS[guess].signature}？" if guess else "用 help() 看看有哪些动作。"
            problems.append(f"第 {i} 步：没有「{c.name}」这个动作。{hint}")
        elif len(c.args) > spec.max_args:
            problems.append(f"第 {i} 步：{c.name} 的参数太多了，用法是 {spec.signature}。")
    return problems
