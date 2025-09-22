# ===============================
# src/commands/reset.py
# ===============================
import os
import json
import discord
from discord import app_commands
from ..config import DATA_DIR, ROLE_ADMIN, ROLE_OFFICIAL
from ..utils.date_utils import now_utc, iso_week_key


def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)


@app_commands.command(name="reset", description="Clear in-memory records of the current week (CSV files are preserved)")
async def reset(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    p = os.path.join(DATA_DIR, "data.json")
    if os.path.exists(p):
        with open(p, "r", encoding="utf-8") as f:
            state = json.load(f)
        wk = iso_week_key(now_utc())
        if state.get("weeks") and state["weeks"].get(wk):
            del state["weeks"][wk]
            with open(p, "w", encoding="utf-8") as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
    await interaction.response.send_message("✅ Cleared in-memory records for the current week. (CSVs not touched)")
