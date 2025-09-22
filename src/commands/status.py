# ===============================
# src/commands/status.py
# ===============================
import discord
from discord import app_commands
from ..storage import weekly_summary
from ..utils.date_utils import now_utc


@app_commands.command(name="status_vs", description="Show daily and weekly summary for the current ISO week (UTC/game-day)")
async def status(interaction: discord.Interaction):
    s = weekly_summary()
    per_day = s.get("perDay", {})
    averages = s.get("averages", {})
    days_lines = "\n".join(
        f"• {d}: total {v['total']:,} | eligibles ({len(v['eligible'])}): {', '.join(v['eligible'])}"
        for d, v in sorted(per_day.items(), key=lambda x: x[0])
    ) or "—"
    avg_lines = "\n".join(
        f"• {n}: avg {v['average']:,} ({v['daysCount']} days, ≥7.2M on {v['hitDays']})"
        for n, v in sorted(averages.items(), key=lambda x: x[1]['average'], reverse=True)
    ) or "—"
    await interaction.response.send_message(
        f"📊 **Status week {s['week']}**\n**By day:**\n{days_lines}\n\n**Averages Mon–Sat:**\n{avg_lines}"
    )
