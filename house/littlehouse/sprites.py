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
