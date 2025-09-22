# ===============================
# src/utils/date_utils.py (UTC-only, game cutover 02:00)
# ===============================
from __future__ import annotations
from datetime import datetime, timedelta, timezone, time, date
from typing import List, Tuple
from ..config import GAME_CUTOVER_UTC

UTC = timezone.utc
CUTOVER_UTC = time(GAME_CUTOVER_UTC, 0, 0)


def now_utc() -> datetime:
    return datetime.now(UTC)


def to_game_date(dt: datetime) -> date:
    """Return the game day (as a date) for a given UTC datetime.
    Game day changes at 02:00 UTC. If time >= 02:00 → same date; otherwise → previous date.
    """
    dt = dt.astimezone(UTC)
    if dt.time() >= CUTOVER_UTC:
        return dt.date()
    return (dt - timedelta(days=1)).date()


def from_game_date(d: date) -> datetime:
    """Map a game-day date to a stable UTC datetime (noon UTC)."""
    return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=UTC)


def yyyymmdd_from_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def yyyymmdd(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d")


def iso_week_key(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-{iso.week:02d}"


def week_bounds(dt: datetime) -> Tuple[datetime, datetime]:
    iso = dt.isocalendar()
    monday_date = (dt - timedelta(days=iso.weekday - 1)).date()
    sunday_date = monday_date + timedelta(days=6)
    monday = datetime(monday_date.year, monday_date.month, monday_date.day, tzinfo=UTC)
    sunday = datetime(sunday_date.year, sunday_date.month, sunday_date.day, tzinfo=UTC)
    return monday, sunday

DAY_MAP = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


def parse_optional_day_abbrev(abbrev: str | None) -> int | None:
    if not abbrev:
        return None
    return DAY_MAP.get(abbrev.lower())


def game_date_for_abbrev_this_week(abbrev: str, base: datetime | None = None) -> datetime | None:
    base = base or now_utc()
    gd = to_game_date(base)
    dow = parse_optional_day_abbrev(abbrev)
    if not dow:
        return None
    monday = gd - timedelta(days=(gd.isoweekday() - 1))
    target = monday + timedelta(days=dow - 1)
    return from_game_date(target)


def game_week_monsat(base: datetime) -> List[datetime]:
    gd = to_game_date(base)
    monday = gd - timedelta(days=(gd.isoweekday() - 1))
    return [from_game_date(monday + timedelta(days=i)) for i in range(6)]


def game_week_monfri(base: datetime) -> List[datetime]:
    gd = to_game_date(base)
    monday = gd - timedelta(days=(gd.isoweekday() - 1))
    return [from_game_date(monday + timedelta(days=i)) for i in range(5)]


def is_game_mon_to_sat(d: date) -> bool:
    return 1 <= d.isoweekday() <= 6


def is_game_mon_to_fri(d: date) -> bool:
    return 1 <= d.isoweekday() <= 5
