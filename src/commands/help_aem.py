# ===============================
# src/commands/help_aem.py
# ===============================
# src/commands/help_aem.py — display help/usage summary inside Discord (updated)
import discord
from discord import app_commands

HELP_TEXT = """
📖 **Alliance Events Management Bot — Help**

**Points & Status**
• `/points <name> <amount> [day]` — register VS points
• `/status_vs` — show daily/weekly summary
• `/reset` — clear this week (Admin/Official)

**Draws & Roles**
• `/draw <D|W>` — Daily (yesterday→today) / Weekly (Mon–Fri)
• `/weekend_roles` — Sat+Sun driver/passenger assignments
• `/redo_d <YYYYMMDD>` / `/redo_w <YYYY-WW>` — redo draws

**CSVs & Weeks**
• `/csv kind:<records|draws|both> [week]` — export CSVs
• `/weeks` — list available weeks

**Schedules (Events)**
• `/mg <yyyymmdd> <HHmm> [<HHmm_weekend>]` — Marshall’s Guard (repeats 2d)
• `/zs <yyyymmdd> <HHmm> [<HHmm_weekend>]` — Zombie Siege (repeats 3d)
• `/mg_status` — show next 5 occurrences (MG)
• `/zs_status` — show next 5 occurrences (ZS)

**Automation**
• `/auto <feature> <on|off>` — toggle features at runtime

**Train**
• `/train_set_drivers <d1..d10>` — set 10 drivers
• `/train_set_anchor <YYYYMMDD>` — anchor Monday
• `/train_mode <on|off>` — weekly full post toggle
• `/train_show` — show this week’s lineup

**Time / Server Time**
• `/time_lw` — show current UTC, server-day start (00:00 server), and game-day key
• `/time_lw <yyyymmdd> <HHmm> <Country>` — convert a **server-time** moment to **all time zones** in the country

**Info**
• `/help_aem` — show this help

ℹ️ Notes:
- Server day cutover: 02:00 UTC (00:00 server)
- Roles required: R5/R4 for sensitive commands
- Auto tasks: Draw D (00:30 daily if no W), Draw W (Sun 00:30 if week complete), VS reminder (23:45 daily), Train (01:00 + 14:30)
"""

@app_commands.command(name="help_aem", description="Show help and command usage for AEM bot")
async def help_aem(interaction: discord.Interaction):
    await interaction.response.send_message(HELP_TEXT, ephemeral=True)