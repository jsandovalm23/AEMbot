# ===============================
# src/commands/train.py
# ===============================
# /train_show modes:
#   - (sin parámetros) → semana actual (Mon–Sun)
#   - today            → solo hoy
#   - next             → solo mañana
#   - full             → dos semanas (Mon–Sun × 2)
#
# Incluye fines de semana:
#  - Pasajero y conductor del fin de semana se leen de CSV tipo "weekend"
#  - Si no hay registro weekend, se muestra "Pending"
#
from __future__ import annotations
import discord
from discord import app_commands
from datetime import timedelta, date, datetime, timezone
from typing import Optional, Tuple, Dict

from ..config import ROLE_ADMIN, ROLE_OFFICIAL
from ..storage import set_train_config, get_train_config
from ..utils.date_utils import to_game_date, from_game_date, now_utc
from ..utils.train_utils import driver_for_day, read_draw_for_date
from ..utils.csv_utils import week_csv_names

UTC = timezone.utc

# --------------------------------
# permisos (Admin/Official pueden editar)
# --------------------------------
def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    # ROLE_* pueden ser listas o strings separados por coma; manejamos ambos
    def _to_list(v):
        if isinstance(v, (list, tuple)): return [str(x).strip() for x in v if str(x).strip()]
        if isinstance(v, str): return [s.strip() for s in v.split(",") if s.strip()]
        return []
    allow = set(_to_list(ROLE_ADMIN) + _to_list(ROLE_OFFICIAL))
    return any(n in allow for n in names)

# -----------------------------
# utilidades para /train_show
# -----------------------------
_LABELS_EN = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def _monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday=0

def _utc_from_date(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)

def _csv_path_for(dt_utc: datetime) -> Optional[str]:
    names = week_csv_names(dt_utc)
    p = names.get("sorteos")
    return p

def _parse_pipe_kv(detail: str) -> Dict[str, str]:
    # Convierte "weekend|for:YYYYMMDD|driver:...|driver_backup:...|passenger:...|passenger_backups:A,B"
    # a dict {"for": "...", "driver": "...", "driver_backup": "...", "passenger": "...", "passenger_backups": "..."}
    s = detail or ""
    if s.startswith(("W|", "D|", "weekend|")):
        s = s.split("|", 1)[1] if "|" in s else ""
    out: Dict[str, str] = {}
    for part in s.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out

def _prev_sunday_ref(d: date) -> datetime:
    # igual que la lógica del bot: CSV de la semana previa se resuelve con el domingo anterior
    # Sunday inmediatamente anterior al lunes de la semana de `d`
    monday = d - timedelta(days=d.weekday())  # Monday=0
    prev_sunday = monday - timedelta(days=1)
    return _utc_from_date(prev_sunday)

def _next_sunday_ref(d: date) -> datetime:
    # Sunday al final de la semana de `d` (Monday=0)
    monday = d - timedelta(days=d.weekday())
    next_sunday = monday + timedelta(days=6)
    return _utc_from_date(next_sunday)

def _this_week_ref(d: date) -> datetime:
    return _utc_from_date(d)

