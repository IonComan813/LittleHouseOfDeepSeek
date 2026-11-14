"""The night sky over the house, from the real date (the game clock is real time).

Moon phase from the mean synodic month counted from a known new moon; moonrise
roughly 50 minutes later each day (good enough to say whether the moon is up);
the big yearly meteor showers on their real peak nights. Pure functions.
"""

from __future__ import annotations

from datetime import datetime, timezone

SYNODIC_DAYS = 29.530588853
NEW_MOON = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)  # a known new moon

# (name, from age, to age) in days since new moon
PHASES = (
    ("新月", 0.0, 1.85), ("蛾眉月", 1.85, 5.54), ("上弦月", 5.54, 9.23), ("盈凸月", 9.23, 12.92),
    ("满月", 12.92, 16.61), ("亏凸月", 16.61, 20.30), ("下弦月", 20.30, 23.99), ("残月", 23.99, 27.68),
    ("新月", 27.68, SYNODIC_DAYS),
)

# (name, month, first day, last day, (best hour from, to)) — peak nights of the big showers
METEOR_SHOWERS = (
    ("象限仪座流星雨", 1, 2, 4), ("天琴座流星雨", 4, 21, 23), ("宝瓶座η流星雨", 5, 5, 7),
    ("英仙座流星雨", 8, 11, 13), ("猎户座流星雨", 10, 20, 22), ("狮子座流星雨", 11, 16, 18),
    ("双子座流星雨", 12, 13, 15),
)

SEASON_STARS = {
    "spring": "北斗七星高高地挂在北边的天上，斗柄指着东方",
    "summer": "夏季大三角很亮，银河从南边的海面上升起来",
    "autumn": "秋天的星星稀疏些，飞马座的四边形端端正正地挂在头顶",
    "winter": "猎户座的三颗腰带星排成一线，天狼星在东南边闪得厉害",
}


def moon_age(dt: datetime) -> float:
    """Days since the last new moon (0 ≤ age < 29.53)."""
    aware = dt if dt.tzinfo else dt.astimezone()
    days = (aware - NEW_MOON).total_seconds() / 86400.0
    return days % SYNODIC_DAYS


def moon_phase(dt: datetime) -> str:
    age = moon_age(dt)
    return next(name for name, a, b in PHASES if a <= age < b)


def moon_light(dt: datetime) -> float:
    """How full the moon is: 0 (new) … 1 (full)."""
    age = moon_age(dt)
    return 1.0 - abs(age - SYNODIC_DAYS / 2) / (SYNODIC_DAYS / 2)


def moon_up(dt: datetime) -> bool:
    """Roughly whether the moon is above the horizon: it rises about 06:00 at new
    moon and about 50 minutes later each day, and stays up about 12 hours."""
    rise = (6.0 + moon_age(dt) / SYNODIC_DAYS * 24.0) % 24.0
    hour = dt.hour + dt.minute / 60.0
    return (hour - rise) % 24.0 < 12.0


def meteor_shower(dt: datetime) -> str | None:
    """The meteor shower at its peak tonight, if any (a night belongs to the evening's date)."""
    day = dt if dt.hour >= 12 else datetime.fromordinal(dt.toordinal() - 1)
    for name, month, first, last in METEOR_SHOWERS:
        if day.month == month and first <= day.day <= last:
            return name
    return None


def moon_text(dt: datetime) -> str:
    phase = moon_phase(dt)
    if phase == "新月":
        return "今晚是新月，看不见月亮"
    if moon_up(dt):
        return f"天上挂着{phase}"
    # a waxing moon sets in the evening; a waning one rises late at night
    return f"{phase}已经落下去了" if moon_age(dt) < SYNODIC_DAYS / 2 else f"{phase}还没升起来"
