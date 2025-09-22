# ===============================
# src/commands/reset_all.py
# ===============================
# /reset_all — wipe all persisted data (data.json). Admin/Official only.
from __future__ import annotations
import os, json
import discord
from discord import app_commands
from ..config import ROLE_ADMIN, ROLE_OFFICIAL, DATA_DIR

# data.json path (mismo lugar que usa storage)
DATA_JSON = os.path.join(DATA_DIR, "data.json")

def _to_role_list(v) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []

def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    allow = set(_to_role_list(ROLE_ADMIN) + _to_role_list(ROLE_OFFICIAL))
    return any(n in allow for n in names)

@app_commands.command(
    name="reset_all",
    description="Wipe all bot data (data.json) — Admin/Official only."
)
@app_commands.describe(confirm="Type YES to confirm")
async def reset_all(interaction: discord.Interaction, confirm: str):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)

    if confirm != "YES":
        return await interaction.response.send_message(
            "⚠️ This will erase all data. Re-run `/reset_all` with `confirm: YES` to proceed.",
            ephemeral=True
        )

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DATA_JSON, "w", encoding="utf-8") as f:
        json.dump({}, f)

    await interaction.response.send_message("🧹 Done. All data cleared (data.json reset to {}).", ephemeral=True)
