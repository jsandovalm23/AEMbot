# ===============================
# src/commands/points.py
# ===============================
import discord
from discord import app_commands
from ..utils.date_utils import (
    now_utc,
    to_game_date,
    from_game_date,
    game_date_for_abbrev_this_week,
    is_game_mon_to_sat,
)
from ..storage import register_points


@app_commands.command(name="points", description="Register VS points for the current ISO week (game-day model)")
@app_commands.describe(name="In-game player name", amount="Points (integer)", day="Optional: mon|tue|wed|thu|fri|sat")
async def points(interaction: discord.Interaction, name: str, amount: int, day: str | None = None):
    name = name.strip()
    when = None
    if day:
        dt = game_date_for_abbrev_this_week(day, now_utc())
        if not dt:
            return await interaction.response.send_message("Invalid day. Use: mon, tue, wed, thu, fri, sat.", ephemeral=True)
        when = dt
    else:
        gd = to_game_date(now_utc())
        when = from_game_date(gd)

    if not is_game_mon_to_sat(when.date()):
        return await interaction.response.send_message("VS runs **Monday–Saturday** (game-day). Choose a valid day.", ephemeral=True)

    res = register_points(commander=name, points=amount, date=when)
    await interaction.response.send_message(
        f"✓ {name}: +{amount:,} registered for **{when.strftime('%A %d/%m')}** (game-day). Day total: {res['total']:,}.")
