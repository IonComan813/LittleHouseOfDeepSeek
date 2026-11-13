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
        Room("living_room", "客厅", "朝南的小客厅，木地板，有一张红色布艺沙发和一扇大窗；圆木桌上放着开拓署的订货目录。", ("kitchen", "bedroom", "yard"),
             hints=("catalog()", "order(物品, 数量)", "rest(沙发)", "display(收藏品)", "place(家具)", "clean()")),
        Room("kitchen", "厨房", "小小的厨房，铺着粉白相间的格子地砖；靠墙是灶台、带水槽的台面和一台白色冰箱，中间有一张两人用的木桌。", ("living_room",),
             hints=("recipes()", "cook(菜名)", "eat(食物)", "clean()")),
        Room("bedroom", "卧室", "木地板的卧室，有一张床、一个书架和一个木衣柜。", ("living_room",),
             hints=("rest(床)", "place(家具)", "clean()")),
        Room("yard", "庭院", "屋前的小草地院子，有三块菜地、一个邮箱和开拓署的寄售箱，东边长着一棵树，角落里有几丛灌木，院子和沙滩之间隔着一道矮木篱笆。往前走就是沙滩。", ("living_room", "beach"), outdoor=True,
             hints=("open(邮箱)", "open(包裹)", "sell(物品, 数量)", "plant(种子, 菜地)", "water()", "harvest()")),
        Room("beach", "沙滩", "细细的白沙滩，海浪会把贝壳冲上岸，岸边有一块适合钓鱼的礁石。", ("yard",), outdoor=True,
             hints=("pick(东西)", "fish()")),
    )
}

# --------------------------------------------------------------------------- appearance
#
# How things LOOK. The renderer (render.py) draws exactly this, and the text
# (examine, room descriptions, item descriptions) says exactly this — keep the
# two in step: if the picture changes, change the words here too, and anything
# drawn must appear here (tests/test_consistency.py checks the drawn set).

APPEARANCE: dict[str, str] = {
    # fixtures (by object id)
    "sofa": "红色的布艺沙发，左边放着一个黄色的小靠垫。",
    "bed": "木床，白色的枕头，盖着红色的被子。",
    "bookshelf": "深色的木书架，两层都塞满了五颜六色的书。",
    "wardrobe": "两扇门的木衣柜，门上有黄铜小把手。",
    "shelf": "两层的木架子，用来摆收藏品。",
    "stove": "灰色的灶台，黑色台面上有两个灶眼。",
    "table": "浅色的木桌，配两张小木凳。",
    "fridge": "白色的冰箱，门上贴着一个红色的冰箱贴。",
    "counter": "靠墙的木台面，中间嵌着一个水槽。",
    "mailbox": "立在木桩上的蓝色邮箱，有信的时候会竖起一面红色小旗。",
    "consign": "开拓署的木制寄售箱，侧面有一道青绿色的标记。",
    "parcel": "用胶带封好的纸箱。",
    "rock": "岸边一块圆圆的灰色大礁石。",
    "tree": "一棵圆冠的树：春天是嫩绿色、缀着粉色小花，夏天深绿，秋天橙黄，冬天叶子掉光、枝头泛白。",
    "pot#1": "种在红陶盆里的绿萝。",
    "pot#2": "种在红陶盆里的一小簇多肉。",
    # furniture items (by item name)
    "小地毯": "椭圆形的地毯，中间是粉色，镶着一圈紫色的边。",
    "台灯": "奶白色灯罩的小台灯，晚上亮起暖黄色的光。",
    "挂画": "木框里画着蓝天、太阳和一片绿地。",
    "风铃": "浅蓝色的风铃，下面挂着三根小管子。",
    "小书桌": "浅木色的小书桌，桌上放着一张白纸。",
    "懒人沙发": "青绿色的豆袋懒人沙发。",
    "花瓶": "蓝色的花瓶，插着红、黄、粉三朵花。",
    # the cat
    "团子": "一只橘猫。",
}

# Static scenery drawn in the picture that is also a world object (examine-able).
SCENERY = {"fridge": ("冰箱", "kitchen"), "counter": ("水槽", "kitchen"), "wardrobe": ("衣柜", "bedroom"), "tree": ("树", "yard")}

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
    ("焦掉的菜", "dish food", 10, "黑乎乎的，勉强能吃。"),
    # things found while cleaning
    ("纽扣", "collectible", 0, "一颗小小的木纽扣，不知道是从哪件衣服上掉的。"),
    ("毛线球", "collectible", 0, "团子藏起来的毛线球，已经被抓得毛毛的。"),
    ("玻璃弹珠", "collectible", 0, "里面裹着一道蓝色的花纹。"),
    ("旧照片", "collectible", 0, "泛黄的照片：一群人站在还没修好的码头前，笑得很开心。背面写着「潮汐湾 第一年」。"),
    ("发卡", "collectible", 0, "一枚贝壳形状的发卡。"),
    ("浮木", "collectible", 0, "被海水磨得很光滑的一截浮木，形状像一只鸟。"),
    # tools
    ("鱼竿", "tool"),
    # furniture / decor
    ("小地毯", "furniture", 0, APPEARANCE["小地毯"]), ("台灯", "furniture", 0, APPEARANCE["台灯"]),
    ("挂画", "furniture", 0, APPEARANCE["挂画"]), ("风铃", "furniture", 0, APPEARANCE["风铃"]),
    ("小书桌", "furniture", 0, APPEARANCE["小书桌"]), ("懒人沙发", "furniture", 0, APPEARANCE["懒人沙发"]),
    ("花瓶", "furniture", 0, APPEARANCE["花瓶"]),
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

