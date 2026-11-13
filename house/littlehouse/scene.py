"""Where things are drawn: the tile layout of the house, yard and beach.

Pure data (no pygame), so layout can be tested and reused. Coordinates are in
16-pixel tiles: (x, y, w, h). The map is a top-down cutaway:

    rows 0-1    back wall with windows
    rows 2-11   bedroom | living room | kitchen
    row  12     front wall with the door
    rows 13-18  yard (plots, mailbox, consignment box)
    rows 19-22  beach
    rows 23-25  sea
"""

from __future__ import annotations

import hashlib

TILE = 16
COLS, ROWS = 40, 26
HUD_H = 20

Rect = tuple[int, int, int, int]

ROOM_FLOORS: dict[str, Rect] = {
    "bedroom": (1, 2, 11, 10),
    "living_room": (13, 2, 14, 10),
    "kitchen": (28, 2, 11, 10),
}
YARD: Rect = (0, 13, COLS, 6)
BEACH: Rect = (0, 19, COLS, 4)
SEA: Rect = (0, 23, COLS, 3)

INNER_WALL_COLS = (12, 27)
INNER_DOOR_ROWS = (7, 8)
FRONT_WALL_ROW = 12
FRONT_DOOR_COLS = (19, 20)
WINDOWS: dict[str, tuple[int, int]] = {  # x of a 2-tile window in the back wall
    "bedroom": 4, "living_room": 18, "kitchen": 32,
}

FIXTURES: dict[str, Rect] = {
    "bed": (2, 3, 2, 3),
    "bookshelf": (6, 2, 3, 2),
    "pot#2": (10, 10, 1, 1),
    "sofa": (14, 3, 3, 2),
    "shelf": (22, 2, 3, 2),
    "catalog": (19, 5, 2, 2),  # the little table with the order catalog (not an object)
    "pot#1": (13, 10, 1, 1),
    "stove": (29, 2, 2, 2),
    "table": (33, 6, 3, 2),
    "plot#1": (3, 14, 3, 2),
    "plot#2": (7, 14, 3, 2),
    "plot#3": (11, 14, 3, 2),
    "parcel": (21, 13, 1, 1),
    "mailbox": (24, 13, 1, 1),
    "consign": (26, 13, 2, 1),
    "rock": (33, 20, 2, 2),
}

# Static scenery that is not a world object.
EXTRAS: dict[str, Rect] = {
    "counter": (34, 2, 5, 1),
    "fridge": (37, 3, 2, 2),
    "wardrobe": (10, 2, 2, 2),
    "tree": (33, 14, 3, 3),
}
BUSHES = [(1, 13), (17, 13), (30, 17), (38, 15)]

# Where placed furniture goes, in order, per room.
DECOR_SLOTS: dict[str, list[tuple[int, int]]] = {
    "living_room": [(17, 7), (24, 7), (14, 6), (21, 9), (25, 10)],
    "bedroom": [(4, 7), (8, 6), (2, 9), (6, 9), (9, 4)],
    "kitchen": [(30, 7), (29, 9), (37, 9), (32, 10)],
}

ANCHORS: dict[str, tuple[int, int]] = {
    "bedroom": (6, 6),
    "living_room": (20, 8),
    "kitchen": (31, 5),
    "yard": (20, 16),
    "beach": (22, 20),
}

BEACH_SPOTS = [(4, 20), (8, 21), (12, 19), (15, 21), (18, 20), (25, 21), (28, 19), (30, 21), (37, 20), (2, 21)]


def find_spots(find_ids: list[str]) -> dict[str, tuple[int, int]]:
    """Stable, non-overlapping beach positions for the finds lying there."""
    taken: set[int] = set()
    out = {}
    for fid in sorted(find_ids):
        i = int(hashlib.md5(fid.encode()).hexdigest(), 16) % len(BEACH_SPOTS)
        while i in taken and len(taken) < len(BEACH_SPOTS):
            i = (i + 1) % len(BEACH_SPOTS)
        taken.add(i)
        out[fid] = BEACH_SPOTS[i]
    return out


def decor_spots(room: str, decor_ids: list[str]) -> dict[str, tuple[int, int]]:
    slots = DECOR_SLOTS.get(room, [])
    return {d: slots[i % len(slots)] for i, d in enumerate(decor_ids)} if slots else {}


Point = tuple[float, float]

# Walking between areas goes through these points (from the first area's side
# to the second's); the reverse direction uses them reversed.
DOORS: dict[tuple[str, str], list[Point]] = {
    ("bedroom", "living_room"): [(11, 8), (13, 8)],
    ("living_room", "kitchen"): [(26, 8), (28, 8)],
    ("living_room", "yard"): [(19.5, 11), (19.5, 13)],
    ("yard", "beach"): [(19.5, 18), (19.5, 20)],
}


def door_points(a: str, b: str) -> list[Point]:
    if (a, b) in DOORS:
        return list(DOORS[(a, b)])
    if (b, a) in DOORS:
        return list(reversed(DOORS[(b, a)]))
    return []


def route(rooms: list[str], start: Point, end: Point) -> list[Point]:
    """Waypoints from ``start`` to ``end`` walking through ``rooms`` in order."""
    points: list[Point] = [start]
    for a, b in zip(rooms, rooms[1:]):
        points += door_points(a, b)
    points.append(end)
    return points


def spot_of(obj_id: str, room: str, find_pos: dict[str, tuple[int, int]],
            decor_pos: dict[str, tuple[int, int]] | None = None) -> Point:
    """Where she stands to use something: just below or beside it."""
    if obj_id in find_pos:
        x, y = find_pos[obj_id]
        return x + 1, y
    if decor_pos and obj_id in decor_pos:
        x, y = decor_pos[obj_id]
        return x, min(y + 1, _area_bottom(room))
    rect = FIXTURES.get(obj_id) or EXTRAS.get(obj_id)
    if rect and _in_area(room, rect[0], rect[1]):
        x, y, w, h = rect
        return x + w // 2, min(y + h, _area_bottom(room))
    return ANCHORS[room]


def resident_tile(location: str, focus: str | None, find_pos: dict[str, tuple[int, int]]) -> tuple[int, int]:
    """Stand next to the thing she last touched, else at the room's anchor."""
    if focus:
        spot = spot_of(focus, location, find_pos)
        return int(spot[0]), int(spot[1])
    return ANCHORS[location]


def _area(location: str) -> Rect:
    if location in ROOM_FLOORS:
        return ROOM_FLOORS[location]
    return {"yard": YARD, "beach": BEACH}[location]


def _in_area(location: str, x: int, y: int) -> bool:
    ax, ay, aw, ah = _area(location)
    return ax <= x < ax + aw and ay <= y < ay + ah


def _area_bottom(location: str) -> int:
    ax, ay, aw, ah = _area(location)
    return ay + ah - 1
