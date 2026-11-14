"""Pixel-art rendering of the world (pygame-ce).

Everything is drawn procedurally at 1x (16 px tiles) in a warm pastoral
palette and scaled up with nearest-neighbour, so no image assets are needed.
Works without a window: ``render_png(world)`` is used by the house server to
give the resident (and anyone) a picture, and the read-only viewer window
draws the same surface.
"""

from __future__ import annotations

import hashlib
import io
import math
import os
import random
import time

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

from . import content as C  # noqa: E402
from . import scene as S  # noqa: E402
from .anim import Pose, current_pose  # noqa: E402
from .clock import season_of  # noqa: E402

T = S.TILE
W, H = S.COLS * T, S.ROWS * T

# --------------------------------------------------------------------------- palette (warm pastoral)

PAL = {
    "k": (59, 42, 38), "w": (166, 110, 72), "W": (196, 140, 92), "d": (120, 78, 52),
    "c": (245, 232, 200), "C": (225, 205, 165), "x": (255, 252, 240),
    "g": (106, 160, 80), "G": (150, 196, 104), "h": (70, 118, 62),
    "r": (226, 108, 90), "R": (176, 72, 64), "y": (244, 200, 96), "o": (232, 150, 72),
    "b": (96, 150, 200), "B": (150, 196, 226), "n": (60, 86, 130),
    "s": (238, 214, 160), "S": (220, 190, 130), "p": (240, 170, 180), "P": (170, 130, 190),
    "e": (150, 146, 140), "E": (204, 198, 190), "f": (248, 212, 180), "F": (110, 70, 50),
    "t": (140, 98, 64), "T": (98, 66, 46), "q": (90, 170, 160),
    # the whale girl
    "u": (58, 98, 200), "U": (110, 160, 236), "v": (34, 50, 112), "i": (60, 130, 230),
    "M": (52, 92, 186), "m": (250, 250, 255),
}

# The resident: a blue-haired whale girl (ahoge, fin ears, whale tail, blue
# and white maid dress with a little whale on the apron). 20x28, two walk frames.
_GIRL_TOP = [
    ".........U..........",
    "........UU..........",
    "......uuuuuuu.......",
    ".....uuuuuuuuu......",
    "....uuuuuuuuuuu.....",
    "....uuuUuuuuUuu.....",
    "....uuffffffffu.....",
    ".vu.uffiiffiiffu.uv.",
    ".vuuuffiiffiifuuuv..",
    "..vu.ufpffffpfu.uv..",
    ".....uuffffffuu.....",
    "....uuuffrrffuuu....",
    "....uuu.ffff.uuu....",
    "....uuMMmmmmMMuu....",
    "...uuMMMmMMmMMMuu...",
    "...uuMMmmmmmmMMuu...",
    "..ufMMmmmmmmmmMMfu..",
    "...uMMmmmBmmmmMMu...",
    "...uMMmmmmmmmmMMu.vv",
    "..uMMMmmmmmmmmMMMuvv",
    "..MMMMMmmmmmmMMMMvuv",
    "..MmMmMmMmMmMmMmM.vv",
    "...MMMMMMMMMMMMM..v.",
]
RESIDENT = _GIRL_TOP + [
    ".....xx....xx.......",
    ".....xx....xx.......",
    ".....xx....xx.......",
    "....kkk....kkk......",
    "....................",
]
RESIDENT_STEP = _GIRL_TOP + [
    "......xx..xx........",
    ".....xx....xx.......",
    "....xx......xx......",
    "...kkk......kkk.....",
    "....................",
]
CAT = [
    "...o.....o......",
    "...oo...oo......",
    "...ooooooo......",
    "..oookoookoo....",
    "..ooooopoooo....",
    "...oooxooo......",
    "....ooooo.......",
    "...ooooooo....o.",
    "..ooyoooyooo..o.",
    "..oooooooooo.o..",
    "..ooooooooooo...",
    "..ooxoooooxoo...",
    "...oo.....oo....",
    "................",
]
CAT_ASLEEP = [
    "................",
    "..o.o...........",
    "..ooooooooooo...",
    ".okookooooooooo.",
    ".oooooyoooyoooo.",
    "..oooooooooooooo",
    "...ooooooooooo..",
    "................",
]

DIGITS = {
    "0": ["111", "101", "101", "101", "111"], "1": ["010", "110", "010", "010", "111"],
    "2": ["111", "001", "111", "100", "111"], "3": ["111", "001", "111", "001", "111"],
    "4": ["101", "101", "111", "001", "001"], "5": ["111", "100", "111", "001", "111"],
    "6": ["111", "100", "111", "101", "111"], "7": ["111", "001", "010", "010", "010"],
    "8": ["111", "101", "111", "101", "111"], "9": ["111", "101", "111", "001", "111"],
    ":": ["0", "1", "0", "1", "0"], "-": ["000", "000", "111", "000", "000"],
}

CROP_COLORS = {
    "番茄": "r", "草莓": "r", "生菜": "G", "萝卜": "x", "菠菜": "h", "南瓜": "o",
    "土豆": "S", "黄瓜": "h", "白菜": "C", "葱": "G",
}
FIND_LOOKS = {
    "白色扇贝壳": ("fan", "x"), "小蛤蜊壳": ("fan", "C"), "带花纹的贝壳": ("fan", "S"),
    "粉色海螺": ("conch", "p"), "光滑的鹅卵石": ("pebble", "E"), "绿色海玻璃": ("pebble", "q"),
    "漂流瓶": ("bottle", "B"), "浮木": ("wood", "W"),
}
SHELF_DOTS = "xpSqECBW"