# --------------------------------------------------------------------------- lore & economy
#
# 小屋在「潮汐湾」：一片正在慢慢恢复的海岸。开拓署（负责这片海岸重建的机构）把一些
# 定居者安置在这里，每周一寄来基本补给；其余的东西要自己挣：把作物、鱼和捡到的
# 小东西放进院子里的寄售箱，傍晚快递员阿陆会收走，按开拓署的收购价付「贝币」。
# 想要别的东西，就在客厅的订货目录上下单，阿陆第二天上午送到门口。

CURRENCY = "贝币"
START_MONEY = 300
COURIER = "快递员阿陆"
DELIVERY_HOUR = 9  # orders and the weekly supply arrive after this hour
PICKUP_HOUR = 18  # the consignment box is emptied after this hour
SUPPLY_WEEKDAY = 0  # Monday

# What the bureau pays for things put in the consignment box.
SELL_PRICES: dict[str, int] = {
    "番茄": 12, "萝卜": 10, "生菜": 10, "草莓": 18, "南瓜": 30, "菠菜": 10,
    "小黄鱼": 15, "沙丁鱼": 10, "鲈鱼": 25, "比目鱼": 30, "章鱼": 45, "旧靴子": 1,
    "白色扇贝壳": 3, "小蛤蜊壳": 2, "带花纹的贝壳": 6, "粉色海螺": 10, "光滑的鹅卵石": 2, "绿色海玻璃": 12,
    "浮木": 8, "玻璃弹珠": 5,
    "番茄炒蛋": 20, "烤鱼": 30, "南瓜粥": 40, "鱼汤": 40, "菠菜蛋饼": 25, "萝卜汤": 18,
}

# The bureau's order catalog: item -> price.
CATALOG: dict[str, int] = {
    "番茄种子": 15, "萝卜种子": 10, "生菜种子": 10, "草莓种子": 25, "南瓜种子": 30, "菠菜种子": 10,
    "鸡蛋": 6, "大米": 8, "面粉": 8, "牛奶": 8, "猫粮": 10,
    "风铃": 60, "花瓶": 70, "台灯": 90, "小地毯": 120, "挂画": 150, "小书桌": 220, "懒人沙发": 260,
}

WEEKLY_SUPPLY = {"大米": 2, "鸡蛋": 4, "猫粮": 4, "牛奶": 1}

WELCOME_LETTER = (
    "【开拓署 · 欢迎信】欢迎来到潮汐湾！这间小屋和院子从今天起就是你的了。"
    "每周一上午，我们会把基本补给（大米、鸡蛋、牛奶、猫粮）送到你门口。"
    "其他需要的东西请在客厅的订货目录上下单（catalog() 查看，order() 下单），快递员阿陆第二天上午送达。"
    "院子里的寄售箱是开拓署的收购点：把作物、鱼或者海边捡到的东西放进去（sell()），"
    "傍晚六点阿陆会收走，货款直接记到你的账上。祝你在这里住得开心。"
)
SUPPLY_LETTER = "【开拓署】本周补给已送达门口，请查收。如有需要请随时订货。"
LETTERS = (
    "【阿陆的便条】今天送货路上看见海豚了！就在你家沙滩外面一点点。",
    "【开拓署通知】码头修缮进度过半，下个季度会通一班渡船。",
    "【邻岛的来信】你好呀，我是灯塔岛的守塔人。听说潮汐湾有新的定居者，送你一句问候。夜里如果看见灯光闪三下，那是我在打招呼。",
    "【开拓署通知】近期海况良好，礁石附近鲈鱼较多，请注意安全。",
    "【阿陆的便条】你家的猫上次朝我哈气了。下次我带小鱼干来贿赂它。",
)

# --------------------------------------------------------------------------- surprises

# Found while cleaning a room (chance grows with how dirty it was).
CLEAN_FINDS: list[tuple[str, int]] = [
    ("@coins", 30), ("纽扣", 15), ("毛线球", 20), ("玻璃弹珠", 15), ("发卡", 10), ("旧照片", 5),
]

# One may happen on a given morning (about every other day).
DAILY_EVENTS: list[tuple[str, str | None, int]] = [
    ("清晨起了一场大雾，海面白茫茫的", None, 10),
    ("一群海鸥落在院子的篱笆上，叫了好一阵", None, 10),
    ("沙滩上冲来一截形状很好看的浮木", "浮木", 6),
    ("夜里听见远处灯塔岛传来汽笛声", None, 6),
    ("团子在窗台上抓到了一只蛾子，得意地叼来叼去", None, 8),
    ("院子角落里开了一朵不认识的小黄花", None, 8),
    ("早上的海水退得很远，露出一大片湿亮的沙滩", None, 6),
]

DREAMS = (
    "梦见自己在海面上走路，脚下的水凉凉的。",
    "梦见团子会说话，它说想吃三条鱼。",
    "梦见小屋长出了第二层楼，楼上全是书。",
    "梦见下了一场贝壳雨，叮叮当当的。",
    "梦见在灯塔上看星星，星星离得很近。",
)

# --------------------------------------------------------------------------- the cat's temper (rolled once per day)

PET_TEMPERS: list[tuple[str, int]] = [("黏人", 30), ("平常", 40), ("傲娇", 20), ("烦躁", 10)]

# --------------------------------------------------------------------------- starting state

START_INVENTORY = {"鱼竿": 1, "鸡蛋": 2, "大米": 2, "猫粮": 3, "萝卜种子": 2, "菠菜种子": 1}
PET_NAME = "团子"
INDOOR_ROOMS = ("living_room", "kitchen", "bedroom")
