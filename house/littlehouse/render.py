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
from . import sprites as SP  # noqa: E402
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


def big_sprite(grid: list[str], flip: bool = False) -> pygame.Surface:
    """Her and the cat at twice their pixel size, to stand next to the LPC furniture."""
    key = ("big", tuple(grid), flip)
    if key not in _cache:
        small = sprite(grid, flip)
        _cache[key] = pygame.transform.scale(small, (small.get_width() * 2, small.get_height() * 2))
    return _cache[key]


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


def _spr(surf, name, r, dx=0, dy=0, align="bottom") -> bool:
    """Blit an LPC picture centred in rect r (bottom-aligned by default). False if it is missing."""
    img = SP.get(name)
    if img is None:
        return False
    x = r.centerx - img.get_width() // 2 + dx
    y = (r.bottom - img.get_height() if align == "bottom" else r.top) + dy
    surf.blit(img, (x, y))
    return True


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


SEASON_TINT = {"spring": (255, 255, 255), "summer": (225, 240, 215), "autumn": (240, 205, 125), "winter": (215, 222, 228)}


def _tiles(surf, rect, names, seed):
    """Fill rect with 32x32 LPC tiles, picking among variants at random (stable per spot)."""
    imgs = [SP.get(n) for n in names]
    if any(i is None for i in imgs):
        return False
    rng = _rng("tiles", seed)
    for y in range(rect.top, rect.bottom, 32):
        for x in range(rect.left, rect.right, 32):
            img = imgs[0] if rng.random() < 0.6 else rng.choice(imgs[1:])
            surf.blit(img, (x, y), (0, 0, min(32, rect.right - x), min(32, rect.bottom - y)))
    return True


