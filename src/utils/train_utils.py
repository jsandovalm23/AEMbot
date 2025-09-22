# ===============================
# src/utils/train_utils.py
# ===============================
# Helpers for driver rotation (2-week cycle) and fetching passenger/backup
# from the weekly/daily draw CSVs.
#
# CSVs:
#   File: VsYYYYMMDD_sorteos.csv  (YYYYMMDD = Sunday of that week)
#   Columns: fecha (yyyymmdd), semana (YYYY-WW), tipo ("D"|"W"|"weekend"), detalle (str)
#
# Daily (D) detail (per-day):
#   "D|for:YYYYMMDD|passenger:Name|backups:Name1,Name2"
#
# Weekly (W) — two supported shapes:
#   A) Per-day lines (current bot):
#      "W|for:YYYYMMDD|passenger:Name|backups:Name1,Name2"
#   B) One line mapping Mon–Fri (legacy, flexible):
#      "mon=Alice|b1=Bob|b2=Eve; tue=Carol|b1=Dan; ...", also supports Spanish keys.
#
# Resolution order (Mon–Fri):
#   1) Look for W in previous Sunday's CSV (per-day W preferred; otherwise legacy map).
#   2) If no W:
#       - Monday: D in previous Sunday's CSV.
#       - Tue–Fri: D in previous Sunday's CSV; if not found → D in this week's CSV.
#
from __future__ import annotations
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import csv
import os
import re

from .csv_utils import week_csv_names
from .date_utils import yyyymmdd

UTC = timezone.utc

# ----------------------------------------
# Driver rotation (10 names, 2-week cycle)
# ----------------------------------------

def _monday_of(d: date) -> date:
    """Return the Monday of the ISO week for the given date."""
    return d - timedelta(days=d.weekday())  # Monday=0

def driver_for_day(drivers10: List[str], anchor_monday: date, game_day: date) -> Optional[str]:
    """
    drivers10: list of up to 10 drivers (week A → indices 0..4, week B → 5..9)
    anchor_monday: a Monday date that marks the start of a 2-week cycle
    game_day: date in game calendar (Mon..Fri valid)
    - Returns None on weekend (Sat/Sun).
    - Returns "Pending" if the slot is missing/blank.
    """
    # Normalize weeks to Mondays for stable week math
    anchor_monday = _monday_of(anchor_monday)
    week_monday = _monday_of(game_day)

    # Weekend → no conductor day
    wd = game_day.isoweekday()  # Mon=1..Sun=7
    if wd < 1 or wd > 5:
        return None

    # Week parity (A/B)
    delta_days  = (week_monday - anchor_monday).days
    delta_weeks = delta_days // 7
    week_parity = delta_weeks & 1

    base = 0 if week_parity == 0 else 5
    idx  = base + (wd - 1)          # Lun=1 -> +0 ... Vie=5 -> +4

    # Missing list/slot ⇒ "Pending"
    if not drivers10 or idx >= len(drivers10):
        return "Pending"

    name = (drivers10[idx] or "").strip()
    return name if name else "Pending"


def weekly_preview(drivers10: List[str], anchor_monday: date, monday_real: date) -> List[Tuple[str, str, str]]:
    """
    Preview Mon–Fri: returns list of tuples (label, driver_or_pending, passenger_label)
    passenger_label is a placeholder; it gets filled when draws exist.
    `monday_real` is a real-world date for Monday (not game-adjusted); used for labels only.
    """
    out: List[Tuple[str, str, str]] = []
    monday_real = _monday_of(monday_real)
    for i in range(5):  # Mon..Fri
        gd = monday_real + timedelta(days=i)
        label = gd.strftime("%a %d/%m")
        drv = driver_for_day(drivers10, anchor_monday, gd)
        if drv is None or not drv.strip():
            drv = "Pending"
        out.append((label, drv, "VIP TBD"))
    return out

# ----------------------------------------
# Reading draws for a specific day
# ----------------------------------------

