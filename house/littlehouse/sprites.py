"""Pictures cut from the LPC sprite sheets in ``assets/lpc`` (see CREDITS.md there).

``get(name)`` returns a pygame Surface, or None when the sheets are missing (the
renderer then falls back to drawing the thing itself). Sheets are loaded once.
"""

from __future__ import annotations

from pathlib import Path

import pygame

ASSETS = Path(__file__).parent / "assets" / "lpc"

Rect = tuple[int, int, int, int]

SPRITES: dict[str, tuple[str, Rect]] = {
    # bedroom
    "bed_quilt": ("beds_single_a.png", (73, 18, 46, 55)),
    "bed_pillow": ("beds_single_a.png", (10, 23, 44, 14)),
    "bookshelf": ("house_interior.png", (32, 224, 32, 32)),
    "wardrobe": ("cabinets.png", (2, 208, 28, 56)),
    "succulent": ("flowers.png", (133, 69, 22, 25)),
    # living room
    "sofa": ("sofas_casual.png", (69, 0, 53, 32)),
    "open_shelf": ("cabinets.png", (160, 64, 32, 48)),
    "round_table": ("tables.png", (0, 64, 32, 30)),
    "pothos": ("planters.png", (128, 32, 32, 64)),
    # kitchen
    "stove_top": ("house_interior.png", (128, 96, 32, 32)),
    "stove_front": ("house_interior.png", (128, 128, 32, 32)),
    "sink_top": ("house_interior.png", (64, 96, 32, 32)),
    "sink_front": ("house_interior.png", (64, 128, 32, 32)),
    "counter_top": ("house_interior.png", (96, 96, 32, 32)),
    "counter_front": ("house_interior.png", (96, 128, 32, 32)),
    "kitchen_table": ("tables.png", (104, 118, 80, 42)),
    # furniture she can buy
    "台灯": ("lighting.png", (6, 100, 20, 26)),
    "花瓶": ("planters.png", (128, 0, 32, 32)),
    "挂画": ("paintings.png", (224, 131, 31, 27)),
    "落地钟": ("decorative_furniture.png", (7, 86, 18, 71)),
    "扶手椅": ("chairs_sofa.png", (64, 128, 32, 32)),
    "盆栽": ("planters.png", (64, 0, 32, 96)),
    # garden
    "soil": ("farming_plowed_soil.png", (32, 96, 32, 32)),
    # outdoors (LPC Tile Atlas, 32x32 cells)
    "grass": ("terrain_atlas.png", (704, 96, 32, 32)),
    "grass2": ("terrain_atlas.png", (672, 160, 32, 32)),
    "grass3": ("terrain_atlas.png", (704, 160, 32, 32)),
    "grass4": ("terrain_atlas.png", (736, 160, 32, 32)),
    "sand": ("terrain_atlas.png", (32, 384, 32, 32)),
    "sand2": ("terrain_atlas.png", (0, 448, 32, 32)),
    "sand3": ("terrain_atlas.png", (32, 448, 32, 32)),
    "sand4": ("terrain_atlas.png", (64, 448, 32, 32)),
    "water": ("terrain_atlas.png", (224, 384, 32, 32)),
    "water2": ("terrain_atlas.png", (96, 448, 32, 32)),
    "water3": ("terrain_atlas.png", (160, 448, 32, 32)),
    "shore": ("terrain_atlas.png", (128, 416, 32, 32)),
    "tree": ("terrain_atlas.png", (864, 928, 64, 96)),
    "bush": ("terrain_atlas.png", (672, 32, 32, 32)),
    "rock": ("terrain_atlas.png", (864, 832, 64, 64)),
    "chest": ("chests.png", (66, 0, 28, 27)),
}

# Crops drawn from farming_plants.png: column per crop, 32x64 cells; rows 0-3 growing, 4 ripe.
CROP_COLUMNS = {"番茄": 0, "土豆": 1, "萝卜": 2, "白菜": 3, "生菜": 3, "黄瓜": 5}

_sheets: dict[str, pygame.Surface | None] = {}
_cache: dict[object, pygame.Surface | None] = {}


def _sheet(name: str) -> pygame.Surface | None:
    if name not in _sheets:
        try:
            _sheets[name] = pygame.image.load(str(ASSETS / name))
        except (FileNotFoundError, pygame.error):
            _sheets[name] = None
    return _sheets[name]


def get(name: str) -> pygame.Surface | None:
    if name not in _cache:
        sheet_name, rect = SPRITES[name]
        sheet = _sheet(sheet_name)
        _cache[name] = sheet.subsurface(rect).copy() if sheet else None
    return _cache[name]


