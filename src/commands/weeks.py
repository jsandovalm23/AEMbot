# ===============================
# src/commands/weeks.py
# ===============================
import discord
from discord import app_commands
from ..utils.csv_utils import list_weeks_in_folder


@app_commands.command(name="weeks", description="List detected weeks (YYYY-WW / Sunday YYYYMMDD) and CSV filenames")
async def weeks(interaction: discord.Interaction):
    weeks = list_weeks_in_folder()
    if not weeks:
        return await interaction.response.send_message("No weeks detected yet.")
    lines = "\n".join(
        f"• {w['week']} | Sunday {w['sunday']} | {w.get('registros') or '—'} | {w.get('sorteos') or '—'}"
        for w in weeks
    )
    await interaction.response.send_message(f"🗂 **Detected weeks**\n{lines}")