def _read_weekend_for_date(real_day: date) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Lee un registro 'weekend' para 'real_day' (sábado o domingo).
    Devuelve: (driver, driver_backup, passenger, passenger_backup_1)
    Si no encuentra, regresa (None, None, None, None)
    """
    target = real_day.strftime("%Y%m%d")
    # El bot escribe weekend en la semana de trabajo vigente (la del domingo previo),
    # así que buscamos primero en el CSV del domingo previo.
    for ref in (_prev_sunday_ref(real_day), _this_week_ref(real_day)):
        path = _csv_path_for(ref)
        if not path:
            continue
        if not __import__('os').path.exists(path):
            continue
        try:
            import csv
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row.get("tipo") or "").strip().lower() != "weekend":
                        continue
                    kv = _parse_pipe_kv(row.get("detalle") or "")
                    if kv.get("for") == target:
                        drv = kv.get("driver")
                        drv_b = kv.get("driver_backup")
                        pax = kv.get("passenger")
                        pax_b1 = None
                        backs = kv.get("passenger_backups") or ""
                        if backs:
                            first = (backs.split(",")[0] or "").strip()
                            pax_b1 = first or None
                        return drv or None, drv_b or None, pax or None, pax_b1
        except Exception:
            continue
    return (None, None, None, None)

def _read_weekday_from_csv(real_day: date) -> Tuple[Optional[str], Optional[str]]:
    """
    Fallback para Mon–Fri: lee CSV de sorteos y encuentra pasajero/backups para 'real_day'
    buscando entradas tipo W/D con for:YYYYMMDD.
    Orden de búsqueda:
      1) CSV del domingo siguiente a 'real_day'  (propio de Draw W)
      2) CSV del domingo previo                   (por compatibilidad)
      3) CSV "de esta semana"                     (compatibilidad adicional)
    Devuelve: (passenger, first_backup) o (None, None).
    """
    target = real_day.strftime("%Y%m%d")
    for ref in (_next_sunday_ref(real_day), _prev_sunday_ref(real_day), _this_week_ref(real_day)):
        path = _csv_path_for(ref)
        if not path:
            continue
        if not __import__('os').path.exists(path):
            continue
        try:
            import csv
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    tipo = (row.get("tipo") or "").strip().lower()
                    if tipo not in ("w", "d"):
                        continue
                    kv = _parse_pipe_kv(row.get("detalle") or "")
                    if kv.get("for") == target:
                        pax = (kv.get("passenger") or "").strip()
                        backs = (kv.get("backups") or kv.get("passenger_backups") or "").strip()
                        b1 = None
                        if backs:
                            first = (backs.split(",")[0] or "").strip()
                            b1 = first or None
                        return pax or None, b1
        except Exception:
            continue
    return (None, None)

def _format_day_line(day_real: date, driver: Optional[str], pax: Optional[str], bkp: Optional[str], weekend=False,
                     drv_wk: Optional[str]=None, pax_wk: Optional[str]=None) -> str:
    # driver/pax “Pending” si no hay
    dlabel = _LABELS_EN[day_real.isoweekday() - 1]
    dshort = f"{dlabel} {day_real.strftime('%d/%m')}"
    drv_txt = (driver.strip() if driver else "Pending")
    if weekend and drv_wk:
        # si viene de weekend CSV, ya es definitivo
        drv_txt = drv_wk.strip() or "Pending"
    pax_txt = (pax.strip() if pax else "Pending")
    if weekend and pax_wk:
        pax_txt = pax_wk.strip() or "Pending"
    bkp_txt = f" (_{bkp}_)" if bkp else ""
    return f"• {dshort} | Driver = {drv_txt if drv_txt == 'Pending' else f'**{drv_txt}**'} — VIP = {pax_txt if pax_txt == 'Pending' else f'**{pax_txt}**'}{bkp_txt}"

def _build_week_block(drivers: list[str], anchor_base: date, week_monday_game: date) -> str:
    # Ancla para rotación
    # 'anchor_base' ya viene como date (no ISO); es el mismo para ambos bloques (A/B)
    header = f"**Week starting {from_game_date(week_monday_game).strftime('%Y-%m-%d')}**"
    lines = [header]

    # Mon..Fri (rotación + pasajeros D/W)
    for i in range(5):
        day_game = week_monday_game + timedelta(days=i)
        day_real = from_game_date(day_game)
        # conductor (rotación)
        drv = driver_for_day(drivers, anchor_base, day_game)
        drv = drv if (drv and isinstance(drv, str) and drv.strip()) else "Pending"
        # pasajero desde CSV (D/W por lógica de train_utils.read_draw_for_date)
        pax, bkp = read_draw_for_date(day_real)
        if not pax:
            # Fallback: buscar directamente en CSV considerando Draw W (domingo siguiente)
            pax, bkp = _read_weekday_from_csv(day_real)
        lines.append(_format_day_line(day_real, drv, pax, bkp))


    # Sat/Sun (desde weekend CSV si existe)
    for i in (5, 6):
        day_game = week_monday_game + timedelta(days=i)
        day_real = from_game_date(day_game)
        # En fin de semana no hay rotación de conductor; si existe weekend CSV lo toma
        drv_wk, drv_bk_wk, pax_wk, pax_b1_wk = _read_weekend_for_date(day_real)
        # Mostrar también backup de pasajero (el primero)
        bkp_to_show = pax_b1_wk
        lines.append(
            _format_day_line(
                day_real,
                None,               # sin rotación de driver en weekend
                None,               # pax se toma de weekend CSV
                bkp_to_show,        # primer backup de pax (si hay)
                weekend=True,
                drv_wk=drv_wk,
                pax_wk=pax_wk,
            )
        )
    return "\n".join(lines)

# --------------------------------
# comandos para configuración
# --------------------------------

@app_commands.command(
    name="train_set_drivers",
    description="Set 10 drivers for a 2-week rotation (w1mon..w2fri)"
)
@app_commands.describe(
    w1mon="Week1 Monday", w1tue="Week1 Tuesday", w1wed="Week1 Wednesday", w1thu="Week1 Thursday", w1fri="Week1 Friday",
    w2mon="Week2 Monday", w2tue="Week2 Tuesday", w2wed="Week2 Wednesday", w2thu="Week2 Thursday", w2fri="Week2 Friday",
)
async def train_set_drivers(
    interaction: discord.Interaction,
    w1mon: str, w1tue: str, w1wed: str, w1thu: str, w1fri: str,
    w2mon: str, w2tue: str, w2wed: str, w2thu: str, w2fri: str,
):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)

    drivers = [w1mon, w1tue, w1wed, w1thu, w1fri, w2mon, w2tue, w2wed, w2thu, w2fri]
    set_train_config(drivers=drivers)

    # Eco con etiquetas 1Mon..2Fri
    labels = ["1Mon","1Tue","1Wed","1Thu","1Fri","2Mon","2Tue","2Wed","2Thu","2Fri"]
    lines = "\n".join(f"{labels[i]} — {drivers[i] or 'Pending'}" for i in range(10))
    await interaction.response.send_message(
        "✅ Train drivers updated:\n" + lines
    )

@app_commands.command(name="train_set_anchor", description="Set rotation anchor Monday (YYYYMMDD of a Monday)")
async def train_set_anchor(interaction: discord.Interaction, monday_yyyymmdd: str):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    if len(monday_yyyymmdd) != 8 or not monday_yyyymmdd.isdigit():
        return await interaction.response.send_message("Use YYYYMMDD.", ephemeral=True)
    y,m,d = int(monday_yyyymmdd[:4]), int(monday_yyyymmdd[4:6]), int(monday_yyyymmdd[6:])
    try:
        md = date(y,m,d)
    except Exception:
        return await interaction.response.send_message("Invalid date.", ephemeral=True)
    if md.isoweekday() != 1:
        return await interaction.response.send_message("Anchor must be a Monday.", ephemeral=True)
    set_train_config(anchor_monday_iso=md.isoformat())
    await interaction.response.send_message(f"✅ Train anchor set to {md.isoformat()}.")

@app_commands.command(name="train_mode", description="Toggle Monday full-week post: on/off")
@app_commands.choices(mode=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
])
async def train_mode(interaction: discord.Interaction, mode: app_commands.Choice[str]):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    set_train_config(post_full_on_monday=(mode.value=="on"))
    await interaction.response.send_message(f"✅ Weekly post on Monday: {mode.value}")

# --------------------------------
# /train_show con modos
# --------------------------------
@app_commands.command(name="train_show", description="Show train lineup")
@app_commands.describe(mode="current | today | next | full")
@app_commands.choices(mode=[
    app_commands.Choice(name="current", value="current"),
    app_commands.Choice(name="today", value="today"),
    app_commands.Choice(name="next", value="next"),
    app_commands.Choice(name="full", value="full"),
])
async def train_show(interaction: discord.Interaction, mode: app_commands.Choice[str] | None = None):
    cfg = get_train_config()
    drivers = cfg.get("drivers") or []
    anchor_iso = cfg.get("anchor_monday")

    # Día de juego actual (cambia 02:00 UTC)
    game_today = to_game_date(now_utc())
    week_monday_game = game_today - timedelta(days=(game_today.isoweekday() - 1))

    # Anchor fijo para ambos bloques:
    anchor_base = date.fromisoformat(anchor_iso) if anchor_iso else week_monday_game

    # ----- modos -----
    chosen = (mode.value if isinstance(mode, app_commands.Choice) else "current").lower()

    if chosen == "today":
        # Solo el día actual (incluye fin de semana)
        day_game = game_today
        day_real = from_game_date(day_game)
        wd = day_game.isoweekday()
        if 1 <= wd <= 5:
            drv = driver_for_day(drivers, anchor_base, day_game)
            drv = drv if (drv and drv.strip()) else "Pending"
            pax, bkp = read_draw_for_date(day_real)
            if not pax:
                # Fallback: considerar Draw W (CSV del domingo siguiente)
                pax, bkp = _read_weekday_from_csv(day_real)
            line = _format_day_line(day_real, drv, pax, bkp)
        else:
            drv_wk, drv_bk_wk, pax_wk, pax_b1_wk = _read_weekend_for_date(day_real)
            line = _format_day_line(day_real, None, None, pax_b1_wk, weekend=True,
                                    drv_wk=drv_wk, pax_wk=pax_wk)
        return await interaction.response.send_message("📅 **Train — Today**\n" + line)

    if chosen == "next":
        # Solo mañana
        day_game = game_today + timedelta(days=1)
        day_real = from_game_date(day_game)
        wd = day_game.isoweekday()
        if 1 <= wd <= 5:
            # usar el lunes de la semana del día consultado si no hay anchor
            anchor_for_next = date.fromisoformat(anchor_iso) if anchor_iso else _monday_of(day_game)
            drv = driver_for_day(drivers, anchor_for_next, day_game)
            drv = drv if (drv and drv.strip()) else "Pending"
            pax, bkp = read_draw_for_date(day_real)
            if not pax:
                # Fallback: considerar Draw W (CSV del domingo siguiente)
                pax, bkp = _read_weekday_from_csv(day_real)
            line = _format_day_line(day_real, drv, pax, bkp)
        else:
            drv_wk, drv_bk_wk, pax_wk, pax_b1_wk = _read_weekend_for_date(day_real)
            line = _format_day_line(day_real, None, None, pax_b1_wk, weekend=True,
                                    drv_wk=drv_wk, pax_wk=pax_wk)
        return await interaction.response.send_message("📅 **Train — Tomorrow**\n" + line)

    if chosen == "full":
        # Dos semanas (Mon–Sun × 2)
        block1 = _build_week_block(drivers, anchor_base, week_monday_game)
        block2 = _build_week_block(drivers, anchor_base, week_monday_game + timedelta(days=7))
        msg = "📅 **Train — 2-Week Lineup (Mon–Sun × 2)**\n" + block1 + "\n\n" + block2
        return await interaction.response.send_message(msg)

    # default: "current" → semana actual (Mon–Sun)
    block = _build_week_block(drivers, anchor_base, week_monday_game)
    msg = "📅 **Train — This Week (Mon–Sun)**\n" + block
    await interaction.response.send_message(msg)
