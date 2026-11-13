"""Game clock.

The world runs on real time by default (scale 1.0). ``offset_seconds`` shifts the
game clock away from the wall clock and ``scale`` speeds it up, which is handy
while developing (e.g. scale 60 = one game hour per real minute).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

SEASONS = ("winter", "spring", "summer", "autumn")
SEASON_ZH = {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}


@dataclass
class Clock:
    scale: float = 1.0
    offset_seconds: float = 0.0
    _anchor_real: float = 0.0
    _anchor_game: float = 0.0

    def __post_init__(self) -> None:
        if self.scale <= 0:
            raise ValueError("clock scale must be positive")
        now = time.time()
        self._anchor_real = now
        self._anchor_game = now + self.offset_seconds

    def timestamp(self) -> float:
        """Game time as a POSIX timestamp."""
        return self._anchor_game + (time.time() - self._anchor_real) * self.scale

    def now(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp())

    def advance(self, game_seconds: float) -> None:
        """Jump the game clock forward (used by tests and by ``wait``)."""
        self._anchor_game += game_seconds


def season_of(dt: datetime) -> str:
    # Northern-hemisphere meteorological seasons.
    return SEASONS[(dt.month % 12) // 3]


def period_of(dt: datetime) -> str:
    h = dt.hour
    if 5 <= h < 8:
        return "清晨"
    if 8 <= h < 11:
        return "上午"
    if 11 <= h < 13:
        return "中午"
    if 13 <= h < 17:
        return "下午"
    if 17 <= h < 19:
        return "傍晚"
    if 19 <= h < 23:
        return "晚上"
    return "深夜"


def is_dark(dt: datetime) -> bool:
    return dt.hour < 6 or dt.hour >= 19