_cache: dict[tuple, pygame.Surface] = {}


def sprite(grid: list[str], flip: bool = False) -> pygame.Surface:
    key = ("grid", tuple(grid), flip)
    if key not in _cache:
        surf = pygame.Surface((len(grid[0]), len(grid)), pygame.SRCALPHA)
        for y, row in enumerate(grid):
            for x, ch in enumerate(row):
                if ch != ".":
                    surf.set_at((x, y), PAL[ch])
        _cache[key] = pygame.transform.flip(surf, True, False) if flip else surf
    return _cache[key]


def _rng(*parts) -> random.Random:
    return random.Random(hashlib.md5("|".join(map(str, parts)).encode()).hexdigest())


def _r(x, y, w=1, h=1) -> pygame.Rect:
    return pygame.Rect(x * T, y * T, w * T, h * T)


# --------------------------------------------------------------------------- terrain


def _floor_wood(surf, rect, base, line):
    pygame.draw.rect(surf, base, rect)
    for yy in range(rect.top, rect.bottom, 4):
        pygame.draw.line(surf, line, (rect.left, yy), (rect.right - 1, yy))
    rng = _rng("planks", rect.topleft)
    for yy in range(rect.top, rect.bottom, 4):
        for _ in range(rect.width // 24):
            xx = rng.randrange(rect.left, rect.right)
            pygame.draw.line(surf, line, (xx, yy), (xx, yy + 3))


def _floor_tiles(surf, rect):
    for ty in range(rect.top, rect.bottom, 8):
        for tx in range(rect.left, rect.right, 8):
            color = PAL["c"] if ((tx // 8) + (ty // 8)) % 2 == 0 else (232, 180, 150)
            pygame.draw.rect(surf, color, (tx, ty, 8, 8))


def _grass(surf, rect, season):
    base = {"spring": (140, 190, 96), "summer": (112, 172, 82), "autumn": (176, 170, 90), "winter": (200, 206, 196)}[season]
    pygame.draw.rect(surf, base, rect)
    rng = _rng("grass", rect.topleft)
    tuft = PAL["h"] if season != "winter" else PAL["E"]
    for _ in range(rect.width * rect.height // 90):
        x, y = rng.randrange(rect.left, rect.right), rng.randrange(rect.top, rect.bottom)
        pygame.draw.line(surf, tuft, (x, y), (x, y - 2))
        pygame.draw.line(surf, tuft, (x + 2, y), (x + 3, y - 2))
    if season in ("spring", "summer"):
        for _ in range(rect.width // 40):
            x, y = rng.randrange(rect.left, rect.right), rng.randrange(rect.top, rect.bottom)
            surf.set_at((x, y), PAL[rng.choice("ypx")])


def _sand(surf, rect):
    pygame.draw.rect(surf, PAL["s"], rect)
    rng = _rng("sand", rect.topleft)
    for _ in range(rect.width * rect.height // 40):
        surf.set_at((rng.randrange(rect.left, rect.right), rng.randrange(rect.top, rect.bottom)), PAL["S"])


def _sea(surf, rect, t):
    for i in range(rect.height):
        k = i / rect.height
        color = (int(110 - 40 * k), int(176 - 50 * k), int(214 - 30 * k))
        pygame.draw.line(surf, color, (rect.left, rect.top + i), (rect.right, rect.top + i))
    # foam along the shore and drifting wave highlights
    for x in range(rect.left, rect.right, 2):
        off = int(2 * math.sin(x / 9 + t * 1.5))
        surf.set_at((x, rect.top + 1 + off), PAL["x"])
    rng = _rng("waves")
    for _ in range(26):
        x0, y0 = rng.randrange(rect.left, rect.right), rng.randrange(rect.top + 6, rect.bottom)
        x = int((x0 + t * 6) % rect.width)
        pygame.draw.line(surf, (190, 226, 240), (x, y0), (x + 4, y0))


def _sky(hour, weather):
    if 7 <= hour < 17:
        sky = (150, 200, 236)
    elif 17 <= hour < 19 or 5 <= hour < 7:
        sky = (240, 170, 140)
    else:
        sky = (40, 52, 96)
    if weather in ("阴", "小雨", "雷阵雨", "小雪") and 7 <= hour < 17:
        sky = (170, 180, 190)
    return sky


# --------------------------------------------------------------------------- furniture & things


def _counter(surf, r):
    """Kitchen counter with a sink along the back wall, and a fridge."""
    pygame.draw.rect(surf, PAL["W"], r)
    pygame.draw.rect(surf, PAL["d"], r, 1)
    pygame.draw.line(surf, PAL["E"], (r.left, r.top + 3), (r.right - 1, r.top + 3), 2)
    sink = pygame.Rect(r.left + 10, r.top + 6, 14, 8)
    pygame.draw.rect(surf, PAL["E"], sink)
    pygame.draw.rect(surf, PAL["B"], sink.inflate(-4, -4))
    for i in range(3):
        pygame.draw.rect(surf, PAL["d"], (r.left + 30 + i * 8, r.bottom - 6, 4, 2))


def _fridge(surf, r):
    pygame.draw.rect(surf, PAL["x"], r, border_radius=3)
    pygame.draw.rect(surf, PAL["E"], r, 1, border_radius=3)
    pygame.draw.line(surf, PAL["E"], (r.left + 1, r.top + 10), (r.right - 2, r.top + 10))
    pygame.draw.rect(surf, PAL["e"], (r.right - 5, r.top + 4, 2, 4))
    pygame.draw.rect(surf, PAL["e"], (r.right - 5, r.top + 13, 2, 6))
    pygame.draw.circle(surf, PAL["r"], (r.left + 5, r.top + 15), 2)


def _wardrobe(surf, r):
    pygame.draw.rect(surf, PAL["w"], r)
    pygame.draw.rect(surf, PAL["d"], r, 1)
    pygame.draw.line(surf, PAL["d"], (r.centerx, r.top + 2), (r.centerx, r.bottom - 3))
    for dx in (-3, 2):
        pygame.draw.rect(surf, PAL["y"], (r.centerx + dx, r.centery - 1, 1, 3))


def _tree(surf, r, season):
    pygame.draw.rect(surf, PAL["d"], (r.centerx - 3, r.centery, 6, r.height // 2))
    leaves = {"spring": PAL["G"], "summer": PAL["g"], "autumn": PAL["o"], "winter": PAL["E"]}[season]
    for dx, dy, rr in ((-8, -2, 10), (8, -2, 10), (0, -10, 12), (0, 2, 10)):
        pygame.draw.circle(surf, leaves, (r.centerx + dx, r.centery + dy), rr)
    pygame.draw.circle(surf, PAL["h"] if season != "winter" else PAL["e"], (r.centerx, r.centery - 10), 12, 1)
    if season == "spring":
        rng = _rng("blossom")
        for _ in range(8):
            surf.set_at((r.centerx + rng.randint(-14, 14), r.centery + rng.randint(-18, 6)), PAL["p"])


def _fence(surf, y_px):
    for x in range(0, W, 12):
        if S.FRONT_DOOR_COLS[0] * T - 4 <= x <= (S.FRONT_DOOR_COLS[1] + 1) * T:
            continue
        pygame.draw.rect(surf, PAL["W"], (x + 4, y_px - 9, 3, 9))
    pygame.draw.line(surf, PAL["W"], (0, y_px - 6), (S.FRONT_DOOR_COLS[0] * T - 4, y_px - 6), 2)
    pygame.draw.line(surf, PAL["W"], ((S.FRONT_DOOR_COLS[1] + 1) * T + 4, y_px - 6), (W, y_px - 6), 2)


def _bush(surf, cx, cy, season):
    color = PAL["h"] if season != "winter" else PAL["e"]
    for dx in (-5, 0, 5):
        pygame.draw.circle(surf, color, (cx + dx, cy), 5)
    if season in ("spring", "summer"):
        for dx in (-5, 2, 5):
            surf.set_at((cx + dx, cy - 2), PAL["r"])


def _bed(surf, r):
    pygame.draw.rect(surf, PAL["d"], r)
    pygame.draw.rect(surf, PAL["c"], r.inflate(-4, -4))
    pygame.draw.rect(surf, PAL["x"], (r.left + 4, r.top + 4, r.width - 8, 9))
    pygame.draw.rect(surf, PAL["r"], (r.left + 3, r.top + 16, r.width - 6, r.height - 19))
    pygame.draw.line(surf, PAL["R"], (r.left + 3, r.top + 16), (r.right - 4, r.top + 16))


def _bookshelf(surf, r):
    pygame.draw.rect(surf, PAL["d"], r)
    rng = _rng("books")
    for row in range(2):
        y = r.top + 3 + row * 14
        pygame.draw.rect(surf, PAL["T"], (r.left + 2, y, r.width - 4, 11))
        x = r.left + 3
        while x < r.right - 4:
            bw = rng.choice((2, 3, 3, 4))
            pygame.draw.rect(surf, PAL[rng.choice("rbgyPqo")], (x, y + rng.choice((1, 2, 3)), bw, 10 - 1))
            x += bw + 1


def _sofa(surf, r):
    pygame.draw.rect(surf, PAL["R"], r.inflate(0, -6).move(0, 3), border_radius=3)
    pygame.draw.rect(surf, PAL["r"], (r.left + 4, r.top + 4, r.width - 8, r.height - 10), border_radius=2)
    pygame.draw.line(surf, PAL["R"], (r.centerx, r.top + 6), (r.centerx, r.bottom - 8))
    pygame.draw.rect(surf, PAL["y"], (r.left + 6, r.top + 6, 6, 6), border_radius=1)


def _shelf(surf, r, items):
    pygame.draw.rect(surf, PAL["w"], r)
    for row in range(2):
        y = r.top + 12 + row * 14
        pygame.draw.line(surf, PAL["d"], (r.left + 1, y), (r.right - 2, y), 2)
    n = sum(items.values())
    names = [name for name, c in items.items() for _ in range(c)]
    for i in range(min(n, 14)):
        row, col = divmod(i, 7)
        x = r.left + 3 + col * 6
        y = r.top + 8 + row * 14
        look = FIND_LOOKS.get(names[i], ("pebble", SHELF_DOTS[i % len(SHELF_DOTS)]))[1]
        pygame.draw.rect(surf, PAL[look], (x, y, 4, 3))


def _catalog_table(surf, r):
    pygame.draw.ellipse(surf, PAL["W"], r.inflate(-4, -8))
    pygame.draw.ellipse(surf, PAL["d"], r.inflate(-4, -8), 1)
    pygame.draw.rect(surf, PAL["q"], (r.centerx - 5, r.centery - 4, 10, 7))
    pygame.draw.line(surf, PAL["x"], (r.centerx - 3, r.centery - 2), (r.centerx + 3, r.centery - 2))


def _stove(surf, r, cooking):
    pygame.draw.rect(surf, PAL["e"], r)
    pygame.draw.rect(surf, PAL["k"], r.inflate(-6, -10).move(0, -3))
    for dx in (-6, 6):
        pygame.draw.circle(surf, PAL["o"] if cooking else PAL["e"], (r.centerx + dx, r.centery - 3), 3, 1)
    pygame.draw.rect(surf, PAL["E"], (r.left + 3, r.bottom - 7, r.width - 6, 4))


def _table(surf, r):
    pygame.draw.rect(surf, PAL["W"], r.inflate(-2, -8).move(0, -2), border_radius=2)
    pygame.draw.rect(surf, PAL["d"], r.inflate(-2, -8).move(0, -2), 1, border_radius=2)
    for dx in (-12, 12):
        pygame.draw.rect(surf, PAL["w"], (r.centerx + dx - 3, r.bottom - 7, 6, 5), border_radius=1)


def _pot(surf, r, water, name):
    cx, base = r.centerx, r.bottom - 2
    pygame.draw.polygon(surf, (196, 108, 76), [(cx - 5, base - 6), (cx + 5, base - 6), (cx + 4, base), (cx - 4, base)])
    leaf = PAL["g"] if water >= 60 else (170, 180, 90) if water >= 30 else (170, 140, 80)
    droop = 0 if water >= 30 else 3
    if "多肉" in name:
        for dx, dy in ((-3, -9), (0, -11), (3, -9), (0, -8)):
            pygame.draw.circle(surf, leaf, (cx + dx, base + dy + droop), 2)
    else:
        for i, (dx, dy) in enumerate(((-6, -10), (-3, -13), (2, -14), (5, -10), (0, -9))):
            pygame.draw.ellipse(surf, leaf, (cx + dx - 2, base + dy + (droop if i % 2 else 0), 5, 3))


def _plot(surf, r, state, season):
    wet = state.get("water", 0) >= 40
    pygame.draw.rect(surf, PAL["T"] if wet else PAL["t"], r.inflate(-2, -2), border_radius=2)
    for yy in range(r.top + 4, r.bottom - 2, 5):
        pygame.draw.line(surf, PAL["k"] if wet else PAL["T"], (r.left + 3, yy), (r.right - 4, yy))
    seed = state.get("seed")
    if not seed:
        return
    crop = C.CROPS[seed]
    progress = 1.0 if state.get("ripe") else min(0.99, state.get("growth", 0) / crop.days)
    fruit = PAL[CROP_COLORS.get(crop.name, "r")]
    leaf = PAL["g"] if season in crop.seasons else (160, 150, 90)
    for i in range(3):
        cx = r.left + 8 + i * 16
        cy = r.centery + 3
        if progress < 0.34:
            pygame.draw.line(surf, leaf, (cx, cy), (cx, cy - 3))
            surf.set_at((cx - 1, cy - 4), leaf)
            surf.set_at((cx + 1, cy - 4), leaf)
        else:
            size = 3 if progress < 0.75 else 5
            pygame.draw.ellipse(surf, leaf, (cx - size, cy - size - 2, size * 2, size + 2))
            if state.get("ripe"):
                big = 5 if crop.name == "南瓜" else 3
                pygame.draw.circle(surf, fruit, (cx + 2, cy - 1), big)
                pygame.draw.circle(surf, PAL["x"], (cx + 1, cy - 2), 1)


def _mailbox(surf, r, has_mail):
    pygame.draw.rect(surf, PAL["d"], (r.centerx - 1, r.top + 8, 3, 8))
    pygame.draw.rect(surf, PAL["b"], (r.left + 2, r.top + 2, 12, 8), border_radius=3)
    pygame.draw.rect(surf, PAL["n"], (r.left + 2, r.top + 2, 12, 8), 1, border_radius=3)
    if has_mail:
        pygame.draw.rect(surf, PAL["r"], (r.right - 3, r.top - 2, 2, 6))
        pygame.draw.rect(surf, PAL["r"], (r.right - 3, r.top - 2, 4, 3))


def _consign(surf, r, has_goods):
    pygame.draw.rect(surf, PAL["w"], r.inflate(-2, -2))
    pygame.draw.rect(surf, PAL["d"], r.inflate(-2, -2), 1)
    pygame.draw.line(surf, PAL["q"], (r.left + 2, r.centery), (r.right - 3, r.centery), 2)
    if has_goods:
        pygame.draw.circle(surf, PAL["o"], (r.left + 8, r.top + 3), 2)
        pygame.draw.circle(surf, PAL["b"], (r.left + 14, r.top + 3), 2)


def _parcel(surf, r):
    box = pygame.Rect(r.left + 2, r.top + 4, 12, 10)
    pygame.draw.rect(surf, (210, 170, 120), box)
    pygame.draw.rect(surf, PAL["d"], box, 1)
    pygame.draw.line(surf, PAL["C"], (box.centerx, box.top), (box.centerx, box.bottom - 1), 2)


def _rock(surf, r):
    pygame.draw.ellipse(surf, PAL["e"], r.inflate(-2, -6).move(0, 3))
    pygame.draw.ellipse(surf, PAL["E"], (r.left + 6, r.top + 8, 10, 5))


def _find(surf, tx, ty, item):
    shape, color = FIND_LOOKS.get(item, ("pebble", "E"))
    cx, cy = tx * T + 8, ty * T + 9
    c = PAL[color]
    if shape == "fan":
        pygame.draw.polygon(surf, c, [(cx - 4, cy), (cx, cy - 4), (cx + 4, cy), (cx, cy + 2)])
        for dx in (-2, 0, 2):
            pygame.draw.line(surf, PAL["S"], (cx, cy + 1), (cx + dx, cy - 3))
    elif shape == "conch":
        pygame.draw.ellipse(surf, c, (cx - 3, cy - 3, 7, 5))
        surf.set_at((cx + 3, cy - 3), PAL["R"])
    elif shape == "bottle":
        pygame.draw.rect(surf, c, (cx - 4, cy - 2, 7, 4))
        pygame.draw.rect(surf, PAL["c"], (cx - 2, cy - 1, 3, 2))
        pygame.draw.rect(surf, PAL["d"], (cx + 3, cy - 1, 2, 2))
    elif shape == "wood":
        pygame.draw.line(surf, c, (cx - 5, cy), (cx + 5, cy - 2), 2)
    else:
        pygame.draw.ellipse(surf, c, (cx - 3, cy - 2, 6, 4))


def _decor(surf, tx, ty, name, lit):
    x, y = tx * T, ty * T
    if name == "小地毯":
        rug = pygame.Rect(x - 8, y + 2, 40, 22)
        pygame.draw.ellipse(surf, PAL["P"], rug)
        pygame.draw.ellipse(surf, PAL["p"], rug.inflate(-8, -6))
    elif name == "台灯":
        pygame.draw.rect(surf, PAL["d"], (x + 7, y + 6, 2, 8))
        pygame.draw.polygon(surf, PAL["y"] if lit else PAL["c"], [(x + 3, y + 7), (x + 13, y + 7), (x + 11, y + 1), (x + 5, y + 1)])
        pygame.draw.rect(surf, PAL["d"], (x + 4, y + 13, 8, 2))
    elif name == "挂画":
        pygame.draw.rect(surf, PAL["d"], (x + 1, y + 2, 14, 11))
        pygame.draw.rect(surf, PAL["B"], (x + 3, y + 4, 10, 7))
        pygame.draw.circle(surf, PAL["y"], (x + 10, y + 6), 2)
        pygame.draw.line(surf, PAL["g"], (x + 3, y + 9), (x + 12, y + 8))
    elif name == "风铃":
        pygame.draw.line(surf, PAL["d"], (x + 8, y), (x + 8, y + 4))
        pygame.draw.ellipse(surf, PAL["B"], (x + 4, y + 4, 9, 5))
        for dx in (5, 8, 11):
            pygame.draw.line(surf, PAL["E"], (x + dx, y + 9), (x + dx, y + 13))
    elif name == "小书桌":
        pygame.draw.rect(surf, PAL["W"], (x, y + 4, 26, 8))
        pygame.draw.rect(surf, PAL["d"], (x, y + 4, 26, 8), 1)
        pygame.draw.rect(surf, PAL["x"], (x + 5, y + 5, 7, 5))
    elif name == "懒人沙发":
        pygame.draw.ellipse(surf, PAL["q"], (x, y + 3, 18, 13))
        pygame.draw.ellipse(surf, (120, 196, 186), (x + 4, y + 5, 10, 6))
    elif name == "花瓶":
        pygame.draw.ellipse(surf, PAL["b"], (x + 5, y + 7, 7, 8))
        for dx, col in ((4, "r"), (8, "y"), (12, "p")):
            pygame.draw.line(surf, PAL["g"], (x + 8, y + 8), (x + dx, y + 3))
            pygame.draw.circle(surf, PAL[col], (x + dx, y + 2), 2)


# --------------------------------------------------------------------------- house shell


def _walls(surf, hour, weather):
    pygame.draw.rect(surf, PAL["C"], (0, 0, W, 2 * T))
    pygame.draw.rect(surf, PAL["d"], (0, 2 * T - 3, W, 3))
    pygame.draw.rect(surf, PAL["d"], (0, 0, W, 3))
    sky = _sky(hour, weather)
    for room, wx in S.WINDOWS.items():
        win = pygame.Rect(wx * T + 2, 6, 2 * T - 4, 2 * T - 14)
        pygame.draw.rect(surf, sky, win)
        if sky[2] < 100:  # night: a couple of stars
            rng = _rng("stars", room)
            for _ in range(3):
                surf.set_at((rng.randrange(win.left + 1, win.right - 1), rng.randrange(win.top + 1, win.bottom - 1)), PAL["x"])
        pygame.draw.rect(surf, PAL["W"], win, 2)
        pygame.draw.line(surf, PAL["W"], (win.centerx, win.top), (win.centerx, win.bottom - 1), 2)
        pygame.draw.line(surf, PAL["W"], (win.left, win.centery), (win.right - 1, win.centery), 1)
    # side walls, inner walls with door gaps, front wall with the door
    for x in (0, S.COLS - 1):
        pygame.draw.rect(surf, PAL["d"], _r(x, 0, 1, S.FRONT_WALL_ROW + 1))
    for x in S.INNER_WALL_COLS:
        for y in range(2, S.FRONT_WALL_ROW):
            if y not in S.INNER_DOOR_ROWS:
                pygame.draw.rect(surf, PAL["d"], _r(x, y))
                pygame.draw.line(surf, PAL["w"], (x * T + 3, y * T), (x * T + 3, y * T + T - 1))
    for x in range(S.COLS):
        if x not in S.FRONT_DOOR_COLS:
            pygame.draw.rect(surf, PAL["d"], _r(x, S.FRONT_WALL_ROW))
            pygame.draw.line(surf, PAL["w"], (x * T, S.FRONT_WALL_ROW * T + 4), (x * T + T, S.FRONT_WALL_ROW * T + 4))
    door = _r(S.FRONT_DOOR_COLS[0], S.FRONT_WALL_ROW, 2, 1)
    pygame.draw.rect(surf, PAL["W"], door)
    pygame.draw.rect(surf, PAL["d"], door, 2)


# --------------------------------------------------------------------------- overlays


def _darkness(hour):
    """(outdoor alpha, indoor alpha, lamps on)."""
    if 7 <= hour < 17:
        return 0, 0, False
    if 17 <= hour < 19:
        return 40, 20, True
    if 19 <= hour < 24:
        return 120, 45, True
    if 5 <= hour < 7:
        return 80, 90, False
    return 150, 150, False  # she sleeps with the lights off


def _overlay(surf, rect, color, alpha):
    if alpha <= 0:
        return
    layer = pygame.Surface(rect.size, pygame.SRCALPHA)
    layer.fill((*color, alpha))
    surf.blit(layer, rect.topleft)


def _weather(surf, weather, t):
    outdoor = pygame.Rect(0, S.YARD[1] * T, W, (S.ROWS - S.YARD[1]) * T)
    rng = _rng("rain", int(t * 4))
    if weather in ("小雨", "雷阵雨"):
        n = 160 if weather == "雷阵雨" else 90
        for _ in range(n):
            x, y = rng.randrange(0, W), rng.randrange(outdoor.top, outdoor.bottom)
            pygame.draw.line(surf, (200, 220, 240), (x, y), (x - 2, y + 5))
        _overlay(surf, outdoor, (90, 100, 120), 40)
    elif weather == "小雪":
        for _ in range(110):
            surf.set_at((rng.randrange(0, W), rng.randrange(outdoor.top, outdoor.bottom)), PAL["x"])
    elif weather == "阴":
        _overlay(surf, outdoor, (120, 120, 130), 35)


# --------------------------------------------------------------------------- HUD


def _digits(surf, text, x, y, color, scale=2):
    for ch in text:
        glyph = DIGITS.get(ch)
        if glyph is None:
            x += 2 * scale
            continue
        for gy, row in enumerate(glyph):
            for gx, bit in enumerate(row):
                if bit == "1":
                    pygame.draw.rect(surf, color, (x + gx * scale, y + gy * scale, scale, scale))
        x += (len(glyph[0]) + 1) * scale
    return x


def _weather_icon(surf, weather, x, y):
    if weather == "晴":
        pygame.draw.circle(surf, PAL["y"], (x + 6, y + 6), 5)
        return
    cloud = PAL["E"] if weather != "多云" else PAL["x"]
    if weather == "多云":
        pygame.draw.circle(surf, PAL["y"], (x + 9, y + 4), 4)
    for cx, cy, rr in ((x + 4, y + 7, 4), (x + 8, y + 5, 4), (x + 11, y + 8, 3)):
        pygame.draw.circle(surf, cloud, (cx, cy), rr)
    if weather in ("小雨", "雷阵雨"):
        for dx in (3, 7, 11):
            pygame.draw.line(surf, PAL["B"], (x + dx, y + 11), (x + dx - 1, y + 14))
    if weather == "雷阵雨":
        pygame.draw.lines(surf, PAL["y"], False, [(x + 8, y + 10), (x + 6, y + 13), (x + 9, y + 13), (x + 7, y + 16)])
    if weather == "小雪":
        for dx in (3, 7, 11):
            surf.set_at((x + dx, y + 13), PAL["x"])


def _bar(surf, x, y, value, color):
    pygame.draw.rect(surf, PAL["k"], (x, y, 34, 6))
    pygame.draw.rect(surf, color, (x + 1, y + 1, int(32 * max(0, min(100, value)) / 100), 4))


def _hud(surf, world, now, weather):
    hud = pygame.Rect(0, H, W, S.HUD_H)
    pygame.draw.rect(surf, PAL["d"], hud)
    pygame.draw.line(surf, PAL["w"], (0, H), (W, H), 2)
    y = H + 5
    x = _digits(surf, now.strftime("%m-%d"), 6, y, PAL["c"])
    x = _digits(surf, now.strftime("%H:%M"), x + 8, y, PAL["x"])
    _weather_icon(surf, weather, x + 8, H + 2)
    season_color = {"spring": PAL["p"], "summer": PAL["g"], "autumn": PAL["o"], "winter": PAL["x"]}[season_of(now)]
    pygame.draw.circle(surf, season_color, (x + 32, H + 10), 4)
    # money
    mx = x + 50
    pygame.draw.circle(surf, PAL["y"], (mx + 4, H + 10), 4)
    pygame.draw.circle(surf, PAL["o"], (mx + 4, H + 10), 4, 1)
    _digits(surf, str(world.money), mx + 12, y, PAL["y"])
    # her needs (fullness, energy) and the cat's affection
    bx = W - 150
    _bar(surf, bx, H + 3, 100 - world.resident["hunger"], PAL["o"])
    _bar(surf, bx, H + 11, world.resident["energy"], PAL["B"])
    pygame.draw.circle(surf, PAL["p"], (bx + 52, H + 10), 3)
    _bar(surf, bx + 58, H + 7, world.pet["affection"], PAL["p"])


# --------------------------------------------------------------------------- action effects


def _effect(surf, pose, world, t):
    """Small overlay for what she is doing (frozen mid-way in a still picture)."""
    e = pose.effect
    if not e:
        return
    px, py = int(pose.x * T + 8), int(pose.y * T + T - 28)  # top of her head
    p = pose.effect_p
    wobble = math.sin(t * 6)
    focus_rect = None
    if pose.focus in S.FIXTURES:
        focus_rect = _r(*S.FIXTURES[pose.focus])
    if e == "water":
        target = focus_rect.center if focus_rect else (px + 10 * pose.facing, py + 22)
        for i in range(4):
            k = (p + i * 0.25) % 1.0
            pygame.draw.circle(surf, PAL["B"], (target[0] - 6 + i * 4, int(target[1] - 10 + 12 * k)), 1)
    elif e == "steam":
        r = focus_rect or pygame.Rect(px - 8, py, 16, 16)
        for i in range(3):
            k = (p + i * 0.33) % 1.0
            pygame.draw.circle(surf, PAL["x"], (r.centerx - 5 + i * 5 + int(wobble), int(r.top - 2 - 10 * k)), 2)
    elif e in ("sparkle", "pop"):
        for i in range(4):
            a = t * 3 + i * math.pi / 2
            x, y = px + int(12 * math.cos(a)), py + 14 + int(9 * math.sin(a))
            surf.set_at((x, y), PAL["y"])
            surf.set_at((x + 1, y), PAL["x"])
    elif e == "dirt":
        for i in range(3):
            pygame.draw.circle(surf, PAL["t"], (px - 6 + i * 6, py + 27 - int(4 * p)), 1)
    elif e == "fishing":
        rod_tip = (px + 14 * pose.facing, py + 4)
        pygame.draw.line(surf, PAL["d"], (px + 4 * pose.facing, py + 18), rod_tip, 1)
        bob = (rod_tip[0] + 18 * pose.facing, S.SEA[1] * T + 6 + int(2 * wobble))
        pygame.draw.line(surf, PAL["E"], rod_tip, bob, 1)
        pygame.draw.circle(surf, PAL["r"], bob, 2)
    elif e == "hearts":
        for i in range(2):
            k = (p + i * 0.5) % 1.0
            x, y = px - 4 + i * 9, int(py - 2 - 10 * k)
            pygame.draw.circle(surf, PAL["p"], (x - 1, y), 2)
            pygame.draw.circle(surf, PAL["p"], (x + 2, y), 2)
            pygame.draw.polygon(surf, PAL["p"], [(x - 3, y + 1), (x + 4, y + 1), (x + 1, y + 4)])
    elif e == "eat":
        pygame.draw.ellipse(surf, PAL["x"], (px + 6 * pose.facing - 4, py + 17, 9, 4))
        pygame.draw.circle(surf, PAL["o"], (px + 6 * pose.facing, py + 17), 2)
    elif e == "zzz":
        for i in range(3):
            k = (p + i * 0.33) % 1.0
            x, y = px + 8 + i * 4, int(py - 2 - 12 * k)
            pygame.draw.lines(surf, PAL["x"], False, [(x, y), (x + 3, y), (x, y + 3), (x + 3, y + 3)])
    elif e in ("paper", "coin", "look", "speech"):
        bubble = pygame.Rect(px - 7, py - 13, 14, 10)
        pygame.draw.rect(surf, PAL["x"], bubble, border_radius=3)
        pygame.draw.polygon(surf, PAL["x"], [(px - 2, bubble.bottom - 1), (px + 2, bubble.bottom - 1), (px, bubble.bottom + 2)])
        if e == "coin":
            pygame.draw.circle(surf, PAL["y"], bubble.center, 3)
        elif e == "paper":
            pygame.draw.rect(surf, PAL["C"], (bubble.centerx - 3, bubble.top + 2, 6, 6))
        elif e == "look":
            pygame.draw.circle(surf, PAL["k"], bubble.center, 2, 1)
        else:
            for dx in (-3, 0, 3):
                surf.set_at((bubble.centerx + dx, bubble.centery), PAL["k"])


def _base(season: str) -> pygame.Surface:
    """Terrain and floors: the expensive, rarely-changing layer, cached per season."""
    key = ("base", season)
    if key not in _cache:
        surf = pygame.Surface((W, H))
        _grass(surf, _r(*S.YARD), season)
        pygame.draw.rect(surf, PAL["S"], _r(S.FRONT_DOOR_COLS[0], S.YARD[1], 2, S.YARD[3]))
        _sand(surf, _r(*S.BEACH))
        _floor_wood(surf, _r(*S.ROOM_FLOORS["bedroom"]), (196, 150, 108), (176, 130, 92))
        _floor_wood(surf, _r(*S.ROOM_FLOORS["living_room"]), (214, 172, 120), (190, 148, 100))
        _floor_tiles(surf, _r(*S.ROOM_FLOORS["kitchen"]))
        for y in S.INNER_DOOR_ROWS:
            for x in S.INNER_WALL_COLS:
                pygame.draw.rect(surf, (200, 160, 112), _r(x, y))
        _cache[key] = surf
    return _cache[key]


# --------------------------------------------------------------------------- main entry


def render(world, t: float | None = None, pose: Pose | None = None) -> pygame.Surface:
    """Draw the whole world at 1x.

    ``pose`` places the resident; by default it is what she is doing at this
    very moment (``anim.current_pose``). ``t`` animates waves, rain and effects
    (seconds).
    """
    t = time.time() if t is None else t
    pose = pose or current_pose(world)
    now = world.now()
    hour = now.hour
    weather = world.weather()
    season = season_of(now)
    surf = pygame.Surface((W, H + S.HUD_H))
    surf.blit(_base(season), (0, 0))
    _sea(surf, _r(*S.SEA), t)
    _walls(surf, hour, weather)

    # dirt specks
    for room, rect in S.ROOM_FLOORS.items():
        dirt = world.dirt.get(room, 0)
        if dirt >= 30:
            rng = _rng("dirt", room)
            fr = _r(*rect)
            for _ in range(int(dirt / 4)):
                surf.set_at((rng.randrange(fr.left, fr.right), rng.randrange(fr.top, fr.bottom)), (120, 100, 80))

    _, _, lamps = _darkness(hour)
    recently_cooked = pose.effect == "steam" or any(not j["ready"] for j in getattr(world, "jobs", []))

    # placed furniture (rugs first so they lie under everything)
    decor = [o for o in world.objects.values() if o.kind == "decor"]
    for room in S.DECOR_SLOTS:
        ids = [o.id for o in decor if o.room == room]
        spots = S.decor_spots(room, ids)
        for o in sorted((o for o in decor if o.room == room), key=lambda o: o.name != "小地毯"):
            _decor(surf, *spots[o.id], o.name, lamps)

    objects = world.objects
    _counter(surf, _r(*S.EXTRAS["counter"]))
    _fridge(surf, _r(*S.EXTRAS["fridge"]))
    _wardrobe(surf, _r(*S.EXTRAS["wardrobe"]))
    _tree(surf, _r(*S.EXTRAS["tree"]), season)
    for bx, by in S.BUSHES:
        _bush(surf, bx * T + 8, by * T + 10, season)
    _fence(surf, S.BEACH[1] * T + 2)
    _bed(surf, _r(*S.FIXTURES["bed"]))
    _bookshelf(surf, _r(*S.FIXTURES["bookshelf"]))
    _sofa(surf, _r(*S.FIXTURES["sofa"]))
    _shelf(surf, _r(*S.FIXTURES["shelf"]), world.shelf)
    _catalog_table(surf, _r(*S.FIXTURES["catalog"]))
    _stove(surf, _r(*S.FIXTURES["stove"]), recently_cooked)
    _table(surf, _r(*S.FIXTURES["table"]))
    for pid in ("pot#1", "pot#2"):
        if pid in objects:
            _pot(surf, _r(*S.FIXTURES[pid]), objects[pid].state.get("water", 0), objects[pid].name)
    for pid in ("plot#1", "plot#2", "plot#3"):
        if pid in objects:
            _plot(surf, _r(*S.FIXTURES[pid]), objects[pid].state, season)
    _mailbox(surf, _r(*S.FIXTURES["mailbox"]), bool(world.mailbox))
    _consign(surf, _r(*S.FIXTURES["consign"]), bool(world.sale_box))
    if world.parcels:
        _parcel(surf, _r(*S.FIXTURES["parcel"]))
    _rock(surf, _r(*S.FIXTURES["rock"]))
    finds = {o.id: o for o in objects.values() if o.kind == "find"}
    find_pos = S.find_spots(list(finds))
    for fid, (tx, ty) in find_pos.items():
        _find(surf, tx, ty, finds[fid].state.get("item", finds[fid].name))

    # the cat and the resident
    asleep = pose.asleep  # in bed: asleep at night, or resting
    pet = world.pet
    cx, cy = S.ANCHORS[pet["room"]]
    if pet["room"] == world.location and abs(cx - pose.x) < 1.5 and abs(cy - pose.y) < 1:
        cx += 2
    cat = CAT_ASLEEP if asleep or (pet["affection"] >= 50 and hour % 3 == 0) else CAT
    surf.blit(sprite(cat), (cx * T + 8, cy * T + T - len(cat)))
    if asleep:
        bx, by, _, _ = S.FIXTURES["bed"]
        pygame.draw.circle(surf, PAL["u"], (bx * T + 16, by * T + 9), 6)
        pygame.draw.circle(surf, PAL["f"], (bx * T + 16, by * T + 11), 4)
    else:
        frame = RESIDENT_STEP if pose.walking and pose.step else RESIDENT
        bob = 0 if pose.walking else int(math.sin(t * 2) > 0.6)  # idle breathing
        surf.blit(sprite(frame, flip=pose.facing < 0), (int(pose.x * T) - 2, int(pose.y * T) + T - len(frame) - bob))
        _effect(surf, pose, world, t)

    # light, weather, HUD
    out_a, in_a, _ = _darkness(hour)
    _overlay(surf, pygame.Rect(0, S.YARD[1] * T, W, H - S.YARD[1] * T), (20, 30, 70), out_a)
    _overlay(surf, pygame.Rect(0, 0, W, S.YARD[1] * T), (20, 30, 70), in_a)
    if lamps:
        for room, rect in S.ROOM_FLOORS.items():
            glow = pygame.Surface((90, 70), pygame.SRCALPHA)
            pygame.draw.ellipse(glow, (255, 210, 140, 45), glow.get_rect())
            fr = _r(*rect)
            surf.blit(glow, (fr.centerx - 45, fr.centery - 35))
    _weather(surf, weather, t)
    _hud(surf, world, now, weather)
    return surf


def render_png(world, scale: int = 1) -> bytes:
    """One still frame as PNG (the "glance"): no window, no loop."""
    surf = render(world)
    if scale != 1:
        surf = pygame.transform.scale(surf, (surf.get_width() * scale, surf.get_height() * scale))
    buf = io.BytesIO()
    pygame.image.save(surf, buf, "house.png")
    return buf.getvalue()
