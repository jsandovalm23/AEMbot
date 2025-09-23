# ===============================
# src/commands/draw.py  (W and D)
# ===============================
import random
from datetime import datetime, timedelta, timezone, time
import discord
from discord import app_commands
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


# ---------- Draw W (weekly) — averages Mon–Sat, only after event ends ----------
async def draw_w(interaction: discord.Interaction):
    now_dt = now_utc()
    current_gd = to_game_date(now_dt)

    if current_gd.isoweekday() != 7:
        return await interaction.response.send_message(
            "**Draw W** can only be executed **after the event ends** (game Sunday).",
            ephemeral=True,
        )

    summary = weekly_summary()
    pool = [name for name, avg in summary.get("averages", {}).items() if avg >= THRESHOLD]

    # 🚫 excluir nombres de train
    pool = _exclude_train_drivers(pool)

    if len(pool) < 5:
        return await interaction.response.send_message("Not enough average-eligibles (≥ 7.2M) to assign 5 passengers.")

    next_week_days = game_week_monfri(from_game_date(current_gd) + timedelta(weeks=1))
    random.shuffle(pool)
    picks = []
    available = pool[:]
    for i in range(5):
        passenger = available.pop(0)
        backups = [available.pop(0)] if available else []
        if available:
            backups.append(available.pop(0))
        picks.append({"day": next_week_days[i], "passenger": passenger, "backups": backups})

    for p in picks:
        detail = f"W|for:{p['day'].strftime('%Y%m%d')}|passenger:{p['passenger']}|backups:{','.join(p['backups'])}"
        append_sorteo(now_dt, "W", detail)

    lines = "\n".join(
        f"• {p['day'].strftime('%A %d/%m')}: passenger **{p['passenger']}**, backups {', '.join(f'**{b}**' for b in p['backups'])}"
        for p in picks
    )
    await interaction.response.send_message(f"🎲 **Draw W** (for **next week Mon–Fri**):\n{lines}")