_DAY_MAP = {
    # English
    "mon": "mon", "tue": "tue", "wed": "wed", "thu": "thu", "fri": "fri",
    "sat": "sat", "sun": "sun",
    # Spanish
    "lun": "mon", "mar": "tue", "mie": "wed", "mié": "wed", "jue": "thu", "vie": "fri",
    "sab": "sat", "sáb": "sat", "dom": "sun",
}

_DEF_ORDER = ["mon", "tue", "wed", "thu", "fri"]

def _key_for_weekday(dt: date) -> str:
    # Monday=1..Sunday=7
    idx = dt.isoweekday()
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][idx - 1]

def _norm_day_key(s: str) -> Optional[str]:
    if not s:
        return None
    s2 = s.strip().lower()
    return _DAY_MAP.get(s2)

# ---------- parsing helpers for legacy W (single-line map) ----------

_re_block_split = re.compile(r"[;,]\s*")
_re_kv = re.compile(r"(?P<k>[a-zA-Záéíóúñ]+)\s*[:=]\s*(?P<v>.+)$")
_re_inner_b = re.compile(r"\b(b1|b2)\s*[:=]\s*([^|,;]+)")

def _parse_weekly_detail(detail: str) -> Dict[str, Dict[str, str]]:
    """
    Parses a flexible weekly detail string into:
      { day_key: {"pax": <name>, "b1": <name?>, "b2": <name?> } }
    Supports inputs like:
      "mon=Alice|b1=Bob|b2=Eve; tue=Carol|b1=Dan"
      "lun: Alicia (b1=Roberto, b2=Eva), mar: Carla (b1=Daniel)"
    """
    out: Dict[str, Dict[str, str]] = {}
    if not detail:
        return out

    # Split into blocks per day by ';' or ',' (be flexible)
    blocks = _re_block_split.split(detail)
    for raw in blocks:
        part = raw.strip()
        if not part:
            continue
        m = _re_kv.search(part)
        if not m:
            # try patterns like "mon Alice (b1=Bob)"
            tokens = part.split()
            if not tokens:
                continue
            dk = _norm_day_key(tokens[0])
            if not dk:
                continue
            rest = part[len(tokens[0]):].strip(" :-\t")
            val = rest
        else:
            dk = _norm_day_key(m.group("k"))
            val = m.group("v").strip()
        if not dk:
            continue

        pax = None
        b1 = None
        b2 = None

        inner = None
        if "(" in val and ")" in val:
            p1 = val.find("(")
            p2 = val.rfind(")")
            if p2 > p1:
                inner = val[p1+1:p2]
                pax = val[:p1].strip().strip("|,;") or None
        if inner is None:
            inner = val

        for m2 in _re_inner_b.finditer(inner):
            key = m2.group(1).lower()
            name = m2.group(2).strip()
            if key == "b1":
                b1 = name
            elif key == "b2":
                b2 = name

        if pax is None:
            pax = re.split(r"[|,]", val, maxsplit=1)[0].strip()
            if pax.lower().startswith("b1=") or pax.lower().startswith("b2="):
                pax = None

        if pax:
            out[dk] = {"pax": pax}
            if b1:
                out[dk]["b1"] = b1
            if b2:
                out[dk]["b2"] = b2

    return out

# ---------- helpers for CSV path selection ----------

def _utc_from_date(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)

def _csv_path_for(dt_utc: datetime) -> Optional[str]:
    names = week_csv_names(dt_utc)
    path = names.get("sorteos")
    return path if path and os.path.exists(path) else None

def _prev_sunday_ref(d: date) -> datetime:
    """Reference dt for CSV of the previous Sunday to 'd'."""
    return _utc_from_date(d - timedelta(days=1))

def _this_week_ref(d: date) -> datetime:
    """Reference dt for CSV of the current week containing 'd'."""
    return _utc_from_date(d)

# ---------- parse 'detalle' key:value pairs (pipe-separated) ----------

_re_kv_pipe = re.compile(r"([a-zA-Z_]+):([^|]+)")

