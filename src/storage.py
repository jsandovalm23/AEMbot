# ===============================
# src/storage.py
# ===============================
# src/storage.py — persistence (JSON + CSV appends) with robust helpers
from __future__ import annotations
import json, os, csv
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta, timezone, date

# Usa configuración centralizada
from .config import DATA_DIR, THRESHOLD
UTC = timezone.utc

DATA_JSON = os.path.join(DATA_DIR, "data.json")

# -------------------- core load/save --------------------

def _load() -> Dict[str, Any]:
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_JSON):
        return {}
    with open(DATA_JSON, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return {}

def _save(state: Dict[str, Any]) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = DATA_JSON + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_JSON)

# -------------------- schedules (MG/ZS) --------------------

def _ensure_schedules(state: Dict[str, Any]):
    state.setdefault("schedules", {"MG": None, "ZS": None})

def set_schedule(kind: str, first_utc_iso: str, hhmm_server: str, repeat_days: int, weekend_hhmm: str | None = None) -> None:
    state = _load()
    _ensure_schedules(state)
    state["schedules"][kind] = {
        "first_utc": first_utc_iso,
        "hhmm_server": hhmm_server,
        "weekend_hhmm": weekend_hhmm,
        "repeat_days": int(repeat_days),
        "updated_at": datetime.now(UTC).isoformat(),
    }
    _save(state)

def get_schedule(kind: str) -> Dict[str, Any] | None:
    state = _load()
    _ensure_schedules(state)
    return state["schedules"].get(kind)

# -------------------- train settings --------------------

def _ensure_train(state: Dict[str, Any]):
    state.setdefault("train", {
        "drivers": [],
        "anchor_monday": None,      # YYYY-MM-DD
        "post_full_on_monday": True
    })

def set_train_config(*, drivers: List[str] | None = None, anchor_monday_iso: str | None = None, post_full_on_monday: bool | None = None):
    state = _load()
    _ensure_train(state)
    if drivers is not None:
        state["train"]["drivers"] = drivers[:10]
    if anchor_monday_iso is not None:
        state["train"]["anchor_monday"] = anchor_monday_iso
    if post_full_on_monday is not None:
        state["train"]["post_full_on_monday"] = bool(post_full_on_monday)
    _save(state)

def get_train_config() -> Dict[str, Any]:
    state = _load()
    _ensure_train(state)
    return state["train"]

# -------------------- auto toggles & marks --------------------

def _ensure_auto(state: Dict[str, Any]):
    state.setdefault("auto", {
        "AUTO_DRAW_D": None, "AUTO_DRAW_W": None, "AUTO_VS_REMINDER": None, "AUTO_TRAIN_POST": None
    })
    state.setdefault("fired_marks", {})  # { key: iso_ts }

def set_auto_toggle(name: str, value: bool) -> None:
    state = _load()
    _ensure_auto(state)
    state["auto"][name] = bool(value)
    _save(state)

def get_auto_toggle(name: str) -> Optional[bool]:
    state = _load()
    _ensure_auto(state)
    return state["auto"].get(name)

def mark_fired(key: str) -> None:
    state = _load()
    _ensure_auto(state)
    state["fired_marks"][key] = datetime.now(UTC).isoformat()
    _save(state)

def has_fired(key: str) -> bool:
    state = _load()
    _ensure_auto(state)
    return key in state.get("fired_marks", {})

# -------------------- CSV helpers (same contract as antes) --------------------
from .utils.csv_utils import append_sorteo, week_csv_names, append_registro
from .utils.date_utils import to_game_date, from_game_date, yyyymmdd, yyyymmdd_from_date

# Expose append_sorteo and names so other modules import from storage if desired
__all__ = [
    "set_schedule", "get_schedule",
    "set_train_config", "get_train_config",
    "set_auto_toggle", "get_auto_toggle",
    "mark_fired", "has_fired",
    "append_sorteo", "week_csv_names",
    "register_points", "weekly_summary",
]

# -------------------- points registry (VS) --------------------

def _ensure_points(state: Dict[str, Any]):
    state.setdefault("points", {})  # {"YYYY-WW": {"YYYYMMDD": [ {name, points} ... ] } }

def _iso_week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-{iso.week:02d}"

def _monday_of_game_week(game_day: date) -> date:
    # lunes de la semana del calendario de juego
    return game_day - timedelta(days=(game_day.isoweekday() - 1))