def crop(name: str, stage: int) -> pygame.Surface | None:
    """A crop at growth stage 0-4 (4 = ripe), or None if there is no LPC picture for it."""
    col = CROP_COLUMNS.get(name)
    if col is None:
        return None
    key = ("crop", col, stage)
    if key not in _cache:
        sheet = _sheet("farming_plants.png")
        _cache[key] = sheet.subsurface((col * 32, max(0, min(4, stage)) * 64, 32, 64)).copy() if sheet else None
    return _cache[key]


def available() -> bool:
    return get("sofa") is not None


# --------------------------------------------------------------------------- the resident (LPC layers + whale bits)
#
# 小栖 is put together at run time from LPC character-generator layers (CREDITS.md):
# body, plain skirt (recoloured navy), blue blouse, white apron, head, long hair
# (recoloured blue). Her whale bits are drawn on top: a cowlick (呆毛), a tail
# with a fluke, and a little whale on the apron.
# Walk sheets are 9 frames x 4 rows of 64x64: rows up, left, down, right; frame 0 = standing.

CHAR = ASSETS / "character"
DIRECTIONS = {"up": 0, "left": 1, "down": 2, "right": 3}
HAIR_RAMP = [(22, 34, 84), (34, 62, 140), (52, 98, 190), (92, 148, 226), (156, 202, 246)]
SKIRT_RAMP = [(20, 30, 70), (32, 48, 108), (48, 72, 150), (78, 106, 182)]
TAIL = ((52, 92, 170), (26, 42, 96), (170, 206, 238))


def _ramp(img: pygame.Surface, ramp: list[tuple[int, int, int]]) -> pygame.Surface:
    """Recolour by brightness onto a colour ramp (keeps the shading, changes the hue)."""
    out = img.copy()
    w, h = out.get_size()
    for y in range(h):
        for x in range(w):
            r, g, b, a = out.get_at((x, y))
            if a == 0:
                continue
            lum = (0.3 * r + 0.59 * g + 0.11 * b) / 255
            out.set_at((x, y), (*ramp[min(len(ramp) - 1, int(lum * len(ramp) * 1.15))], a))
    return out


def recolor_leaves(img: pygame.Surface, ramp: list[tuple[int, int, int]]) -> pygame.Surface:
    """Recolour only the green (leafy) pixels by brightness: autumn leaves, keep the trunk."""
    out = img.copy()
    w, h = out.get_size()
    for y in range(h):
        for x in range(w):
            r, g, b, a = out.get_at((x, y))
            if a and g > r + 8 and g > b:
                lum = (0.3 * r + 0.59 * g + 0.11 * b) / 255
                out.set_at((x, y), (*ramp[min(len(ramp) - 1, int(lum * len(ramp) * 1.4))], a))
    return out


def bare(img: pygame.Surface) -> pygame.Surface:
    """The tree without its leaves (winter): only trunk and branches stay."""
    out = img.copy()
    w, h = out.get_size()
    for y in range(h):
        for x in range(w):
            r, g, b, a = out.get_at((x, y))
            if a and g > r + 8 and g > b:
                out.set_at((x, y), (0, 0, 0, 0))
    return out


AUTUMN_RAMP = [(122, 48, 24), (176, 82, 30), (214, 124, 42), (238, 168, 64), (250, 206, 110)]


def _bbox(layer: pygame.Surface, rect: tuple[int, int, int, int]) -> pygame.Rect | None:
    sub = layer.subsurface(rect)
    rects = pygame.mask.from_surface(sub).get_bounding_rects()
    if not rects:
        return None
    return rects[0].unionall(rects[1:])


def _tail(surf: pygame.Surface, x: int, y: int, dx: int, dy: int) -> None:
    """A whale tail from (x, y) towards (dx, dy): a tapering body ending in a wide two-lobed fluke."""
    import math

    body, line, light = TAIL
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length  # along the tail
    px, py = -uy, ux  # across it
    ex, ey = x + dx, y + dy

    def pt(along: float, across: float) -> tuple[int, int]:
        return round(x + ux * along + px * across), round(y + uy * along + py * across)

    stem = [pt(0, -3), pt(length, -1.5), pt(length, 1.5), pt(0, 3)]
    fluke = [pt(length - 1, 0), pt(length + 2, -6), pt(length + 5, -7), pt(length + 4, -3),
             pt(length + 3, 0), pt(length + 4, 3), pt(length + 5, 7), pt(length + 2, 6)]
    for shape in (stem, fluke):
        pygame.draw.polygon(surf, body, shape)
        pygame.draw.polygon(surf, line, shape, 1)
    pygame.draw.line(surf, light, pt(1, 1), pt(length - 1, 0.5))  # pale belly
    surf.set_at((round(ex), round(ey)), body)


