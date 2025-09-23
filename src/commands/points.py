# ===============================
# src/commands/points.py
# ===============================
import discord
from discord import app_commands
import logging
from datetime import date, datetime

from ..utils.date_utils import (
    now_utc,
    to_game_date,
    from_game_date,
    game_date_for_abbrev_this_week,
    is_game_mon_to_sat,
)
from ..storage import register_points

logger = logging.getLogger(__name__)

_DAY_KEY_FROM_WEEKDAY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat"}

@app_commands.command(name="points", description="Register VS points for the current ISO week (game-day model)")
@app_commands.describe(name="In-game player name", amount="Points (integer)", day="Optional: mon|tue|wed|thu|fri|sat")
async def points(interaction: discord.Interaction, name: str, amount: int, day: str | None = None):
    try:
        name = name.strip()

        # Resolver la fecha/día efectivo según la lógica actual
        if day:
            dt = game_date_for_abbrev_this_week(day, now_utc())
            if not dt:
                return await interaction.response.send_message(
                    "Invalid day. Use: mon, tue, wed, thu, fri, sat.", ephemeral=True
                )
            when = dt
        else:
            gd = to_game_date(now_utc())
            when = from_game_date(gd)

        # Normalizar: si alguna rama devuelve datetime, convertir a date
        if isinstance(when, datetime):
            when = when.date()

        if not is_game_mon_to_sat(when):
            return await interaction.response.send_message(
                "VS runs **Monday–Saturday** (game-day). Choose a valid day.", ephemeral=True
            )

        # Convertir 'when' a clave de día que espera storage.register_points
        weekday = when.weekday()  # 0=Monday ... 6=Sunday
        if weekday == 6:
            return await interaction.response.send_message(
                "VS runs **Mon–Sat**; Sunday is not a valid VS day.", ephemeral=True
            )
        day_key = _DAY_KEY_FROM_WEEKDAY[weekday]

        # Llamar a storage.register_points con la firma real (sobrescribe el total del día)
        week_key, date_key, player_total_today = register_points(name=name, amount=amount, day=day_key)

        # Mensaje de confirmación
        pretty_day = when.strftime('%A %d/%m')
        msg = (
            f"✓ {name}: {player_total_today:,} registered for **{pretty_day}** (game-day total)."
        )

        if not interaction.response.is_done():
            await interaction.response.send_message(msg)
        else:
            await interaction.followup.send(msg)

    except Exception as e:
        logger.exception("Error in /points for %s", name if 'name' in locals() else '?')
        err = f"❌ Error: {e}"
        if not interaction.response.is_done():
            await interaction.response.send_message(err, ephemeral=True)
        else:
            await interaction.followup.send(err, ephemeral=True)