_DAY_OFFSETS = {
    # en inglés porque tus slash commands están en inglés
    "mon": 0, "monday": 0,
    "tue": 1, "tuesday": 1,
    "wed": 2, "wednesday": 2,
    "thu": 3, "thursday": 3,
    "fri": 4, "friday": 4,
    "sat": 5, "saturday": 5,
    # soporta español por conveniencia
    "lun": 0, "mar": 1, "mie": 2, "mié": 2, "jue": 3, "vie": 4, "sab": 5, "sáb": 5,
}

def register_points(name: str, amount: int, day: str | None = None) -> Tuple[str, str]:
    """
    Registra puntos para un jugador en la semana ISO actual (modelo de juego).
    - name: nombre del jugador (del juego)
    - amount: puntos enteros
    - day: opcional ('mon'..'sat' o abreviatura ES). Si None, usa el día de juego actual.
    Reglas:
      * El evento VS corre de lun–sáb. El domingo puede registrar para lun–sáb de la semana actual.
      * Siempre se registra en la semana ISO actual (lunes–domingo) usando calendario del juego (corte 02:00 UTC).
    Devuelve (week_key, yyyymmdd_del_registro)
    """
    if not isinstance(amount, int):
        raise ValueError("amount must be integer")

    state = _load()
    _ensure_points(state)

    now = datetime.now(UTC)
    game_today = to_game_date(now)  # fecha en calendario del juego (corte 02:00 UTC)
    monday = _monday_of_game_week(game_today)

    # Determinar fecha efectiva
    if day:
        key = day.strip().lower()
        if key not in _DAY_OFFSETS:
            raise ValueError("day must be one of mon..sat (or lun..sab)")
        offset = _DAY_OFFSETS[key]
        target = monday + timedelta(days=offset)
    else:
        # usar el día de juego actual
        target = game_today

    # Limitar a lun–sáb siempre (domingo no es día válido del VS)
    if target.isoweekday() == 7:
        raise ValueError("VS runs Mon–Sat; use a Mon–Sat day key when registering on Sunday.")

    week_key = _iso_week_key(target)
    date_key = yyyymmdd_from_date(target)

    week_bucket = state["points"].setdefault(week_key, {})
    day_list: List[Dict[str, Any]] = week_bucket.setdefault(date_key, [])
    day_list.append({"name": name, "points": int(amount)})

    _save(state)

    # CSV: fecha_dia,nombre_comandante,puntos
    append_registro(date_key, name, int(amount))

    return week_key, date_key

def weekly_summary() -> Dict[str, Any]:
    """
    Devuelve un resumen de la semana actual (calendario del juego):
      {
        'week': 'YYYY-WW',
        'days': { 'YYYYMMDD': [{'name':..., 'points':...}, ...], ... },
        'eligibles_by_day': { 'YYYYMMDD': [names ...], ... },
        'averages': { 'name': average_mon_to_sat },
      }
    La elegibilidad diaria es >= THRESHOLD. Promedios: media de los días con registro (lun–sáb).
    """
    state = _load()
    _ensure_points(state)

    now = datetime.now(UTC)
    game_today = to_game_date(now)
    monday = _monday_of_game_week(game_today)
    week_key = _iso_week_key(game_today)

    days: Dict[str, List[Dict[str, Any]]] = state.get("points", {}).get(week_key, {})

    eligibles_by_day: Dict[str, List[str]] = {}
    sums: Dict[str, int] = {}
    counts: Dict[str, int] = {}

    # recorrer lun–sáb
    for i in range(6):
        d = monday + timedelta(days=i)
        dk = yyyymmdd_from_date(d)
        entries = days.get(dk, [])

        # elegibles del día
        eligibles_by_day[dk] = [e["name"] for e in entries if int(e.get("points", 0)) >= THRESHOLD]

        # acumular para promedios por jugador (solo si tuvo registro ese día)
        # si un jugador tiene múltiples entradas ese día, se suman
        per_player: Dict[str, int] = {}
        for e in entries:
            n = e["name"]
            per_player[n] = per_player.get(n, 0) + int(e.get("points", 0))
        for n, p in per_player.items():
            sums[n] = sums.get(n, 0) + p
            counts[n] = counts.get(n, 0) + 1

    averages = {n: (sums[n] / counts[n]) for n in sums.keys() if counts.get(n, 0) > 0}

    return {
        "week": week_key,
        "days": days,
        "eligibles_by_day": eligibles_by_day,
        "averages": averages,
    }
