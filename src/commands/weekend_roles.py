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
)
from ..utils.csv_utils import append_sorteo
from ..storage import weekly_summary


def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    return any(r in names for r in ROLE_ADMIN + ROLE_OFFICIAL)


@app_commands.command(
    name="weekend_roles",
    description="Assign Driver+backup and Passenger+backups for both Saturday and Sunday (no params)"
)
async def weekend_roles(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message(
            "You don't have permission to use this command.",
            ephemeral=True
        )

    # -------------------------------
    # 1) Base temporal en calendario de juego
    # -------------------------------
    nowdt = now_utc()
    cur_gd = to_game_date(nowdt)
    cur_wd = cur_gd.isoweekday()  # 1=Mon ... 7=Sun

    # Domingo PREVIO a la semana actual del calendario de juego:
    #  - Si hoy es domingo, este mismo domingo es el cierre de la semana que acaba de terminar (L–S).
    #  - Si hoy es lunes, tomamos el domingo inmediatamente anterior (ayer) para usar los promedios L–S cerrados.
    monday_game = cur_gd - timedelta(days=(cur_wd - 1))
    prev_sunday_game = monday_game - timedelta(days=1)
    prev_sunday_real = from_game_date(prev_sunday_game)

    # -------------------------------
    # 2) Pool de promedios (semana L–S recién cerrada)
    #    - averages: { name: average_float } calculado sobre 6 días fijos (Mon–Sat)
    # -------------------------------
    summary = weekly_summary(prev_sunday_real)
    aver_map = summary.get("averages", {}) or {}
    averages = [(name, float(avg)) for name, avg in aver_map.items() if float(avg) >= THRESHOLD]

    if len(averages) < 4:
        return await interaction.response.send_message(
            "Need at least 4 average-eligibles to assign without repeats.",
            ephemeral=True
        )

    # Drivers salen del Top-10 por promedio; Passengers del pool completo (>= THRESHOLD) al azar.
    averages.sort(key=lambda x: x[1], reverse=True)
    top10 = [n for n, _ in averages[:10]]     # para Driver
    avg_pool_all = [n for n, _ in averages]   # para Passenger

    # -------------------------------
    # 3) Fechas objetivo: Sábado y Domingo de la SEMANA SIGUIENTE
    #    (si hoy es domingo, empujamos 7 días para el próximo finde)
    # -------------------------------
    targets = []
    for wd in (6, 7):  # Saturday (6), Sunday (7)
        offset = wd - cur_gd.isoweekday()
        if offset <= 0:
            # si hoy es dom (7), offset=0 → empujar 7 días
            offset += 7
        target_gd = cur_gd + timedelta(days=offset)
        targets.append(target_gd)

    results: list[tuple[int, str, str, str, list[str]]] = []

    # Evitar repetidos entre sábado y domingo (pasajeros, backups y drivers)
    used_across_weekend: set[str] = set()  # comparar en minúsculas

    # -------------------------------
    # 4) Asignación por día (Sábado y Domingo)
    # -------------------------------
    for target_gd in targets:
        # Passenger:
        #  - azar total entre todos >= THRESHOLD
        #  - NO excluimos quienes estén en Mon–Vie (permitido repetir con L–V)
        #  - sí evitamos repetidos entre sábado y domingo (used_across_weekend)
        passenger_candidates = [n for n in avg_pool_all if n.lower() not in used_across_weekend]
        if not passenger_candidates:
            return await interaction.response.send_message(
                "No available passenger candidates for weekend (after removing cross-weekend repeats).",
                ephemeral=True
            )
        random.shuffle(passenger_candidates)
        passenger = passenger_candidates.pop(0)

        # Backups de passenger (también evitando repetidos del mismo fin de semana)
        passenger_backups: list[str] = []
        passenger_candidates = [n for n in passenger_candidates if n.lower() not in used_across_weekend]
        if passenger_candidates:
            passenger_backups.append(passenger_candidates.pop(0))
        passenger_candidates = [n for n in passenger_candidates if n.lower() not in used_across_weekend]
        if passenger_candidates:
            passenger_backups.append(passenger_candidates.pop(0))

        # Evitar colisión driver/passenger del mismo día
        used_lower_day = {passenger.lower(), *(b.lower() for b in passenger_backups)}

        # Driver:
        #  - del Top-10
        #  - distinto del passenger/backups del día
        #  - distinto de cualquiera ya usado en el fin de semana (acumulado)
        driver_pool = [
            n for n in top10
            if n.lower() not in used_lower_day and n.lower() not in used_across_weekend
        ]
        if len(driver_pool) < 2:
            return await interaction.response.send_message(
                "Not enough distinct Top-10 candidates to assign driver and backup.",
                ephemeral=True
            )
        random.shuffle(driver_pool)
        driver = driver_pool.pop(0)
        driver_backup = driver_pool.pop(0)

        # Marcar todos como usados para el resto del fin de semana
        used_across_weekend.update({
            passenger.lower(),
            *(b.lower() for b in passenger_backups),
            driver.lower(),
            driver_backup.lower(),
        })

        # -------------------------------
        # 5) Guardado: CSV del DOMINGO DE LA SEMANA DEL TARGET
        #    - Monday de la semana de juego de target_gd + 6 → Sunday (game)
        #    - Convertir a fecha “real” (from_game_date) para que week_csv_names
        #      apunte a VsYYYYMMDD_sorteos.csv correcto (el que usa train_show).
        # -------------------------------
        week_monday_game = target_gd - timedelta(days=(target_gd.isoweekday() - 1))
        target_week_sunday_game = week_monday_game + timedelta(days=6)
        write_ref_dt = from_game_date(target_week_sunday_game)

        detail = (
            f"weekend|for:{yyyymmdd_from_date(target_gd)}|"
            f"driver:{driver}|driver_backup:{driver_backup}|"
            f"passenger:{passenger}|passenger_backups:{','.join(passenger_backups)}"
        )
        append_sorteo(write_ref_dt, "weekend", detail)

        results.append((target_gd.isoweekday(), driver, driver_backup, passenger, passenger_backups))

    # -------------------------------
    # 6) Mensaje final
    # -------------------------------
    day_name = {6: "Saturday", 7: "Sunday"}
    lines = []
    for wd, driver, driver_backup, passenger, passenger_backups in results:
        lines.append(
            f"• {day_name.get(wd, '?')}: Driver **{driver}** (backup **{driver_backup}**), "
            f"Passenger **{passenger}** (backups {', '.join(f'**{b}**' for b in passenger_backups) if passenger_backups else '—'})"
        )
    await interaction.response.send_message("🗓️ **Weekend roles (both days):**\n" + "\n".join(lines))
