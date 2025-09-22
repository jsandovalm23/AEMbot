# ===============================
# src/commands/csv_tools.py
# ===============================
import os
import discord
from discord import app_commands
from datetime import datetime, timedelta, timezone
from ..utils.csv_utils import week_csv_names
from ..config import ROLE_ADMIN, ROLE_OFFICIAL

def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)

@app_commands.command(name="csv", description="Attach CSV files for the current or a specific week")
@app_commands.describe(kind="records|draws|both", week="current|previous|YYYY-WW|YYYYMMDD (any date within the week)")
@app_commands.choices(kind=[
    app_commands.Choice(name="records", value="records"),
    app_commands.Choice(name="draws", value="draws"),
    app_commands.Choice(name="both", value="both"),
])
async def csv_tools(interaction: discord.Interaction, kind: app_commands.Choice[str], week: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)

    target_dt = _resolve_date(week)
    names = week_csv_names(target_dt)
    files = []
    if kind.value in ("records", "both") and os.path.exists(names["registros"]):
        files.append(discord.File(names["registros"]))
    if kind.value in ("draws", "both") and os.path.exists(names["sorteos"]):
        files.append(discord.File(names["sorteos"]))

    if not files:
        return await interaction.response.send_message(f"No CSVs for the week (Sunday {names['sunday']}).")
    await interaction.response.send_message(content=f"📎 CSVs for week (Sunday {names['sunday']})", files=files)

def _resolve_date(sw: str | None) -> datetime:
    today = datetime.now(timezone.utc)
    if not sw or sw == "current":
        return today
    if sw == "previous":
        return today - timedelta(weeks=1)
    if len(sw) == 7 and sw[4] == '-':  # YYYY-WW
        y, w = sw.split('-')
        y, w = int(y), int(w)
        return datetime.fromisocalendar(y, w, 1, tzinfo=timezone.utc)
    if len(sw) == 8 and sw.isdigit():  # YYYYMMDD
        return datetime.strptime(sw, "%Y%m%d").replace(tzinfo=timezone.utc)
    return today