def _parse_pipe_kv(detail: str) -> Dict[str, str]:
    """
    Parses pipe-separated key:value pairs:
      e.g. "W|for:20250922|passenger:Alice|backups:Bob,Eve"
    Ignores the leading "W|" or "D|" or "weekend|".
    """
    s = detail or ""
    # Remove leading type prefix if present
    if s.startswith(("W|", "D|", "weekend|")):
        s = s.split("|", 1)[1] if "|" in s else ""
    out: Dict[str, str] = {}
    for m in _re_kv_pipe.finditer(s):
        k = m.group(1).strip().lower()
        v = m.group(2).strip()
        out[k] = v
    return out

# ---------- core search helpers ----------

def _find_per_day_pick(path: str, target_yymmdd: str, kinds: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
    """
    Search for per-day W/D entries in CSV 'path' with for == target_yymmdd.
    Returns (passenger, first_backup) or (None, None).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tipo = (row.get("tipo") or "").strip().lower()
                if tipo not in {k.lower() for k in kinds}:
                    continue
                kv = _parse_pipe_kv(row.get("detalle") or "")
                if kv.get("for") == target_yymmdd:
                    pax = kv.get("passenger")
                    bkp = None
                    backs = kv.get("backups", "")
                    if backs:
                        first = (backs.split(",")[0] or "").strip()
                        bkp = first or None
                    return pax, bkp
    except Exception:
        pass
    return (None, None)

def _find_weekly_map_pick(path: str, target_day_key: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Legacy support: find a single W row with a Mon–Fri mapping in 'detalle' and get
    passenger/b1 for the given weekday key (mon..fri).
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tipo = (row.get("tipo") or "").strip().lower()
                if tipo != "w":
                    continue
                det = (row.get("detalle") or "").strip()
                # If it's a per-day W, _parse_pipe_kv will catch it earlier in _find_per_day_pick.
                # Here we try legacy multi-day map:
                mapping = _parse_weekly_detail(det)
                if not mapping:
                    continue
                entry = mapping.get(target_day_key)
                if entry:
                    pax = entry.get("pax")
                    bkp = entry.get("b1") or entry.get("b2")
                    if pax:
                        return pax, bkp
    except Exception:
        pass
    return (None, None)

# ---------- main API ----------

def read_draw_for_date(real_day: date) -> Tuple[Optional[str], Optional[str]]:
    """
    Returns (passenger, first_backup) for the given real-world `date` (Mon–Fri).
    Resolution:
      1) Weekly W (per-day W preferred, else legacy mapping) in CSV of previous Sunday.
      2) If no W:
         - Monday: D in previous Sunday's CSV.
         - Tue–Fri: D in previous Sunday's CSV; if not found → D in this week's CSV.
    If not found, returns (None, None).
    """
    wd = real_day.isoweekday()  # Mon=1..Sun=7
    if wd < 1 or wd > 5:
        return (None, None)

    target = yyyymmdd(real_day)
    day_key = _key_for_weekday(real_day)  # mon..fri

    prev_csv = _csv_path_for(_prev_sunday_ref(real_day))
    this_csv = _csv_path_for(_this_week_ref(real_day))

    # 1) Try W (per-day W first) in previous Sunday's CSV
    if prev_csv:
        pax, bkp = _find_per_day_pick(prev_csv, target, kinds=("W",))
        if pax:
            return pax, bkp
        # Legacy single-line W map
        pax, bkp = _find_weekly_map_pick(prev_csv, day_key)
        if pax:
            return pax, bkp

    # 2) Try D
    if wd == 1:  # Monday
        if prev_csv:
            pax, bkp = _find_per_day_pick(prev_csv, target, kinds=("D",))
            if pax:
                return pax, bkp
        return (None, None)
    else:  # Tue–Fri
        if prev_csv:
            pax, bkp = _find_per_day_pick(prev_csv, target, kinds=("D",))
            if pax:
                return pax, bkp
        if this_csv:
            pax, bkp = _find_per_day_pick(this_csv, target, kinds=("D",))
            if pax:
                return pax, bkp
        return (None, None)
