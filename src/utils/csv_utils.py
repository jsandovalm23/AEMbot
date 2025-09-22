# ===============================
# src/utils/csv_utils.py
# ===============================
import os
from datetime import datetime, timedelta
from ..config import DATA_DIR
from .date_utils import iso_week_key, yyyymmdd, UTC


def ensure_dir(path: str) -> None:
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def week_bounds_utc(dt: datetime):
    iso = dt.isocalendar()
    monday_date = (dt - timedelta(days=iso.weekday - 1)).date()
    sunday_date = monday_date + timedelta(days=6)
    monday = datetime(monday_date.year, monday_date.month, monday_date.day, tzinfo=UTC)
    sunday = datetime(sunday_date.year, sunday_date.month, sunday_date.day, tzinfo=UTC)
    return monday, sunday


def week_csv_names(dt: datetime):
    ensure_dir(DATA_DIR)
    monday, sunday = week_bounds_utc(dt)
    sunday_stamp = sunday.strftime("%Y%m%d")
    return {
        "registros": os.path.join(DATA_DIR, f"Vs{sunday_stamp}_registros.csv"),
        "sorteos": os.path.join(DATA_DIR, f"Vs{sunday_stamp}_sorteos.csv"),
        "sunday": sunday_stamp,
    }


def _escape_csv(s: str) -> str:
    s = "" if s is None else str(s)
    if any(ch in s for ch in ('"', ',', '\n')):
        return '"' + s.replace('"', '""') + '"'
    return s


def append_registro(dt: datetime, name: str, points: int) -> None:
    paths = week_csv_names(dt)
    file = paths["registros"]
    header_needed = not os.path.exists(file)
    with open(file, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("fecha_dia,nombre_comandante,puntos\n")
        f.write(f"{yyyymmdd(dt)},{_escape_csv(name)},{points}\n")


def append_sorteo(dt: datetime, kind: str, detail: str) -> None:
    # kind: "D" (daily) | "W" (weekly) | "weekend"
    paths = week_csv_names(dt)
    file = paths["sorteos"]
    header_needed = not os.path.exists(file)
    with open(file, "a", encoding="utf-8") as f:
        if header_needed:
            f.write("fecha,semana,tipo,detalle\n")
        f.write(f"{yyyymmdd(dt)},{iso_week_key(dt)},{_escape_csv(kind)},{_escape_csv(detail)}\n")


def list_weeks_in_folder():
    ensure_dir(DATA_DIR)
    files = [f for f in os.listdir(DATA_DIR) if f.startswith("Vs") and f.endswith(".csv")]
    by = {}
    import re
    for f in files:
        m = re.match(r"^Vs(\d{8})_(registros|sorteos)\.csv$", f)
        if not m:
            continue
        sunday, kind = m.group(1), m.group(2)
        by.setdefault(sunday, {"sunday": sunday, "registros": None, "sorteos": None})
        by[sunday][kind] = f
    out = []
    for sunday, rec in by.items():
        dt = datetime.strptime(sunday, "%Y%m%d").replace(tzinfo=UTC)
        week = iso_week_key(dt)
        out.append({"week": week, **rec})
    out.sort(key=lambda x: x["week"])  # asc
    return out
