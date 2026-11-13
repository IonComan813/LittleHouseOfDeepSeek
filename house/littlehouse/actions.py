"""Actions the resident can take. Each one is callable from the pseudo-code.

An action receives the world plus already-parsed arguments and returns a short
line of text describing what happened (or raises ``ActionError``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .world import ROOMS, ActionError, World


@dataclass
class ActionSpec:
    name: str
    signature: str
    help: str
    fn: Callable[..., str]
    min_args: int
    max_args: int


ACTIONS: dict[str, ActionSpec] = {}


def action(signature: str, help: str, min_args: int = 0, max_args: int = 0):
    def wrap(fn: Callable[..., str]) -> Callable[..., str]:
        name = signature.split("(")[0]
        ACTIONS[name] = ActionSpec(name, signature, help, fn, min_args, max_args)
        return fn

    return wrap


def help_text() -> str:
    return "\n".join(f"{a.signature:<22} {a.help}" for a in ACTIONS.values())


# --------------------------------------------------------------------------- actions


@action("look()", "看看四周（时间、天气、所在位置、能看到的东西）")
def _look(w: World) -> str:
    return w.look()


@action("goto(地点)", "走到某个地方（会自动穿过中间的房间），例如 goto(沙滩)", 1, 1)
def _goto(w: World, place: str) -> str:
    room = w.resolve_room(str(place))
    if room.id == w.location:
        return f"你已经在{room.name}了。"
    path = w.path_to(room.id)
    w.location = room.id
    w.log("move", f"走到了{room.name}")
    via = "、".join(ROOMS[r].name for r in path[:-1])
    return f"你{'穿过' + via + '，' if via else ''}来到了{room.name}。"


@action("examine(东西)", "仔细看某样东西", 1, 1)
def _examine(w: World, ref: str) -> str:
    o = w.resolve(str(ref))
    if o.kind == "plant":
        return f"{w.describe_obj(o)}，土壤湿度大约 {o.state.get('water', 0):.0f}%。"
    if o.kind == "shell":
        return f"一枚{o.name}，被海水冲得很干净。"
    return w.describe_obj(o) + "。"


@action("water(植物)", "给植物浇水", 1, 1)
def _water(w: World, ref: str) -> str:
    o = w.resolve(str(ref))
    if o.kind != "plant":
        raise ActionError(f"{o.name}不需要浇水。")
    before = o.state.get("water", 0)
    o.state["water"] = 100.0
    w.log("care", f"给{o.name}浇了水（之前湿度约 {before:.0f}%）")
    return f"你给{o.name}浇了水，土壤吸饱了水分。"


@action("pick(东西)", "捡起地上的小东西（比如贝壳）", 1, 1)
def _pick(w: World, ref: str) -> str:
    o = w.resolve(str(ref))
    if o.kind not in ("shell",):
        raise ActionError(f"{o.name}拿不起来。")
    o.room = "inventory"
    w.inventory.append(o.id)
    w.log("collect", f"在{ROOMS[w.location].name}捡到了{o.name}")
    return f"你捡起了{o.name}，放进口袋。"


@action("inventory()", "查看背包")
def _inventory(w: World) -> str:
    if not w.inventory:
        return "背包是空的。"
    return "背包：" + "、".join(f"{w.objects[i].name}[{i}]" for i in w.inventory)


@action("rest(地点)", "在沙发或床上歇一会儿", 0, 1)
def _rest(w: World, ref: str = "") -> str:
    if ref:
        o = w.resolve(str(ref))
        if o.id not in ("sofa", "bed"):
            raise ActionError(f"不能在{o.name}上休息。")
        where = o.name
    else:
        where = {"living_room": "沙发", "bedroom": "床"}.get(w.location)
        if where is None:
            raise ActionError("这里没地方躺，去客厅或卧室吧。")
    w.log("rest", f"在{where}上歇了一会儿")
    return f"你在{where}上歇了一会儿。"


@action("say(内容)", "自言自语（会被记进日记）", 1, 1)
def _say(w: World, text: str) -> str:
    w.log("say", f"自言自语：「{text}」")
    return f"你小声说：「{text}」"


@action("help()", "列出所有可用动作")
def _help(w: World) -> str:
    return help_text()
