# ===============================
# src/commands/auto.py
# ===============================
# src/commands/auto.py — enable/disable automation features at runtime
import discord
from discord import app_commands
from ..config import ROLE_ADMIN, ROLE_OFFICIAL
from ..storage import set_auto_toggle, get_auto_toggle


def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)


@app_commands.command(name="auto", description="Toggle automation: /auto <feature> <on|off>")
@app_commands.describe(feature="AUTO_DRAW_D | AUTO_DRAW_W | AUTO_VS_REMINDER | AUTO_TRAIN_POST")
@app_commands.choices(feature=[
    app_commands.Choice(name="AUTO_DRAW_D", value="AUTO_DRAW_D"),
    app_commands.Choice(name="AUTO_DRAW_W", value="AUTO_DRAW_W"),
    app_commands.Choice(name="AUTO_VS_REMINDER", value="AUTO_VS_REMINDER"),
    app_commands.Choice(name="AUTO_TRAIN_POST", value="AUTO_TRAIN_POST"),
])
@app_commands.choices(mode=[
    app_commands.Choice(name="on", value="on"),
    app_commands.Choice(name="off", value="off"),
])
async def auto(interaction: discord.Interaction, feature: app_commands.Choice[str], mode: app_commands.Choice[str]):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    set_auto_toggle(feature.value, mode.value == "on")
    await interaction.response.send_message(f"✅ {feature.value} set to {mode.value}")
