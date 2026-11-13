"""Static game content: places, items, crops, recipes, fish, weather.

Everything the world can contain is declared here as plain data so new content
is added by editing tables, not logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# --------------------------------------------------------------------------- places


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    description: str
    exits: tuple[str, ...]
    outdoor: bool = False
    hints: tuple[str, ...] = ()  # actions worth mentioning here


ROOMS: dict[str, Room] = {
    r.id: r
    for r in (
        Room("living_room", "客厅", "朝南的小客厅，有一张旧沙发和一扇大窗。", ("kitchen", "bedroom", "yard"),
             hints=("rest(沙发)", "display(收藏品)", "place(家具)", "clean()")),
        Room("kitchen", "厨房", "小小的厨房，有灶台和一张两人用的木桌。", ("living_room",),
             hints=("recipes()", "cook(菜名)", "eat(食物)", "clean()")),
        Room("bedroom", "卧室", "放着一张床和一个书架的卧室。", ("living_room",),
             hints=("rest(床)", "place(家具)", "clean()")),
        Room("yard", "庭院", "屋前的小院子，有三块菜地和一个邮箱。往前走就是沙滩。", ("living_room", "beach"), outdoor=True,
             hints=("open(邮箱)", "plant(种子, 菜地)", "water(菜地)", "harvest(菜地)")),
        Room("beach", "沙滩", "细细的白沙滩，海浪会把贝壳冲上岸，岸边有一块适合钓鱼的礁石。", ("yard",), outdoor=True,
             hints=("pick(东西)", "fish()")),
    )
}

# --------------------------------------------------------------------------- items


@dataclass(frozen=True)
class Item:
    id: str  # the Chinese name doubles as id: it is what the agent types
    tags: frozenset[str] = field(default_factory=frozenset)
    fill: int = 0  # how much hunger eating it removes (0 = not edible)
    desc: str = ""


def _items(*specs: tuple) -> dict[str, Item]:
    out = {}
    for spec in specs:
        name, tags, *rest = spec
        fill = rest[0] if rest else 0
        desc = rest[1] if len(rest) > 1 else ""
        out[name] = Item(name, frozenset(tags.split()), fill, desc)
    return out


ITEMS: dict[str, Item] = _items(
    # staples (from the mailbox)
    ("鸡蛋", "ingredient", 0), ("大米", "ingredient"), ("面粉", "ingredient"), ("牛奶", "ingredient food", 10),
    ("猫粮", "petfood"),
    # produce
    ("番茄", "ingredient food produce", 10), ("萝卜", "ingredient produce"), ("生菜", "ingredient produce"),
    ("草莓", "ingredient food produce", 10), ("南瓜", "ingredient produce"), ("菠菜", "ingredient produce"),
    # seeds
    ("番茄种子", "seed"), ("萝卜种子", "seed"), ("生菜种子", "seed"), ("草莓种子", "seed"),
    ("南瓜种子", "seed"), ("菠菜种子", "seed"),
    # fish & catches
    ("小黄鱼", "fish ingredient"), ("沙丁鱼", "fish ingredient"), ("鲈鱼", "fish ingredient"),
    ("比目鱼", "fish ingredient"), ("章鱼", "fish ingredient"),
    ("旧靴子", "junk", 0, "湿漉漉的旧靴子，不知道是谁的。"),
    # collectibles
    ("白色扇贝壳", "collectible shell"), ("粉色海螺", "collectible shell"), ("带花纹的贝壳", "collectible shell"),
    ("小蛤蜊壳", "collectible shell"), ("光滑的鹅卵石", "collectible"), ("绿色海玻璃", "collectible"),
    ("漂流瓶", "collectible readable", 0, "玻璃瓶里卷着一张纸条。"),
    # dishes
    ("番茄炒蛋", "dish food", 45), ("白米饭", "dish food", 35), ("煎蛋", "dish food", 20), ("烤鱼", "dish food", 40),
    ("蔬菜沙拉", "dish food", 25), ("萝卜汤", "dish food", 30), ("南瓜粥", "dish food", 45),
    ("草莓牛奶", "dish food", 20), ("菠菜蛋饼", "dish food", 40), ("鱼汤", "dish food", 45),
    # tools
    ("鱼竿", "tool"),
    # furniture / decor
    ("小地毯", "furniture"), ("台灯", "furniture"), ("挂画", "furniture"), ("风铃", "furniture"),
    ("小书桌", "furniture"), ("懒人沙发", "furniture"), ("花瓶", "furniture"),
)

# --------------------------------------------------------------------------- crops

SPRING, SUMMER, AUTUMN, WINTER = "spring", "summer", "autumn", "winter"


@dataclass(frozen=True)
class Crop:
    name: str
    seed: str
    days: float  # game days of watered growth to ripen
    seasons: frozenset[str]
    yield_count: int = 2


CROPS: dict[str, Crop] = {
    c.seed: c
    for c in (
        Crop("番茄", "番茄种子", 4, frozenset({SPRING, SUMMER})),
        Crop("草莓", "草莓种子", 5, frozenset({SPRING})),
        Crop("生菜", "生菜种子", 3, frozenset({SPRING, AUTUMN})),
        Crop("萝卜", "萝卜种子", 3, frozenset({AUTUMN, WINTER})),
        Crop("菠菜", "菠菜种子", 3, frozenset({AUTUMN, WINTER})),
        Crop("南瓜", "南瓜种子", 6, frozenset({SUMMER, AUTUMN}), yield_count=1),
    )
}
SEEDS_BY_SEASON = {s: [c.seed for c in CROPS.values() if s in c.seasons] for s in (SPRING, SUMMER, AUTUMN, WINTER)}

# --------------------------------------------------------------------------- recipes

# Ingredient keys are item names, or "#tag" for "any item with this tag".
RECIPES: dict[str, dict[str, int]] = {
    "番茄炒蛋": {"番茄": 1, "鸡蛋": 2},
    "白米饭": {"大米": 1},
    "煎蛋": {"鸡蛋": 1},
    "烤鱼": {"#fish": 1},
    "蔬菜沙拉": {"生菜": 1, "番茄": 1},
    "萝卜汤": {"萝卜": 1},
    "南瓜粥": {"南瓜": 1, "大米": 1},
    "草莓牛奶": {"草莓": 1, "牛奶": 1},
    "菠菜蛋饼": {"菠菜": 1, "鸡蛋": 1, "面粉": 1},
    "鱼汤": {"#fish": 1, "萝卜": 1},
}

# --------------------------------------------------------------------------- fishing

# (item, weight); None = nothing bit
FISH_TABLE: dict[str, list[tuple[str | None, int]]] = {
    SPRING: [(None, 40), ("小黄鱼", 25), ("沙丁鱼", 20), ("鲈鱼", 8), ("旧靴子", 5), ("漂流瓶", 2)],
    SUMMER: [(None, 35), ("沙丁鱼", 25), ("鲈鱼", 15), ("章鱼", 8), ("小黄鱼", 10), ("旧靴子", 5), ("漂流瓶", 2)],
    AUTUMN: [(None, 40), ("鲈鱼", 22), ("小黄鱼", 18), ("比目鱼", 12), ("旧靴子", 6), ("漂流瓶", 2)],
    WINTER: [(None, 50), ("比目鱼", 22), ("小黄鱼", 18), ("旧靴子", 7), ("漂流瓶", 3)],
}

BEACH_FINDS: list[tuple[str, int]] = [
    ("白色扇贝壳", 30), ("小蛤蜊壳", 25), ("带花纹的贝壳", 15), ("粉色海螺", 10),
    ("光滑的鹅卵石", 12), ("绿色海玻璃", 6), ("漂流瓶", 2),
]

BOTTLE_NOTES = (
    "「今天的海是灰蓝色的。希望捡到这张纸条的人，那天是晴天。」",
    "「我在很远的岛上种了一棵柠檬树，它今年第一次结果了。」",
    "「如果你也睡不着，就数一数海浪吧，我数到了三百二十一。」",
    "「致未来的某人：请替我看一眼今晚的月亮。」",
    "「这张纸条已经在海上漂了很久，它想找个地方歇一歇。」",
)

# --------------------------------------------------------------------------- weather

WEATHER_TABLE: dict[str, list[tuple[str, int]]] = {
    SPRING: [("晴", 4), ("多云", 3), ("小雨", 3), ("阴", 2)],
    SUMMER: [("晴", 5), ("多云", 2), ("雷阵雨", 2), ("小雨", 1)],
    AUTUMN: [("晴", 4), ("多云", 3), ("阴", 2), ("小雨", 2)],
    WINTER: [("晴", 3), ("阴", 3), ("小雪", 2), ("多云", 2)],
}
RAINY = {"小雨", "雷阵雨"}

# --------------------------------------------------------------------------- mailbox

MAIL_STAPLES = ["鸡蛋", "鸡蛋", "大米", "牛奶", "面粉", "猫粮"]
MAIL_FURNITURE = ["小地毯", "台灯", "挂画", "风铃", "小书桌", "懒人沙发", "花瓶"]
MAIL_HOUR = 9

# --------------------------------------------------------------------------- starting state

START_INVENTORY = {"鱼竿": 1, "鸡蛋": 2, "大米": 2, "猫粮": 3, "萝卜种子": 2, "菠菜种子": 1}
PET_NAME = "团子"
INDOOR_ROOMS = ("living_room", "kitchen", "bedroom")
