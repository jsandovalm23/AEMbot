# ===============================
# src/commands/redo.py
# ===============================
# src/commands/redo.py — redo daily/weekly draws (admin only)
import discord, csv, os
from discord import app_commands
from ..config import ROLE_ADMIN, ROLE_OFFICIAL
from ..utils.date_utils import from_game_date, to_game_date
from ..utils.csv_utils import week_csv_names


def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)


@app_commands.command(name="redo_d", description="Redo Draw D for a date (YYYYMMDD). Removes previous D for that date, then you can run /draw D.")
async def redo_d(interaction: discord.Interaction, yyyymmdd: str):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    if len(yyyymmdd) != 8:
        return await interaction.response.send_message("Use YYYYMMDD.", ephemeral=True)
    from datetime import date
    y,m,d = int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:])
    dt = date(y,m,d)
    week_dt = from_game_date(dt)
    names = week_csv_names(week_dt)
    path = names["sorteos"]
    if not os.path.exists(path):
        return await interaction.response.send_message("No draws exist for that week.", ephemeral=True)
    rows = []
    removed = 0
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if (row.get("tipo") or "").upper() == "D" and f"for:{yyyymmdd}" in (row.get("detalle") or ""):
                removed += 1
                continue
            rows.append(row)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fecha","semana","tipo","detalle"])
        writer.writeheader()
        writer.writerows(rows)
    await interaction.response.send_message(f"✅ Removed {removed} D entries for {yyyymmdd}. Now you can run /draw D.")


@app_commands.command(name="redo_w", description="Redo Draw W for an ISO week (YYYY-WW). Removes all W of that week.")
async def redo_w(interaction: discord.Interaction, iso_week: str):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    if len(iso_week) != 7 or iso_week[4] != '-':
        return await interaction.response.send_message("Use YYYY-WW.", ephemeral=True)
    # Find Sunday's CSV by scanning data dir
    import re
    from glob import glob
    sunday_csvs = glob(os.path.join("data", "Vs*_sorteos.csv"))
    pattern = re.compile(r"Vs(\d{8})_sorteos\\.csv$")
    removed = 0
    for p in sunday_csvs:
        m = pattern.search(p)
        if not m:
            continue
        # naive check: open and see if semana==iso_week appears
        keep_rows = []
        with open(p, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("semana") == iso_week) and (row.get("tipo") or "").upper() == "W":
                    removed += 1
                    continue
                keep_rows.append(row)
        if removed:
            with open(p, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["fecha","semana","tipo","detalle"])
                writer.writeheader()
                writer.writerows(keep_rows)
    await interaction.response.send_message(f"✅ Removed {removed} W entries for week {iso_week}.")