def _whale_badge(surf: pygame.Surface, x: int, y: int) -> None:
    body, line, light = TAIL
    pygame.draw.ellipse(surf, body, (x, y, 5, 3))
    surf.set_at((x + 5, y), body)
    surf.set_at((x + 6, y - 1), body)
    surf.set_at((x + 1, y + 1), light)


def resident(direction: str, frame: int) -> pygame.Surface | None:
    """One 64x64 frame of her: direction up/left/down/right, frame 0 (standing) to 8."""
    key = ("resident", direction, frame)
    if key in _cache:
        return _cache[key]
    layers = {}
    for name in ("body_female_walk", "skirt_plain_walk", "blouse_blue_walk", "apron_full_white_walk",
                 "head_female_walk", "hair_long_walk"):
        sheet = _sheet_at(CHAR / f"{name}.png")
        if sheet is None:
            _cache[key] = None
            return None
        layers[name] = sheet
    row = DIRECTIONS[direction]
    rect = (frame * 64, row * 64, 64, 64)
    out = pygame.Surface((64, 64), pygame.SRCALPHA)
    body = _bbox(layers["body_female_walk"], rect)
    head = _bbox(layers["head_female_walk"], rect) or body
    # the tail first, so the body covers its root (except from behind)
    tail_at = {"down": (body.right - 5, body.bottom - 11, 6, 3), "left": (body.right - 6, body.bottom - 13, 7, 3),
               "right": (body.left + 5, body.bottom - 13, -7, 3)}
    if direction in tail_at:
        _tail(out, *tail_at[direction])
    out.blit(layers["body_female_walk"], (0, 0), rect)
    out.blit(_ramp(layers["skirt_plain_walk"].subsurface(rect), SKIRT_RAMP), (0, 0))
    out.blit(layers["blouse_blue_walk"], (0, 0), rect)
    out.blit(layers["apron_full_white_walk"], (0, 0), rect)
    out.blit(layers["head_female_walk"], (0, 0), rect)
    out.blit(_ramp(layers["hair_long_walk"].subsurface(rect), HAIR_RAMP), (0, 0))
    if direction == "up":
        _tail(out, body.centerx + 3, body.bottom - 12, 7, 4)  # out from under the skirt
    hair = _bbox(layers["hair_long_walk"], rect) or head
    cx = hair.centerx + (2 if direction == "left" else -2 if direction == "right" else 0)
    for i, (px, py) in enumerate(((cx, hair.top), (cx + 1, hair.top - 1), (cx + 2, hair.top - 2), (cx + 2, hair.top - 3), (cx + 1, hair.top - 4))):
        out.set_at((px, py), HAIR_RAMP[2 if i < 3 else 3])
    if direction == "down":
        _whale_badge(out, body.centerx - 3, body.bottom - 16)
    _cache[key] = out
    return out


def _sheet_at(path: Path) -> pygame.Surface | None:
    key = str(path)
    if key not in _sheets:
        try:
            _sheets[key] = pygame.image.load(key)
        except (FileNotFoundError, pygame.error):
            _sheets[key] = None
    return _sheets[key]


# --------------------------------------------------------------------------- the cat (bluecarrot16's LPC cats, golden coat)

CAT_COLUMNS = 4  # per coat: 3 walking frames + lying down
CAT_COAT = 1  # 0 white, 1 golden (an orange tabby), 2 brown, 3 black
CAT_ROWS = {"right": 0, "up": 1, "down": 2, "left": 3, "sit": 4}


def cat(pose: str, frame: int = 0) -> pygame.Surface | None:
    """The cat: pose left/right/up/down (frame 0-2), 'sit', or 'sleep'."""
    key = ("cat", pose, frame)
    if key not in _cache:
        sheet = _sheet("cats.png")
        if sheet is None:
            _cache[key] = None
        else:
            col = CAT_COAT * CAT_COLUMNS + (3 if pose == "sleep" else frame % 3)
            row = 0 if pose == "sleep" else CAT_ROWS[pose]
            _cache[key] = sheet.subsurface((col * 32, row * 32, 32, 32)).copy()
    return _cache[key]
