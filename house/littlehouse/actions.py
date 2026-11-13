"""Actions the resident can take. Each one is callable from the pseudo-code.

An action receives the world plus already-parsed arguments and returns a short
line of text describing what happened (or raises ``ActionError``). Many take an
optional argument: without it they act on everything that fits here
(``water()`` waters every plant/plot in the room), which saves the agent turns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import content as C
from .world import ActionError, Obj, World, _weighted

TIRED_THRESHOLD = 5.0


@dataclass
class ActionSpec:
    name: str
    signature: str
    help: str
    fn: Callable[..., str]
    min_args: int
    max_args: int
    effort: float  # energy cost; 0 = free


ACTIONS: dict[str, ActionSpec] = {}


def action(signature: str, help: str, min_args: int = 0, max_args: int = 0, effort: float = 0.0):
    def wrap(fn: Callable[..., str]) -> Callable[..., str]:
        name = signature.split("(")[0]
        ACTIONS[name] = ActionSpec(name, signature, help, fn, min_args, max_args, effort)
        return fn

    return wrap


def help_text() -> str:
    return "\n".join(f"{a.signature:<20} {a.help}" for a in ACTIONS.values())


def perform(w: World, name: str, args: list) -> str:
    """Run one action with its energy cost applied."""
    spec = ACTIONS[name]
    if spec.effort and w.resident["energy"] < TIRED_THRESHOLD:
        raise ActionError("你太累了，做不动了。先 rest() 歇一歇，或者吃点东西。")
    text = spec.fn(w, *args)
    if spec.effort:
        w.resident["energy"] = max(0.0, w.resident["energy"] - spec.effort)
    return text


# ---------------------------------------------------------------- helpers


def _need_room(w: World, *rooms: str) -> None:
    if w.location not in rooms:
        names = "或".join(C.ROOMS[r].name for r in rooms)
        raise ActionError(f"这件事要在{names}做。")


def _need_indoor(w: World) -> None:
    if C.ROOMS[w.location].outdoor:
        raise ActionError("这件事要在屋里做。")


def _pet_here(w: World) -> dict:
    p = w.pet
    if p["room"] != w.location:
        raise ActionError(f"{p['name']}不在这里。可以试试 call() 叫它过来。")
    return p


def _minutes_since(w: World, ts: float) -> float:
    return (w.clock.timestamp() - ts) / 60.0


# ---------------------------------------------------------------- looking around


@action("look()", "看看四周")
def _look(w: World) -> str:
    return w.look()


@action("help()", "列出所有动作")
def _help(w: World) -> str:
    return help_text()


@action("goto(地点)", "走到某处（自动穿过中间的房间），如 goto(沙滩)", 1, 1)
def _goto(w: World, place: str) -> str:
    room = w.resolve_room(place)
    if room.id == w.location:
        return f"你已经在{room.name}了。"
    path = w.path_to(room.id)
    w.location = room.id
    w.log("move", f"走到了{room.name}")
    via = "、".join(C.ROOMS[r].name for r in path[:-1])
    return f"你{'穿过' + via + '，' if via else ''}来到了{room.name}。"


@action("examine(东西)", "仔细看某样东西（也可以是背包里的物品）", 1, 1)
def _examine(w: World, ref: str) -> str:
    ref = str(ref)
    try:
        o = w.resolve(ref)
    except ActionError:
        name = w.item_name(ref)
        item = C.ITEMS.get(name)
        return f"{name}：{item.desc or '没什么特别的。'}" if item else f"{name}。"
    if o.id == "shelf":
        return "收藏架上摆着：" + (w.format_items(w.shelf) if w.shelf else "什么都还没有。")
    if o.id == "mailbox":
        return "邮箱里有：" + w.format_items(w.mailbox) if w.mailbox else "邮箱是空的。"
    if o.kind == "plant":
        return f"{w.describe_obj(o)}，土壤湿度大约 {o.state.get('water', 0):.0f}%。"
    if o.kind == "plot" and o.state.get("seed"):
        crop = C.CROPS[o.state["seed"]]
        pct = min(100, o.state.get("growth", 0) / crop.days * 100)
        return f"{w.describe_obj(o)}，长到了大约 {pct:.0f}%。{crop.name}适合{'、'.join(_season_names(crop.seasons))}种。"
    if o.kind == "find":
        return f"沙滩上的{o.name}，被海水冲得很干净。"
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


@action("rest(地点)", "在沙发或床上歇一会儿，恢复精力", 0, 1)
def _rest(w: World, ref: str = "") -> str:
    if ref:
        o = w.resolve(ref)
        if o.id not in ("sofa", "bed"):
            raise ActionError(f"不能在{o.name}上休息。")
        where = o
    else:
        spot = {"living_room": "sofa", "bedroom": "bed"}.get(w.location)
        if spot is None:
            raise ActionError("这里没地方躺，去客厅或卧室吧。")
        where = w.objects[spot]
    if _minutes_since(w, w.resident.get("last_rest", 0.0)) < 60:
        return f"你在{where.name}上躺了一下，但刚歇过，没什么困意。"
    gain = 25.0 if where.id == "bed" else 15.0
    w.resident["energy"] = min(100.0, w.resident["energy"] + gain)
    w.resident["last_rest"] = w.clock.timestamp()
    w.log("rest", f"在{where.name}上歇了一会儿")
    return f"你在{where.name}上歇了一会儿，精神好多了。"


@action("eat(食物)", "吃东西", 1, 1)
def _eat(w: World, ref: str) -> str:
    name = w.item_name(ref)
    item = C.ITEMS.get(name)
    if item is None or item.fill <= 0:
        raise ActionError(f"{name}不能直接吃。看看 recipes() 能做成什么。")
    w.take_item(name)
    w.resident["hunger"] = max(0.0, w.resident["hunger"] - item.fill)
    w.log("eat", f"吃了{name}")
    full = "饱饱的" if w.resident["hunger"] < 20 else "垫了垫肚子"
    return f"你吃了{name}，{full}。"


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


@action("recipes()", "看看会做哪些菜，以及现在缺什么")
def _recipes(w: World) -> str:
    lines = []
    for dish, ing in C.RECIPES.items():
        ok, _, missing = _recipe_status(w, ing)
        need = "、".join(f"{'任意一条鱼' if k == '#fish' else k}{'×' + str(n) if n > 1 else ''}" for k, n in ing.items())
        lines.append(f"{'✓' if ok else '✗'} {dish}（{need}）" + ("" if ok else f" 缺：{'、'.join(missing)}"))
    return "\n".join(lines)


@action("cook(菜名)", "在厨房做菜，如 cook(番茄炒蛋)", 1, 1, effort=3)
def _cook(w: World, dish: str) -> str:
    _need_room(w, "kitchen")
    dish = str(dish).strip()
    if dish not in C.RECIPES:
        raise ActionError(f"不会做「{dish}」。用 recipes() 看看菜谱。")
    ok, use, missing = _recipe_status(w, C.RECIPES[dish])
    if not ok:
        raise ActionError(f"做{dish}还缺：{'、'.join(missing)}。")
    for name, n in use.items():
        w.take_item(name, n)
    w.add_item(dish)
    w.dirt["kitchen"] = min(100.0, w.dirt["kitchen"] + 8.0)
    w.log("cook", f"用{w.format_items(use)}做了{dish}")
    return f"灶台上冒起热气，你做好了{dish}。"


# ---------------------------------------------------------------- housework


@action("clean()", "打扫当前房间", effort=5)
def _clean(w: World) -> str:
    _need_indoor(w)
    before = w.dirt[w.location]
    w.dirt[w.location] = 0.0
    room = C.ROOMS[w.location].name
    w.log("clean", f"打扫了{room}")
    return f"你把{room}打扫得干干净净。" if before >= 40 else f"{room}本来就挺干净，你又擦了擦。"


@action("place(家具)", "把背包里的家具摆在当前房间", 1, 1, effort=2)
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


@action("stow(家具)", "把摆着的家具收回背包", 1, 1, effort=2)
def _stow(w: World, ref: str) -> str:
    o = w.resolve(ref)
    if o.kind != "decor":
        raise ActionError(f"{o.name}收不起来。")
    del w.objects[o.id]
    w.add_item(o.name)
    w.log("decorate", f"把{o.name}收了起来")
    return f"你把{o.name}收进了背包。"


@action("water(植物)", "浇水；不写参数就浇这里所有的植物和菜地", 0, 1, effort=1)
def _water(w: World, ref: str = "") -> str:
    targets = [w.resolve(ref)] if ref else [o for o in w.here() if o.kind in ("plant", "plot")]
    if not targets:
        raise ActionError("这里没有需要浇水的东西。")
    for o in targets:
        if o.kind not in ("plant", "plot"):
            raise ActionError(f"{o.name}不需要浇水。")
        o.state["water"] = 100.0
    names = "、".join(o.name for o in targets)
    w.log("care", f"给{names}浇了水")
    return f"你给{names}浇了水。"


# ---------------------------------------------------------------- yard


@action("open(邮箱)", "打开邮箱，把里面的东西拿出来", 1, 1)
def _open(w: World, ref: str) -> str:
    o = w.resolve(ref)
    if o.id != "mailbox":
        raise ActionError(f"{o.name}打不开。")
    if not w.mailbox:
        return "邮箱是空的。"
    got = dict(w.mailbox)
    for name, n in got.items():
        w.add_item(name, n)
    w.mailbox.clear()
    w.log("mail", f"从邮箱里拿到了{w.format_items(got)}")
    return f"邮箱里有：{w.format_items(got)}。你都拿了出来。"


@action("plant(种子, 菜地)", "在菜地播种，如 plant(萝卜种子)；不写菜地就种在第一块空地", 1, 2, effort=2)
def _plant(w: World, seed_ref: str, plot_ref: str = "") -> str:
    _need_room(w, "yard")
    seed = w.item_name(seed_ref)
    if seed not in C.CROPS:
        raise ActionError(f"{seed}不是种子。")
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


@action("harvest(菜地)", "收获成熟的作物；不写参数就收这里所有熟了的", 0, 1, effort=2)
def _harvest(w: World, ref: str = "") -> str:
    plots = [w.resolve(ref)] if ref else [o for o in w.here() if o.kind == "plot" and o.state.get("ripe")]
    if not plots:
        raise ActionError("这里没有可以收获的作物。")
    got: dict[str, int] = {}
    for p in plots:
        if not p.state.get("ripe"):
            raise ActionError(f"{p.name}里的东西还没熟。")
        crop = C.CROPS[p.state["seed"]]
        w.add_item(crop.name, crop.yield_count)
        got[crop.name] = got.get(crop.name, 0) + crop.yield_count
        p.state.update({"seed": None, "growth": 0.0, "ripe": False})
    w.log("farm", f"收获了{w.format_items(got)}")
    return f"你收获了{w.format_items(got)}！"


# ---------------------------------------------------------------- beach


@action("pick(东西)", "捡起地上的小东西；不写参数就捡这里所有的", 0, 1, effort=1)
def _pick(w: World, ref: str = "") -> str:
    finds = [w.resolve(ref)] if ref else [o for o in w.here() if o.kind == "find"]
    if not finds:
        raise ActionError("这里没有可以捡的东西。")
    for o in finds:
        if o.kind != "find":
            raise ActionError(f"{o.name}拿不起来。")
    names: dict[str, int] = {}
    for o in finds:
        del w.objects[o.id]
        w.add_item(o.state["item"])
        names[o.state["item"]] = names.get(o.state["item"], 0) + 1
    text = w.format_items(names)
    w.log("collect", f"在{C.ROOMS[w.location].name}捡到了{text}")
    return f"你捡起了{text}。"


@action("fish()", "在沙滩的礁石上钓鱼（需要鱼竿）", effort=4)
def _fish(w: World) -> str:
    _need_room(w, "beach")
    if w.inventory.get("鱼竿", 0) < 1:
        raise ActionError("你没有鱼竿。")
    weather = w.weather()
    if weather == "雷阵雨":
        raise ActionError("在打雷，礁石上太危险了，改天再钓吧。")
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
    return f"{p['name']}从{came_from}小跑着过来了。"


@action("feed(食物)", "喂猫（默认用猫粮，鱼也行）", 0, 1)
def _feed(w: World, ref: str = "") -> str:
    p = _pet_here(w)
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
    p["affection"] = min(100.0, p["affection"] + (8 if food != "猫粮" else 4))
    p["hungry_noted"] = False
    w.log("pet", f"喂{p['name']}吃了{food}")
    return f"{p['name']}{'狼吞虎咽地' if was_hungry else '慢悠悠地'}吃完了{food}，蹭了蹭你的手。"


@action("pet()", "摸摸猫咪")
def _pet(w: World) -> str:
    p = _pet_here(w)
    if _minutes_since(w, p.get("last_pet", 0.0)) < 30:
        return f"{p['name']}已经被摸够了，甩甩尾巴走开了两步。"
    p["affection"] = min(100.0, p["affection"] + 6)
    p["last_pet"] = w.clock.timestamp()
    w.log("pet", f"摸了摸{p['name']}")
    if p["affection"] >= 60:
        return f"{p['name']}翻过肚皮，发出呼噜呼噜的声音。"
    return f"{p['name']}眯起眼睛，蹭了蹭你的手。"