def _grass(surf, rect, season):
    if _tiles(surf, rect, ("grass", "grass2", "grass3", "grass4"), "grass"):
        tint = pygame.Surface(rect.size)
        tint.fill(SEASON_TINT[season])
        surf.blit(tint, rect.topleft, special_flags=pygame.BLEND_MULT)
        if season == "winter":  # a dusting of frost
            rng = _rng("frost")
            for _ in range(rect.width * rect.height // 60):
                surf.set_at((rng.randrange(rect.left, rect.right), rng.randrange(rect.top, rect.bottom)), PAL["x"])
        return
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
    if _tiles(surf, rect, ("sand", "sand2", "sand3", "sand4"), "sand"):
        return
    pygame.draw.rect(surf, PAL["s"], rect)
    rng = _rng("sand", rect.topleft)
    for _ in range(rect.width * rect.height // 40):
        surf.set_at((rng.randrange(rect.left, rect.right), rng.randrange(rect.top, rect.bottom)), PAL["S"])


def _sea_base(rect):
    """Water tiles with the wet shoreline along the top (static: cached)."""
    key = ("sea", tuple(rect))
    if key not in _cache:
        layer = pygame.Surface((rect.width, rect.height + 16), pygame.SRCALPHA)
        shore = SP.get("shore")
        if shore is None or not _tiles(layer, pygame.Rect(0, 16, rect.width, rect.height), ("water", "water2", "water3"), "sea"):
            _cache[key] = None
            return None
        for x in range(0, rect.width, 32):  # sand above, water below: overlaps the beach's last 16 px
            layer.blit(shore, (x, 0))
        _cache[key] = layer
    return _cache[key]


def _sea(surf, rect, t):
    base = _sea_base(rect)
    if base is not None:
        surf.blit(base, (rect.left, rect.top - 16))
        rng = _rng("waves")
        for _ in range(26):  # drifting highlights
            x0, y0 = rng.randrange(rect.left, rect.right), rng.randrange(rect.top + 6, rect.bottom)
            x = int((x0 + t * 6) % rect.width)
            pygame.draw.line(surf, (190, 226, 240), (x, y0), (x + 4, y0))
        for x in range(rect.left, rect.right, 3):  # foam where the waves come in
            off = int(2 * math.sin(x / 9 + t * 1.5))
            surf.set_at((x, rect.top + 2 + off), PAL["x"])
        return
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
    """Kitchen counter with a sink along the back wall."""
    if SP.available():
        for i, (top, front) in enumerate((("sink_top", "sink_front"), ("counter_top", "counter_front"))):
            surf.blit(SP.get(top), (r.left + i * 32, r.top))
            surf.blit(SP.get(front), (r.left + i * 32, r.top + 32))
        return
    pygame.draw.rect(surf, PAL["W"], r)
    pygame.draw.rect(surf, PAL["d"], r, 1)
    pygame.draw.line(surf, PAL["E"], (r.left, r.top + 3), (r.right - 1, r.top + 3), 2)
    sink = pygame.Rect(r.left + 10, r.top + 6, 14, 8)
    pygame.draw.rect(surf, PAL["E"], sink)
    pygame.draw.rect(surf, PAL["B"], sink.inflate(-4, -4))
    for i in range(3):
        pygame.draw.rect(surf, PAL["d"], (r.left + 30 + i * 8, r.bottom - 6, 4, 2))


def _fridge(surf, r):
    """A tall white fridge (drawn here: LPC has none), freezer door on top, a red magnet."""
    body = pygame.Rect(r.left + 2, r.top + 2, r.width - 4, r.height - 4)
    pygame.draw.rect(surf, (178, 178, 176), body.move(0, 2), border_radius=3)  # shadow
    pygame.draw.rect(surf, PAL["x"], body, border_radius=3)
    pygame.draw.rect(surf, (150, 150, 150), body, 1, border_radius=3)
    pygame.draw.rect(surf, (226, 230, 232), (body.left + 2, body.top + 2, body.width - 4, 6))  # top highlight
    split = body.top + body.height // 3
    pygame.draw.line(surf, (150, 150, 150), (body.left + 1, split), (body.right - 2, split))
    pygame.draw.rect(surf, (120, 120, 124), (body.right - 6, body.top + 6, 2, split - body.top - 10))
    pygame.draw.rect(surf, (120, 120, 124), (body.right - 6, split + 4, 2, 14))
    pygame.draw.circle(surf, PAL["r"], (body.left + 7, split + 10), 2)


def _wardrobe(surf, r):
    if _spr(surf, "wardrobe", r):
        return
    pygame.draw.rect(surf, PAL["w"], r)
    pygame.draw.rect(surf, PAL["d"], r, 1)
    pygame.draw.line(surf, PAL["d"], (r.centerx, r.top + 2), (r.centerx, r.bottom - 3))
    for dx in (-3, 2):
        pygame.draw.rect(surf, PAL["y"], (r.centerx + dx, r.centery - 1, 1, 3))


def _tree(surf, r, season):
    """The yard's tree: green in spring and summer (with blossom in spring), orange in autumn, bare in winter."""
    img = SP.get("tree")
    if img is not None and season == "winter":  # bare branches with frost on their tips
        key = ("winter-tree",)
        if key not in _cache:
            _cache[key] = SP.bare(img)
        trunk = _cache[key]
        x, y = r.centerx - trunk.get_width() // 2, r.bottom - trunk.get_height()
        surf.blit(trunk, (x, y))
        top = (x + 32, y + 62)
        for dx, dy in ((-18, -34), (-8, -44), (4, -46), (14, -38), (22, -26), (-22, -20)):
            end = (top[0] + dx, top[1] + dy)
            pygame.draw.line(surf, PAL["T"], top, end, 2)
            pygame.draw.line(surf, PAL["T"], end, (end[0] + dx // 4, end[1] - 6), 1)
            pygame.draw.circle(surf, PAL["x"], end, 2)
        return
    if img is not None:
        if season == "autumn":
            key = ("autumn-tree",)
            if key not in _cache:
                _cache[key] = SP.recolor_leaves(img, SP.AUTUMN_RAMP)
            img = _cache[key]
        x, y = r.centerx - img.get_width() // 2, r.bottom - img.get_height()
        surf.blit(img, (x, y))
        if season == "spring":
            rng = _rng("blossom")
            for _ in range(22):
                bx, by = x + rng.randint(10, 54), y + rng.randint(8, 52)
                pygame.draw.circle(surf, PAL["p"], (bx, by), 2)
                surf.set_at((bx, by), PAL["x"])
        return
    r = pygame.Rect(r.centerx - 24, r.bottom - 48, 48, 48)
    trunk_x = r.centerx - 3
    pygame.draw.rect(surf, PAL["T"], (trunk_x, r.centery, 6, r.height // 2))
    pygame.draw.line(surf, PAL["d"], (trunk_x + 4, r.centery + 2), (trunk_x + 4, r.bottom - 2))
    mid, dark, light = {
        "spring": (PAL["G"], PAL["g"], (196, 226, 150)),
        "summer": (PAL["g"], PAL["h"], PAL["G"]),
        "autumn": (PAL["o"], (196, 108, 52), PAL["y"]),
        "winter": (PAL["E"], PAL["e"], PAL["x"]),
    }[season]
    blobs = ((-8, -2, 10), (8, -2, 10), (0, -10, 12), (0, 2, 10))
    for dx, dy, rr in blobs:  # shadow layer, a little lower
        pygame.draw.circle(surf, dark, (r.centerx + dx, r.centery + dy + 2), rr)
    for dx, dy, rr in blobs:
        pygame.draw.circle(surf, mid, (r.centerx + dx, r.centery + dy), rr - 1)
    for dx, dy in ((-6, -12), (4, -15), (-10, -4)):  # sunlit leaves
        pygame.draw.circle(surf, light, (r.centerx + dx, r.centery + dy), 3)
    if season == "winter":  # bare branches showing through
        for dx in (-7, 0, 7):
            pygame.draw.line(surf, PAL["d"], (r.centerx, r.centery + 2), (r.centerx + dx, r.centery - 10), 1)
    if season == "spring":
        rng = _rng("blossom")
        for _ in range(10):
            surf.set_at((r.centerx + rng.randint(-14, 14), r.centery + rng.randint(-18, 6)), PAL["p"])


def _fence(surf, y_px):
    for x in range(0, W, 12):
        if S.FRONT_DOOR_COLS[0] * T - 4 <= x <= (S.FRONT_DOOR_COLS[1] + 1) * T:
            continue
        pygame.draw.rect(surf, PAL["W"], (x + 4, y_px - 9, 3, 9))
    pygame.draw.line(surf, PAL["W"], (0, y_px - 6), (S.FRONT_DOOR_COLS[0] * T - 4, y_px - 6), 2)
    pygame.draw.line(surf, PAL["W"], ((S.FRONT_DOOR_COLS[1] + 1) * T + 4, y_px - 6), (W, y_px - 6), 2)


def _bush(surf, cx, cy, season):
    img = SP.get("bush")
    if img is not None:
        if season in ("autumn", "winter"):
            img = img.copy()
            img.fill(SEASON_TINT[season], special_flags=pygame.BLEND_MULT)
        surf.blit(img, (cx - 16, cy - 22))
        return
    color = PAL["h"] if season != "winter" else PAL["e"]
    for dx in (-5, 0, 5):
        pygame.draw.circle(surf, color, (cx + dx, cy), 5)
    if season in ("spring", "summer"):
        for dx in (-5, 2, 5):
            surf.set_at((cx + dx, cy - 2), PAL["r"])


def _bed(surf, r):
    quilt, pillow = SP.get("bed_quilt"), SP.get("bed_pillow")
    if quilt is not None and pillow is not None:
        x = r.centerx - quilt.get_width() // 2
        surf.blit(quilt, (x, r.top + 6))
        surf.blit(pillow, (r.centerx - pillow.get_width() // 2, r.top + 2))
        return
    pygame.draw.rect(surf, PAL["d"], r)
    pygame.draw.rect(surf, PAL["c"], r.inflate(-4, -4))
    pygame.draw.rect(surf, PAL["x"], (r.left + 4, r.top + 4, r.width - 8, 9))
    pygame.draw.rect(surf, PAL["r"], (r.left + 3, r.top + 16, r.width - 6, r.height - 19))
    pygame.draw.line(surf, PAL["R"], (r.left + 3, r.top + 16), (r.right - 4, r.top + 16))


def _bookshelf(surf, r):
    shelf = SP.get("bookshelf")
    if shelf is not None:
        for x in range(r.left, r.right - 1, 32):
            surf.blit(shelf, (x, r.top))
        return
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
    if _spr(surf, "sofa", r):
        return
    pygame.draw.rect(surf, PAL["R"], r.inflate(0, -6).move(0, 3), border_radius=3)
    pygame.draw.rect(surf, PAL["r"], (r.left + 4, r.top + 4, r.width - 8, r.height - 10), border_radius=2)
    pygame.draw.line(surf, PAL["R"], (r.centerx, r.top + 6), (r.centerx, r.bottom - 8))
    pygame.draw.rect(surf, PAL["y"], (r.left + 6, r.top + 6, 6, 6), border_radius=1)


def _shelf(surf, r, items):
    shelf = SP.get("open_shelf")
    if shelf is not None:  # two open shelves side by side, the collection on their boards
        for x in (r.left, r.left + 32):
            surf.blit(shelf, (x, r.top))
        names = [name for name, c in items.items() for _ in range(c)]
        for i, name in enumerate(names[:16]):
            row, col = divmod(i, 8)
            look = FIND_LOOKS.get(name, ("pebble", SHELF_DOTS[i % len(SHELF_DOTS)]))[1]
            x, y = r.left + 4 + col * 7, r.top + 22 + row * 12
            pygame.draw.rect(surf, PAL[look], (x, y, 5, 4))
            pygame.draw.rect(surf, PAL["k"], (x, y, 5, 4), 1)
        return
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


def _booklet(surf, x, y):
    pygame.draw.rect(surf, PAL["q"], (x, y, 12, 8))
    pygame.draw.rect(surf, PAL["n"], (x, y, 12, 8), 1)
    pygame.draw.line(surf, PAL["x"], (x + 3, y + 3), (x + 9, y + 3))


def _catalog_table(surf, r, on_table=True):
    if SP.get("round_table") is not None and not on_table:
        _spr(surf, "round_table", r)
        return
    if _spr(surf, "round_table", r):  # with the bureau's catalog (a teal booklet) on top
        pygame.draw.rect(surf, PAL["q"], (r.centerx - 6, r.top + 6, 12, 8))
        pygame.draw.rect(surf, PAL["n"], (r.centerx - 6, r.top + 6, 12, 8), 1)
        pygame.draw.line(surf, PAL["x"], (r.centerx - 3, r.top + 9), (r.centerx + 3, r.top + 9))
        return
    pygame.draw.ellipse(surf, PAL["W"], r.inflate(-4, -8))
    pygame.draw.ellipse(surf, PAL["d"], r.inflate(-4, -8), 1)
    pygame.draw.rect(surf, PAL["q"], (r.centerx - 5, r.centery - 4, 10, 7))
    pygame.draw.line(surf, PAL["x"], (r.centerx - 3, r.centery - 2), (r.centerx + 3, r.centery - 2))


def _stove(surf, r, cooking):
    top, front = SP.get("stove_top"), SP.get("stove_front")
    if top is not None and front is not None:
        surf.blit(top, (r.left, r.top))
        surf.blit(front, (r.left, r.top + 32))
        if cooking:  # the rings glow under a pot
            for dx in (-7, 7):
                pygame.draw.circle(surf, PAL["o"], (r.centerx + dx, r.top + 16), 3, 1)
        return
    pygame.draw.rect(surf, PAL["e"], r)
    pygame.draw.rect(surf, PAL["k"], r.inflate(-6, -10).move(0, -3))
    for dx in (-6, 6):
        pygame.draw.circle(surf, PAL["o"] if cooking else PAL["e"], (r.centerx + dx, r.centery - 3), 3, 1)
    pygame.draw.rect(surf, PAL["E"], (r.left + 3, r.bottom - 7, r.width - 6, 4))


def _table(surf, r):
    if _spr(surf, "kitchen_table", r):
        return
    pygame.draw.rect(surf, PAL["W"], r.inflate(-2, -8).move(0, -2), border_radius=2)
    pygame.draw.rect(surf, PAL["d"], r.inflate(-2, -8).move(0, -2), 1, border_radius=2)
    for dx in (-12, 12):
        pygame.draw.rect(surf, PAL["w"], (r.centerx + dx - 3, r.bottom - 7, 6, 5), border_radius=1)


def _pot(surf, r, water, name, fallen=False):
    img = SP.get("succulent" if "多肉" in name else "pothos")
    if img is not None:
        if water < 60:  # thirsty leaves fade towards yellow-brown
            img = img.copy()
            img.fill((235, 215, 150) if water >= 30 else (210, 170, 110), special_flags=pygame.BLEND_MULT)
        if fallen:  # knocked over: lying on its side, leaves on the floor
            img = pygame.transform.rotate(img, 90)
            surf.blit(img, (r.centerx - img.get_width() // 2 - 6, r.bottom - img.get_height()))
            return
        surf.blit(img, (r.centerx - img.get_width() // 2, r.bottom - img.get_height()))
        return
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
    soil = SP.get("soil")
    seed = state.get("seed")
    if soil is not None:
        wet = state.get("water", 0) >= 40
        for x in range(r.left, r.right - 1, 32):
            surf.blit(soil, (x, r.top))
        if not wet:  # dry soil is paler
            pale = pygame.Surface(r.size, pygame.SRCALPHA)
            pale.fill((240, 220, 180, 70))
            surf.blit(pale, r.topleft)
        if seed:
            crop = C.CROPS[seed]
            progress = 1.0 if state.get("ripe") else min(0.99, state.get("growth", 0) / crop.days)
            stage = 4 if state.get("ripe") else min(3, int(progress * 4))
            img = SP.crop(crop.name, stage)
            if img is not None:
                if season not in crop.seasons:
                    img = img.copy()
                    img.fill((220, 200, 140), special_flags=pygame.BLEND_MULT)
                for x in range(r.left, r.right - 1, 32):
                    surf.blit(img, (x, r.bottom - 64 + 4))
                return
            # no LPC picture for this crop: drawn here at the same scale
            out_of_season = season not in crop.seasons
            for x in range(r.left + 16, r.right - 1, 32):
                _crop_drawn(surf, crop.name, x, r.bottom - 6, stage, out_of_season)
        return
    wet = state.get("water", 0) >= 40
    pygame.draw.rect(surf, PAL["T"] if wet else PAL["t"], r.inflate(-2, -2), border_radius=2)
    for yy in range(r.top + 4, r.bottom - 2, 5):
        pygame.draw.line(surf, PAL["k"] if wet else PAL["T"], (r.left + 3, yy), (r.right - 4, yy))
    if seed:
        _plot_crops(surf, r, state, season)


def _crop_drawn(surf, name, cx, base, stage, wilted=False):
    """菠菜 / 葱 / 南瓜 / 草莓 at the LPC scale: stage 0-3 growing, 4 ripe."""
    k = (stage + 1) / 5  # size
    leaf, dark, light = ((96, 150, 60), (52, 96, 40), (150, 196, 96)) if not wilted else ((150, 150, 90), (110, 100, 60), (190, 180, 120))
    if stage == 0:  # every crop starts as a pair of seed leaves
        pygame.draw.line(surf, dark, (cx, base), (cx, base - 4))
        pygame.draw.ellipse(surf, leaf, (cx - 5, base - 7, 5, 3))
        pygame.draw.ellipse(surf, leaf, (cx + 1, base - 7, 5, 3))
        return
    if name == "菠菜":  # a rosette of broad, veined leaves
        for ang in range(0, 360, 60):
            import math as _m
            ex = cx + int(_m.cos(_m.radians(ang)) * 10 * k)
            ey = base - 6 - int(_m.sin(_m.radians(ang)) * 6 * k)
            pygame.draw.ellipse(surf, dark, (ex - 5 * k - 1, ey - 3 * k - 1, 10 * k + 2, 6 * k + 2))
            pygame.draw.ellipse(surf, leaf, (ex - 5 * k, ey - 3 * k, 10 * k, 6 * k))
            pygame.draw.line(surf, light, (cx, base - 6), (ex, ey))
    elif name == "葱":  # tufts of tall, thin hollow leaves
        h = int(8 + 20 * k)
        for dx in (-5, -2, 1, 4):
            top = (cx + dx + (1 if dx > 0 else -1) * int(3 * k), base - h + abs(dx))
            pygame.draw.line(surf, dark, (cx + dx, base), top, 2)
            pygame.draw.line(surf, light, (cx + dx, base - 2), (top[0], top[1] + 2), 1)
        pygame.draw.rect(surf, (236, 236, 220), (cx - 6, base - 3, 12, 3))  # white stalks
    elif name == "南瓜":  # big leaves on a vine, an orange ribbed pumpkin when ripe
        for dx, dy in ((-10, -6), (8, -8), (0, -12)):
            sz = int(6 + 6 * k)
            pygame.draw.circle(surf, dark, (cx + int(dx * k), base + int(dy * k)), sz)
            pygame.draw.circle(surf, leaf, (cx + int(dx * k) - 1, base + int(dy * k) - 1), sz - 2)
        if stage >= 3:
            size = 7 if stage == 3 else 11
            body = pygame.Rect(cx - size, base - size - 2, size * 2, size + 4)
            color = (236, 150, 48) if stage == 4 else (168, 186, 70)
            pygame.draw.ellipse(surf, (150, 80, 26) if stage == 4 else (110, 130, 40), body.inflate(2, 2))
            pygame.draw.ellipse(surf, color, body)
            for dx in (-size // 2, 0, size // 2):
                pygame.draw.line(surf, (196, 112, 34) if stage == 4 else (130, 150, 50), (cx + dx, body.top + 2), (cx + dx, body.bottom - 2))
            pygame.draw.rect(surf, (96, 70, 40), (cx - 1, body.top - 3, 3, 4))
    else:  # 草莓: low leafy plant with white flowers, then red berries
        for dx, dy in ((-7, -5), (6, -5), (0, -9), (-2, -3)):
            sz = int(3 + 4 * k)
            pygame.draw.circle(surf, dark, (cx + dx, base + dy), sz)
            pygame.draw.circle(surf, leaf, (cx + dx - 1, base + dy - 1), max(1, sz - 1))
        if stage == 3:
            for dx in (-6, 5):
                pygame.draw.circle(surf, PAL["x"], (cx + dx, base - 10), 2)
        if stage == 4:
            for dx, dy in ((-8, -2), (7, -3), (1, -1)):
                pygame.draw.polygon(surf, (210, 50, 54), [(cx + dx - 3, base + dy - 3), (cx + dx + 3, base + dy - 3), (cx + dx, base + dy + 3)])
                surf.set_at((cx + dx, base + dy - 1), (250, 220, 120))


def _plot_crops(surf, r, state, season):
    """Crops without an LPC picture (菠菜, 葱, 南瓜, 草莓): small drawn plants."""
    crop = C.CROPS[state["seed"]]
    progress = 1.0 if state.get("ripe") else min(0.99, state.get("growth", 0) / crop.days)
    fruit = PAL[CROP_COLORS.get(crop.name, "r")]
    leaf = PAL["g"] if season in crop.seasons else (160, 150, 90)
    for i in range(max(1, r.width // 16)):
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
    if SP.available():  # drawn at the LPC scale: a blue box on a wooden post
        cx, base = r.centerx, r.bottom + 4
        pygame.draw.rect(surf, PAL["T"], (cx - 2, base - 14, 4, 14))
        pygame.draw.rect(surf, PAL["d"], (cx - 2, base - 14, 4, 14), 1)
        box = pygame.Rect(cx - 9, base - 26, 18, 12)
        pygame.draw.rect(surf, PAL["b"], box, border_radius=4)
        pygame.draw.rect(surf, PAL["n"], box, 1, border_radius=4)
        pygame.draw.line(surf, PAL["B"], (box.left + 3, box.top + 3), (box.right - 4, box.top + 3))
        if has_mail:
            pygame.draw.rect(surf, PAL["r"], (box.right, box.top - 6, 2, 9))
            pygame.draw.rect(surf, PAL["r"], (box.right, box.top - 6, 5, 4))
        return
    pygame.draw.rect(surf, PAL["d"], (r.centerx - 1, r.top + 8, 3, 8))
    pygame.draw.rect(surf, PAL["b"], (r.left + 2, r.top + 2, 12, 8), border_radius=3)
    pygame.draw.rect(surf, PAL["n"], (r.left + 2, r.top + 2, 12, 8), 1, border_radius=3)
    if has_mail:
        pygame.draw.rect(surf, PAL["r"], (r.right - 3, r.top - 2, 2, 6))
        pygame.draw.rect(surf, PAL["r"], (r.right - 3, r.top - 2, 4, 3))


def _consign(surf, r, has_goods):
    img = SP.get("chest")
    if img is not None:  # a wooden chest with the bureau's teal stripe
        x, y = r.centerx - img.get_width() // 2, r.bottom - img.get_height() + 4
        surf.blit(img, (x, y))
        pygame.draw.line(surf, PAL["q"], (x + 3, y + 17), (x + img.get_width() - 4, y + 17), 2)
        if has_goods:
            pygame.draw.circle(surf, PAL["o"], (x + 9, y + 2), 2)
            pygame.draw.circle(surf, PAL["b"], (x + 15, y + 1), 2)
        return
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
    if _spr(surf, "rock", r):
        return
    r = pygame.Rect(r.centerx - 16, r.bottom - 32, 32, 32)
    """A big grey reef rock with a flat top (where she sits to fish) and wet foam at its foot."""
    base = [(r.left + 1, r.bottom - 4), (r.left + 3, r.top + 9), (r.left + 9, r.top + 4),
            (r.right - 8, r.top + 3), (r.right - 2, r.top + 10), (r.right - 1, r.bottom - 4)]
    pygame.draw.ellipse(surf, (196, 176, 130), (r.left - 2, r.bottom - 7, r.width + 4, 7))  # wet sand
    pygame.draw.polygon(surf, (110, 108, 106), base)
    pygame.draw.polygon(surf, PAL["e"], [(r.left + 4, r.top + 10), (r.left + 9, r.top + 5), (r.right - 8, r.top + 4),
                                         (r.right - 4, r.top + 10), (r.centerx, r.top + 13)])
    pygame.draw.line(surf, PAL["E"], (r.left + 9, r.top + 6), (r.right - 9, r.top + 5))  # flat sunlit top
    pygame.draw.line(surf, (86, 84, 84), (r.centerx - 2, r.top + 14), (r.centerx + 3, r.bottom - 6))  # crack
    for dx in (2, 9, 17, 25):  # foam
        surf.set_at((r.left + dx, r.bottom - 3), PAL["x"])


def _find(surf, tx, ty, item):
    shape, color = FIND_LOOKS.get(item, ("pebble", "E"))
    cx, cy = tx * T + 8, ty * T + 9
    c = PAL[color]
    if shape == "fan":  # a scallop: fan with ridges, outlined so it reads on white sand
        fan = [(cx - 6, cy - 1), (cx - 3, cy - 5), (cx + 3, cy - 5), (cx + 6, cy - 1), (cx + 1, cy + 3), (cx - 1, cy + 3)]
        pygame.draw.polygon(surf, c, fan)
        pygame.draw.polygon(surf, PAL["t"], fan, 1)
        for dx in (-4, -2, 0, 2, 4):
            pygame.draw.line(surf, PAL["S"], (cx, cy + 2), (cx + dx, cy - 4))
        pygame.draw.rect(surf, c, (cx - 2, cy + 2, 4, 2))
    elif shape == "conch":
        pygame.draw.ellipse(surf, c, (cx - 5, cy - 3, 10, 7))
        pygame.draw.ellipse(surf, PAL["R"], (cx - 5, cy - 3, 10, 7), 1)
        pygame.draw.line(surf, PAL["R"], (cx - 2, cy), (cx + 3, cy - 2))
    elif shape == "bottle":
        pygame.draw.rect(surf, c, (cx - 4, cy - 2, 7, 4))
        pygame.draw.rect(surf, PAL["c"], (cx - 2, cy - 1, 3, 2))
        pygame.draw.rect(surf, PAL["d"], (cx + 3, cy - 1, 2, 2))
    elif shape == "wood":
        pygame.draw.line(surf, c, (cx - 5, cy), (cx + 5, cy - 2), 2)
    else:
        pygame.draw.ellipse(surf, c, (cx - 3, cy - 2, 6, 4))


def _decor(surf, tx, ty, name, lit, fallen=False):
    x, y = tx * T, ty * T
    img = SP.get(name) if name in SP.SPRITES else None
    if img is not None and fallen:
        img = pygame.transform.rotate(img, -90)
        surf.blit(img, (x + 8 - img.get_width() // 2, y + T - img.get_height()))
        return
    if img is not None:
        if name == "挂画":  # hangs on the back wall above its spot
            surf.blit(img, (x + 8 - img.get_width() // 2, 4))
            return
        surf.blit(img, (x + 8 - img.get_width() // 2, y + T - img.get_height()))
        if name == "台灯" and lit:
            glow = pygame.Surface((40, 30), pygame.SRCALPHA)
            pygame.draw.ellipse(glow, (255, 220, 140, 70), glow.get_rect())
            surf.blit(glow, (x - 12, y - 14))
        return
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
    px, py = int(pose.x * T + 8), int(pose.y * T + T - 52)  # just above her head
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


def _messes(surf, world):
    """What the cat left behind: spilled soil and water, a book, the catalog, a cushion, a trampled quilt."""
    for o in world.objects.values():
        if o.kind != "mess":
            continue
        kind = o.state.get("kind")
        spot = o.state.get("spot")
        rect = None
        if spot in S.FIXTURES:
            rect = _r(*S.FIXTURES[spot])
        elif spot and spot in world.objects and world.objects[spot].kind == "decor":
            ids = [d.id for d in world.objects.values() if d.kind == "decor" and d.room == o.room]
            tx, ty = S.decor_spots(o.room, ids).get(spot, S.ANCHORS[o.room])
            rect = _r(tx, ty)
        if rect is None:
            ax, ay = S.ANCHORS[o.room]
            rect = _r(ax, ay)
        rng = _rng("mess", o.id)
        if kind == "soil":
            for _ in range(14):
                x = rect.centerx + rng.randint(-14, 16)
                y = rect.bottom + rng.randint(-4, 6)
                pygame.draw.circle(surf, (110, 74, 48) if rng.random() < 0.7 else (140, 98, 64), (x, y), rng.randint(1, 3))
        elif kind == "water":
            pygame.draw.ellipse(surf, (150, 200, 230), (rect.centerx - 4, rect.bottom - 6, 26, 9))
            pygame.draw.ellipse(surf, (200, 232, 248), (rect.centerx, rect.bottom - 5, 10, 3))
        elif kind == "book":
            x, y = rect.centerx + 6, rect.bottom + 10
            pygame.draw.rect(surf, PAL["R"], (x, y, 12, 9))
            pygame.draw.rect(surf, PAL["x"], (x + 2, y + 1, 8, 7))
            pygame.draw.line(surf, PAL["R"], (x + 6, y + 1), (x + 6, y + 7))
        elif kind == "catalog":
            _booklet(surf, rect.centerx + 10, rect.bottom + 6)
        elif kind == "cushion":
            x, y = rect.centerx + 22, rect.bottom + 6
            pygame.draw.rect(surf, PAL["y"], (x, y, 10, 9), border_radius=3)
            pygame.draw.rect(surf, PAL["o"], (x, y, 10, 9), 1, border_radius=3)
        elif kind == "quilt":
            for i in range(5):
                x = rect.left + 12 + rng.randint(0, rect.width - 24)
                y = rect.top + 26 + rng.randint(0, 30)
                pygame.draw.line(surf, (120, 40, 34), (x, y), (x + rng.randint(4, 9), y + rng.randint(-3, 3)), 1)
            for _ in range(4):  # orange cat hairs
                surf.set_at((rect.left + 14 + rng.randint(0, 20), rect.top + 30 + rng.randint(0, 20)), PAL["o"])


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
            _decor(surf, *spots[o.id], o.name, lamps, o.state.get("fallen", False))

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
    mess_kinds = {o.state.get("kind") for o in world.objects.values() if o.kind == "mess"}
    _catalog_table(surf, _r(*S.FIXTURES["catalog"]), on_table="catalog" not in mess_kinds)
    _stove(surf, _r(*S.FIXTURES["stove"]), recently_cooked)
    _table(surf, _r(*S.FIXTURES["table"]))
    for pid in ("pot#1", "pot#2"):
        if pid in objects:
            _pot(surf, _r(*S.FIXTURES[pid]), objects[pid].state.get("water", 0), objects[pid].name,
                 objects[pid].state.get("fallen", False))
    for pid in ("plot#1", "plot#2", "plot#3"):
        if pid in objects:
            _plot(surf, _r(*S.FIXTURES[pid]), objects[pid].state, season)
    _mailbox(surf, _r(*S.FIXTURES["mailbox"]), bool(world.mailbox))
    _consign(surf, _r(*S.FIXTURES["consign"]), bool(world.sale_box))
    if world.parcels:
        _parcel(surf, _r(*S.FIXTURES["parcel"]))
    _rock(surf, _r(*S.FIXTURES["rock"]))
    _messes(surf, world)
    finds = {o.id: o for o in objects.values() if o.kind == "find"}
    find_pos = S.find_spots(list(finds))
    for fid, (tx, ty) in find_pos.items():
        _find(surf, tx, ty, finds[fid].state.get("item", finds[fid].name))

    # the cat and the resident
    asleep = pose.asleep  # in bed: asleep at night, or resting
    pet = world.pet
    cx, cy = S.ANCHORS[pet["room"]]
    if pet["room"] == world.location and abs(cx - pose.x) < 1.5 and abs(cy - pose.y) < 1:
        cx += 3
    cat_sleeps = asleep or (pet["affection"] >= 50 and hour % 3 == 0)
    cat_img = SP.cat("sleep" if cat_sleeps else "sit")
    if cat_img is not None:
        surf.blit(cat_img, (cx * T, cy * T + T - 30))
    else:
        cat_img = big_sprite(CAT_ASLEEP if cat_sleeps else CAT)
        surf.blit(cat_img, (cx * T + 8, cy * T + T - cat_img.get_height()))
    if asleep:  # her blue hair on the pillow, the quilt pulled up
        bx, by, bw, _ = S.FIXTURES["bed"]
        hx = bx * T + bw * T // 2
        pygame.draw.circle(surf, PAL["u"], (hx, by * T + 12), 8)
        pygame.draw.circle(surf, PAL["f"], (hx, by * T + 15), 5)
    else:
        lpc = (SP.resident(("right" if pose.facing > 0 else "left"), 1 + pose.step % 8) if pose.walking
               else SP.resident("down", 0))
        if lpc is not None:  # 64x64 frame, her feet about 2 px above its bottom
            bob = 0 if pose.walking else int(math.sin(t * 2) > 0.6)
            surf.blit(lpc, (int(pose.x * T) + 8 - 32, int(pose.y * T) + T - 62 - bob))
        else:
            frame = RESIDENT_STEP if pose.walking and pose.step % 2 else RESIDENT
            bob = 0 if pose.walking else 2 * int(math.sin(t * 2) > 0.6)  # idle breathing
            img = big_sprite(frame, flip=pose.facing < 0)
            surf.blit(img, (int(pose.x * T) + 8 - img.get_width() // 2, int(pose.y * T) + T - img.get_height() - bob))
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
