# ===============================
# src/storage.py
# ===============================
# src/storage.py — persistence (JSON + CSV appends) with robust helpers
from __future__ import annotations
import json, os, csv
from typing import Any, Dict, List, Tuple, Optional
from datetime import datetime, timedelta, timezone, date, time

# Usa configuración centralizada
from .config import DATA_DIR, THRESHOLD
UTC = timezone.utc

# -------------------- name matching helpers (sin alias fijos) --------------------
# Objetivo:
#  - Tratar como iguales nombres que solo difieren en mayúsculas/espacios.
#  - Reconciliar typos ASCII MUY leves (distancia de edición <= 1) cuando comparten 1er/último alfanumérico,
#    p. ej. "ChikenLobo" vs "ChickenLobo", "Lnhrf" vs "Lnhrs".
#  - Mantener separados nombres con caracteres no ASCII (p. ej. "ANGELO" vs "ANGELØ").

def _collapse_spaces(s: str) -> str:
    return " ".join((s or "").strip().split())

def _canonical_key(s: str) -> str:
    # casefold (robusto) + colapso de espacios. NO quitamos diacríticos.
    return _collapse_spaces(str(s)).casefold()

def _is_ascii(s: str) -> bool:
    try:
        return str(s).isascii()
    except Exception:
        return all(ord(ch) < 128 for ch in str(s))

def _levenshtein(a: str, b: str) -> int:
    a, b = str(a), str(b)
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0: return lb
    if lb == 0: return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i]
        for j, cb in enumerate(b, 1):
            ins = curr[j-1] + 1
            dele = prev[j] + 1
            sub = prev[j-1] + (0 if ca == cb else 1)
            curr.append(min(ins, dele, sub))
        prev = curr
    return prev[-1]

def _first_last_alnum_equal(a: str, b: str) -> bool:
    import re
    ra = re.findall(r"[A-Za-z0-9]", a)
    rb = re.findall(r"[A-Za-z0-9]", b)
    if not ra or not rb:
        return False
    return (ra[0].casefold() == rb[0].casefold()) and (ra[-1].casefold() == rb[-1].casefold())

def _names_equivalent(a: str, b: str) -> bool:
    """
    Reglas:
      1) Igualdad por casefold + espacios (independiente de mayúsculas y dobles espacios).
      2) Si AMBOS son ASCII y min(len)>=5 y comparten primer/último alfanumérico,
         aceptamos Levenshtein <= 1 (corrige typos muy leves).
      3) Si alguno NO es ASCII (p. ej. 'Ø'), solo aceptamos igualdad exacta case-insensitive.
    """
    if _canonical_key(a) == _canonical_key(b):
        return True
    if _is_ascii(a) and _is_ascii(b):
        aa, bb = _collapse_spaces(a), _collapse_spaces(b)
        if min(len(aa), len(bb)) >= 5 and _first_last_alnum_equal(aa, bb):
            return _levenshtein(aa.casefold(), bb.casefold()) <= 1
    return False

def _pick_display_name(a: str, b: str) -> str:
    """
    Al fusionar 'a' y 'b', elegimos un nombre para mostrar:
      - Preferimos el que tenga más caracteres alfabéticos.
      - Empate: preferimos el más largo.
      - Último recurso: 'a'.
    """
    import re
    na = len(re.findall(r"[A-Za-z]", a or ""))
    nb = len(re.findall(r"[A-Za-z]", b or ""))
    if nb > na:
        return b
    if nb == na and len(b or "") > len(a or ""):
        return b
    return a

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

