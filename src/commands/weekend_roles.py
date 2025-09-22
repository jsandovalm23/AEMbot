# ===============================
# src/commands/weekend_roles.py
# ===============================
import random, csv, os
import discord
from discord import app_commands
from datetime import timedelta
from ..config import ROLE_ADMIN, ROLE_OFFICIAL, THRESHOLD
from ..utils.date_utils import (
    now_utc,
    to_game_date,
    from_game_date,
    yyyymmdd_from_date,
    game_week_monfri,
)
from ..utils.csv_utils import append_sorteo, week_csv_names
from ..storage import weekly_summary


def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)


def _collect_mon_fri_assignments(write_week_ref_dt):
    """
    Lee del CSV de la *semana de escritura* (domingo de cierre actual) todas las
    asignaciones planificadas para Lun–Vie de la *semana siguiente* (for:YYYYMMDD),
    y devuelve un conjunto de nombres (passenger y backups) para excluirlos del fin de semana.
    """
    excluded = set()
    names = week_csv_names(write_week_ref_dt)
    path = names["sorteos"]
    if not os.path.exists(path):
        return excluded

    # Queremos Mon–Vie de la semana SIGUIENTE a write_week_ref_dt.
    next_week_ref_dt = write_week_ref_dt + timedelta(days=7)
    mon_fri_dates = {d.strftime("%Y%m%d") for d in game_week_monfri(next_week_ref_dt)}

    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            detalle = (row.get("detalle") or "").strip()
            try:
                parts = [p for p in detalle.split("|") if ":" in p]
                kv = {p.split(":", 1)[0]: p.split(":", 1)[1] for p in parts}
                for_date = kv.get("for")
                if for_date and for_date in mon_fri_dates:
                    # Excluir passenger y backups (ambos formatos: "backups" o "passenger_backups")
                    if "passenger" in kv and kv["passenger"]:
                        excluded.add(kv["passenger"])
                    if "backups" in kv and kv["backups"]:
                        for b in kv["backups"].split(","):
                            b = b.strip()
                            if b:
                                excluded.add(b)
                    if "passenger_backups" in kv and kv["passenger_backups"]:
                        for b in kv["passenger_backups"].split(","):
                            b = b.strip()
                            if b:
                                excluded.add(b)
            except Exception:
                continue
    return excluded


@app_commands.command(name="weekend_roles", description="Assign Driver+backup and Passenger+backups for both Saturday and Sunday (no params)")
async def weekend_roles(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("You don't have permission to use this command.", ephemeral=True)

    nowdt = now_utc()
    cur_gd = to_game_date(nowdt)

    # Semana de escritura = semana del domingo de cierre actual (p.ej. 2025-09-21)
    write_week_dt = from_game_date(cur_gd)

    # Pool de promedios de la semana que acaba de terminar (se calcula con write_week_dt)
    summary = weekly_summary(write_week_dt)
    averages = [(n, v.get("average", 0)) for n, v in summary.get("averages", {}).items() if v.get("average", 0) >= THRESHOLD]
    if len(averages) < 4:
        return await interaction.response.send_message("Need at least 4 average-eligibles to assign without repeats.", ephemeral=True)

    averages.sort(key=lambda x: x[1], reverse=True)
    top10 = [n for n, _ in averages[:10]]     # Para Driver
    avg_pool_all = [n for n, _ in averages]   # Para Passenger

    # Excluir Mon–Vie de la SEMANA SIGUIENTE (22–26) leyendo del mismo CSV (Vs<domingo actual>)
    excluded_mon_fri = _collect_mon_fri_assignments(write_week_dt)

    # Objetivos del fin de semana (Sábado y Domingo de la semana siguiente)
    # Calculados desde el game-day actual para obtener 6=Sat, 7=Sun de la semana en curso;
    # si hoy es domingo, offset=6 y 7 nos llevan al finde de la semana siguiente.
    targets = []
    for wd in (6, 7):  # Saturday, Sunday (game weekday)
        offset = wd - cur_gd.isoweekday()
        if offset <= 0:
            # Si es Dom (7), offset=0 -> es hoy; para tomar el próximo finde, avanzamos 7 días
            offset += 7
        target_gd = cur_gd + timedelta(days=offset)
        targets.append(target_gd)

    results = []
    for target_gd in targets:
        # Passenger del pool de promedios, excluyendo Mon–Vie ya asignados
        passenger_candidates = [n for n in avg_pool_all if n not in excluded_mon_fri]
        if not passenger_candidates:
            return await interaction.response.send_message("No available passenger candidates after excluding Mon–Fri selections.", ephemeral=True)
        random.shuffle(passenger_candidates)
        passenger = passenger_candidates.pop(0)
        passenger_backups = []
        if passenger_candidates:
            passenger_backups.append(passenger_candidates.pop(0))
        if passenger_candidates:
            passenger_backups.append(passenger_candidates.pop(0))

        # Driver del Top-10, distinto del passenger y sus backups (puede repetir con Mon–Vie)
        driver_pool = [n for n in top10 if n not in {passenger, *passenger_backups}]
        if len(driver_pool) < 2:
            return await interaction.response.send_message("Not enough distinct Top-10 candidates to assign driver and backup.", ephemeral=True)
        random.shuffle(driver_pool)
        driver = driver_pool.pop(0)
        driver_backup = driver_pool.pop(0)

        # Guardar en el CSV del DOMINGO ACTUAL (domingo de cierre, p.ej. Vs20250921_sorteos.csv)
        detail = (
            f"weekend|for:{yyyymmdd_from_date(target_gd)}|"
            f"driver:{driver}|driver_backup:{driver_backup}|"
            f"passenger:{passenger}|passenger_backups:{','.join(passenger_backups)}"
        )
        append_sorteo(write_week_dt, "weekend", detail)

        results.append((target_gd.isoweekday(), driver, driver_backup, passenger, passenger_backups))

    # Mensaje
    day_name = {6: "Saturday", 7: "Sunday"}
    lines = []
    for wd, driver, driver_backup, passenger, passenger_backups in results:
        lines.append(
            f"• {day_name.get(wd, '?')}: Driver **{driver}** (backup **{driver_backup}**), "
            f"Passenger **{passenger}** (backups {', '.join(f'**{b}**' for b in passenger_backups) if passenger_backups else '—'})"
        )
    await interaction.response.send_message("🗓️ **Weekend roles (both days):**\n" + "\n".join(lines))
