# ===============================
# src/commands/draw.py  (W and D)
# ===============================
import random
import os, csv
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone, time, date
from ..config import ROLE_ADMIN, ROLE_OFFICIAL, THRESHOLD
from ..utils.date_utils import (
    now_utc,
    to_game_date,
    from_game_date,
    yyyymmdd_from_date,
    is_game_mon_to_fri,
    game_week_monfri,
)
from ..utils.csv_utils import append_sorteo
from ..storage import weekly_summary, get_train_config

UTC = timezone.utc


def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)


# ---------- helper: exclude drivers from pool ----------
def _exclude_train_drivers(pool: list[str]) -> list[str]:
    train_cfg = get_train_config()
    drivers = {d.lower() for d in train_cfg.get("drivers", []) if d and d.strip()}
    return [p for p in pool if p.lower() not in drivers]


@app_commands.command(name="draw", description="Alliance draws: D (daily) or W (weekly)")
@app_commands.describe(kind="D = daily (uses previous game-day), W = weekly (after event ends)")
@app_commands.choices(kind=[
    app_commands.Choice(name="W (weekly)", value="W"),
    app_commands.Choice(name="D (daily)", value="D"),
])
async def draw(interaction: discord.Interaction, kind: app_commands.Choice[str]):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

    if kind.value == "D":
        return await draw_d(interaction)
    else:
        return await draw_w(interaction)

def _parse_pipe_kv(detail: str) -> dict[str, str]:
    # "W|for:YYYYMMDD|passenger:Foo Bar|backups:A,B" -> {"for":"...","passenger":"...","backups":"A,B"}
    s = detail or ""
    if "|" in s and (s.startswith("W|") or s.startswith("D|") or s.startswith("weekend|")):
        s = s.split("|", 1)[1]
    out = {}
    for part in s.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out

def _exclude_last_week_W_passengers(target_week_monday_real: date) -> set[str]:
    """
    Lee el CSV de la semana inmediatamente anterior (el del domingo previo)
    y devuelve los nombres que salieron como passenger en líneas tipo 'W'.
    """
    from datetime import datetime, timezone, timedelta
    from ..utils.csv_utils import week_csv_names
    UTC = timezone.utc

    prev_sunday_real = target_week_monday_real - timedelta(days=1)  # domingo anterior
    csv_path = week_csv_names(datetime(prev_sunday_real.year, prev_sunday_real.month, prev_sunday_real.day, tzinfo=UTC))["sorteos"]
    out: set[str] = set()
    if not csv_path or not os.path.exists(csv_path):
        return out
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("tipo") or "").strip().upper() != "W":
                    continue
                kv = _parse_pipe_kv(row.get("detalle") or "")
                p = (kv.get("passenger") or "").strip()
                if p:
                    out.add(p)
    except Exception:
        pass
    return out

# ---------- Draw D (daily) — previous game-day elegibles → next assignment ----------
async def draw_d(interaction: discord.Interaction):
    now_dt = now_utc()
    current_gd = to_game_date(now_dt)
    base_gd = current_gd - timedelta(days=1)

    base_wd = base_gd.isoweekday()
    if base_wd == 7:
        return await interaction.response.send_message(
            "**Draw D** cannot be run based on game Sunday.", ephemeral=True
        )

    week_dt = from_game_date(base_gd)
    summary = weekly_summary()

    day_key = yyyymmdd_from_date(base_gd)
    eligibles = list(set(summary.get("eligibles_by_day", {}).get(day_key, [])))

    # 🚫 excluir nombres de train
    eligibles = _exclude_train_drivers(eligibles)

    if not eligibles:
        return await interaction.response.send_message("No eligibles (≥ 7.2M) in the previous game-day.")

    if base_wd == 6:  # Saturday
        applies_for_gd = base_gd + timedelta(days=2)  # Monday
    else:
        applies_for_gd = base_gd + timedelta(days=1)  # next day

    random.shuffle(eligibles)
    passenger = eligibles[0]
    backups = eligibles[1:3]

    detail = f"D|for:{yyyymmdd_from_date(applies_for_gd)}|passenger:{passenger}|backups:{','.join(backups)}"

    if isinstance(week_dt, datetime):
        week_dt_dt = week_dt
    else:
        week_dt_dt = datetime.combine(week_dt, time(0, 0, tzinfo=UTC))

    append_sorteo(week_dt_dt, "D", detail)

    human_day = from_game_date(applies_for_gd)
    await interaction.response.send_message(
        f"🎲 **Draw D** (based on **{base_gd}** → applies **{human_day.strftime('%A %d/%m')}**):\n"
        f"• Passenger: **{passenger}**\n"
        f"• Backups: {', '.join(f'**{b}**' for b in backups)}"
    )

# ---------- Draw W (weekly) — averages Mon–Sat, after event ends (Sun) or Monday grace ----------
async def draw_w(interaction: discord.Interaction):
    now_dt = now_utc()
    current_gd = to_game_date(now_dt)
    wd = current_gd.isoweekday()  # 1=Mon ... 7=Sun

    # Caso A: Domingo → usar la semana que terminó ese día y asignar para la siguiente semana
    if wd == 7:
        ref_gd_for_summary = current_gd
        target_week_start = from_game_date(current_gd) + timedelta(weeks=1)

    # Caso B: Lunes (día de gracia) → usar la semana anterior y asignar para esta semana
    elif wd == 1:
        ref_gd_for_summary = current_gd - timedelta(days=1)
        target_week_start = from_game_date(current_gd)

    # Cualquier otro día → rechazar
    else:
        return await interaction.response.send_message(
            "**Draw W** can only be executed **after the event ends** (game Sunday) or on **game Monday** as a grace day.",
            ephemeral=True,
        )

    # Obtener resumen de la semana de referencia
    summary = weekly_summary(ref_gd_for_summary)
    pool = [name for name, avg in summary.get("averages", {}).items() if avg >= THRESHOLD]

    # 🚫 excluir nombres de train
    pool = _exclude_train_drivers(pool)

    if len(pool) < 5:
        return await interaction.response.send_message("Not enough average-eligibles (≥ 7.2M) to assign 5 passengers.")

    # Días destino (Lun–Vie)
    next_week_days = game_week_monfri(target_week_start)

    # 🚫 excluir PASAJEROS que ya salieron en el W de la semana anterior
    target_week_monday_real = target_week_start  # ya es real-world Monday para la semana destino
    exclude_prev_w = _exclude_last_week_W_passengers(target_week_monday_real)
    pool = [n for n in pool if n not in exclude_prev_w]

    if len(pool) < 5:
        return await interaction.response.send_message(
            "Not enough average-eligibles after excluding last week's W passengers (need 5)."
        )

    random.shuffle(pool)
    picks = []
    available = pool[:]
    for i in range(5):
        passenger = available.pop(0)
        backups = []
        if available: backups.append(available.pop(0))
        if available: backups.append(available.pop(0))
        picks.append({"day": next_week_days[i], "passenger": passenger, "backups": backups})

    for p in picks:
        detail = f"W|for:{p['day'].strftime('%Y%m%d')}|passenger:{p['passenger']}|backups:{','.join(p['backups'])}"
        append_sorteo(now_dt, "W", detail)

    lines = "\n".join(
        f"• {p['day'].strftime('%A %d/%m')}: passenger **{p['passenger']}**, backups {', '.join(f'**{b}**' for b in p['backups'])}"
        for p in picks
    )
    when_txt = "for next week Mon–Fri" if wd == 7 else "for this week Mon–Fri"
    await interaction.response.send_message(f"🎲 **Draw W** ({when_txt}):\n{lines}")