def register_points(name: str, amount: int, day: str | None = None, ref_date: date | datetime | None = None) -> Tuple[str, str, int]:
    """
    Registra puntos para un jugador en la semana ISO del calendario de juego, con opción de
    referenciar explícitamente la semana (ref_date) para cerrar rezagos en domingo/lunes.
    - name: nombre del jugador (del juego)
    - amount: puntos enteros (se guarda como TOTAL del día)
    - day: opcional ('mon'..'sat' o abreviatura ES). Si None, usa el día de juego actual.
    - ref_date: opcional (date/datetime). Si se provee, esa fecha define la semana de juego destino.
    Reglas:
      * El evento VS corre de lun–sáb. El domingo puede registrar para lun–sáb de la semana que finaliza ese mismo domingo.
      * El lunes aún puede registrar para la semana pasada (cierre), pero nunca para futuro.
      * Siempre se registra en la semana ISO del calendario del juego derivada de ref_date (si se pasa) o del "ahora".
    Devuelve (week_key, yyyymmdd_del_registro, total_del_dia)
    """
    if not isinstance(amount, int):
        raise ValueError("amount must be integer")

    state = _load()
    _ensure_points(state)

    # Base temporal: ahora o ref_date (si viene)
    if ref_date is None:
        now = datetime.now(UTC)
    else:
        if isinstance(ref_date, datetime):
            now = ref_date.astimezone(UTC)
        else:
            now = datetime.combine(ref_date, time(0, 0, tzinfo=UTC))

    game_today = to_game_date(now)          # fecha en calendario del juego (corte 02:00 UTC)
    monday = _monday_of_game_week(game_today)

    # Determinar fecha efectiva
    if day:
        key = day.strip().lower()
        if key not in _DAY_OFFSETS:
            raise ValueError("day must be one of mon..sat (or lun..sab)")
        offset = _DAY_OFFSETS[key]
        target = monday + timedelta(days=offset)
    else:
        # usar el día de juego base (derivado de now/ref_date)
        target = game_today

    # Limitar a lun–sáb siempre (domingo no es día válido del VS)
    if target.isoweekday() == 7:
        raise ValueError("VS runs Mon–Sat; Sunday is not a valid VS day.")

    week_key = _iso_week_key(target)
    date_key = yyyymmdd_from_date(target)

    week_bucket = state["points"].setdefault(week_key, {})
    day_list: List[Dict[str, Any]] = week_bucket.setdefault(date_key, [])

    # Sobrescribir: eliminar registros previos equivalentes a este jugador (reglas lógicas)
    existing_display = None
    to_keep = []
    for e in day_list:
        ename = str(e.get("name", ""))
        if _names_equivalent(ename, name):
            existing_display = ename if existing_display is None else _pick_display_name(existing_display, ename)
            # omitimos este registro (lo reemplazaremos)
        else:
            to_keep.append(e)
    day_list[:] = to_keep

    display_name = existing_display or _collapse_spaces(name)

    # Insertar la nueva entrada como TOTAL del día
    day_list.append({"name": display_name, "points": int(amount)})

    _save(state)

    # CSV: fecha_dia,nombre_comandante,puntos (se guarda el total)
    dt_utc = datetime.combine(target, time(0, 0, tzinfo=UTC))
    append_registro(dt_utc, display_name, int(amount))

    return week_key, date_key, int(amount)

def weekly_summary(ref_date: datetime | date | None = None) -> Dict[str, Any]:
    """
    Devuelve un resumen de la semana del calendario de juego que contiene ref_date.
    Si ref_date es None, usa la semana actual.
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

    if ref_date is None:
        base_dt = datetime.now(UTC)
    else:
        if isinstance(ref_date, datetime):
            base_dt = ref_date.astimezone(UTC)
        else:
            base_dt = datetime.combine(ref_date, time(0, 0, tzinfo=UTC))

    game_today = to_game_date(base_dt)
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

        # Consolida duplicados obvios del MISMO día (case/espacios/typo ASCII leve).
        per_day_merged: Dict[str, int] = {}
        per_day_display: Dict[str, str] = {}  # clave interna -> display consolidado

        for e in entries:
            raw_name = str(e.get("name", ""))
            pts = int(e.get("points", 0))

            hit_key = None
            for k in per_day_display.keys():
                if _names_equivalent(k, raw_name):
                    hit_key = k
                    break
            if hit_key is None:
                per_day_display[raw_name] = _collapse_spaces(raw_name)
                per_day_merged[raw_name] = pts
            else:
                new_disp = _pick_display_name(per_day_display[hit_key], raw_name)
                if new_disp != per_day_display[hit_key]:
                    per_day_display[hit_key] = new_disp
                per_day_merged[hit_key] = per_day_merged.get(hit_key, 0) + pts

        # elegibles del día (usando displays consolidados)
        eligibles_by_day[dk] = [
            per_day_display[k]
            for k, v in per_day_merged.items()
            if int(v) >= THRESHOLD
        ]

        # acumular para promedios por jugador (fusión a nivel de semana)
        for k, v in per_day_merged.items():
            disp = per_day_display[k]
            hit_week = None
            for wk in list(sums.keys()):
                if _names_equivalent(wk, disp):
                    hit_week = wk
                    break
            if hit_week is None:
                sums[disp] = int(v)
            else:
                new_disp = _pick_display_name(hit_week, disp)
                if new_disp != hit_week:
                    sums[new_disp] = sums.pop(hit_week)
                    if hit_week in counts:
                        counts[new_disp] = counts.pop(hit_week)
                    hit_week = new_disp
                sums[hit_week] = sums.get(hit_week, 0) + int(v)

            # contamos el día si tuvo registro (para referencia); el promedio final divide entre 6 fijos
            counts[disp] = counts.get(disp, 0) + 1

    # Promedios sobre 6 días fijos (Mon–Sat). Días sin registro cuentan como 0.
    if sums:
        averages = {n: (sums[n] / 6.0) for n in sums.keys()}
    else:
        averages = {}

    return {
        "week": week_key,
        "days": days,
        "eligibles_by_day": eligibles_by_day,
        "averages": averages,
    }
