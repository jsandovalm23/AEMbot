# ===============================
# src/commands/points.py
# ===============================
import discord
from discord import app_commands
import logging
from datetime import date, datetime, timedelta

from ..utils.date_utils import (
    now_utc,
    to_game_date,
    from_game_date,
    is_game_mon_to_sat,
)
from ..storage import register_points

logger = logging.getLogger(__name__)

_DAY_KEY_FROM_WEEKDAY = {0: "mon", 1: "tue", 2: "wed", 3: "thu", 4: "fri", 5: "sat"}

@app_commands.command(name="points", description="Register VS points for the current ISO week (game-day model)")
@app_commands.describe(name="In-game player name", amount="Points (integer)", day="Optional: mon|tue|wed|thu|fri|sat")
async def points(interaction: discord.Interaction, name: str, amount: int, day: str | None = None):
    try:
        name = name.strip()

        # Reglas (resumen):
        # - Nunca registrar en FUTURO.
        # - Sin 'day' → registrar en AYER (game-day); si AYER fue Sunday, ajustar a Saturday.
        # - Con 'day' (mon..sat) →
        #     * Domingo o Lunes: se puede registrar para la SEMANA PASADA.
        #     * Mar–Sáb: solo días de la SEMANA ACTUAL que no sean futuro.
        #
        # Nota: Para registrar en la semana pasada (Dom/Lun), calculamos un target_gd (game-date)
        #       y pasamos ese contexto a storage.register_points para que escriba en la semana correcta.

        now_dt = now_utc()
        current_gd = to_game_date(now_dt)              # fecha de juego "hoy" (date)
        current_wd = current_gd.isoweekday()           # 1=Mon ... 7=Sun

        if not day:
            # Caso: sin día → AYER
            target_gd = current_gd - timedelta(days=1)
            # Si AYER fue Sunday (no válido para VS), mover a Saturday (semana previa).
            if target_gd.isoweekday() == 7:
                target_gd = target_gd - timedelta(days=1)  # Saturday
        else:
            # Normalizar entrada de día
            key = (day or "").strip().lower()
            _abbr_to_idx = {
                # en inglés porque tus slash commands están en inglés
                "mon": 1, "monday": 1,
                "tue": 2, "tuesday": 2,
                "wed": 3, "wednesday": 3,
                "thu": 4, "thursday": 4,
                "fri": 5, "friday": 5,
                "sat": 6, "saturday": 6,
                # soporta español por conveniencia
                "lun": 1, "lunes": 1,
                "mar": 2, "martes": 2,
                "mie": 3, "mié": 3, "miercoles": 3, "miércoles": 3,
                "jue": 4, "jueves": 4,
                "vie": 5, "viernes": 5,
                "sab": 6, "sáb": 6, "sabado": 6, "sábado": 6,
            }
            if key not in _abbr_to_idx:
                return await interaction.response.send_message(
                    "Invalid day. Use: mon, tue, wed, thu, fri, sat.", ephemeral=True
                )

            desired_idx = _abbr_to_idx[key]  # 1..6
            # Monday de la semana ACTUAL (que contiene current_gd)
            monday_gd = current_gd - timedelta(days=(current_wd - 1))  # siempre Monday

            if current_wd == 7:
                # Domingo: se permite registrar para cualquier Mon–Sat de la semana que cierra hoy.
                target_gd = monday_gd + timedelta(days=(desired_idx - 1))
            elif current_wd == 1:
                # Lunes:
                # - Todo lo que se registre en lunes (Mon–Sat) pertenece a la semana pasada.
                prev_monday_gd = monday_gd - timedelta(days=7)
                target_gd = prev_monday_gd + timedelta(days=(desired_idx - 1))
            else:
                # Mar–Sáb: solo semana ACTUAL y nunca futuro.
                if desired_idx > current_wd:
                    return await interaction.response.send_message(
                        "Cannot register points in the future. Choose a past or current game-day.", ephemeral=True
                    )
                target_gd = monday_gd + timedelta(days=(desired_idx - 1))

        # Convertir target_gd (date) a 'when' (date) para validaciones/mensaje
        when = from_game_date(target_gd)
        if isinstance(when, datetime):
            when = when.date()

        # Validar VS: Monday–Saturday (game-day)
        if not is_game_mon_to_sat(when):
            return await interaction.response.send_message(
                "VS runs **Monday–Saturday** (game-day). Choose a valid day.", ephemeral=True
            )

        # Convertir 'when' a clave 'day' que espera storage.register_points
        weekday_py = when.weekday()  # 0=Mon ... 6=Sun
        if weekday_py == 6:
            return await interaction.response.send_message(
                "VS runs **Mon–Sat**; Sunday is not a valid VS day.", ephemeral=True
            )
        day_key = _DAY_KEY_FROM_WEEKDAY[weekday_py]  # 'mon'..'sat'

        # Llamada a storage.register_points:
        #  - Usamos 'day=day_key' y además pasamos 'ref_date=target_gd' para que escriba
        #    en la semana correcta (actual o pasada según el escenario).
        week_key, date_key, player_total_today = register_points(
            name=name,
            amount=amount,
            day=day_key,
            ref_date=target_gd,  # <-- clave: fija la semana correcta
        )

        # Mensaje de confirmación (simple, sin notas extras)
        pretty_day = when.strftime('%A %d/%m')
        msg = f"✓ {name}: {player_total_today:,} registered for **{pretty_day}** (game-day total)."

        if not interaction.response.is_done():
            await interaction.response.send_message(msg)
        else:
            await interaction.followup.send(msg)

    except Exception as e:
        logger.exception("Error in /points for %s", name if 'name' in locals() else '?')
        err = f"❌ Error: {e}"
        if not interaction.response.is_done():
            await interaction.response.send_message(err, ephemeral=True)
        else:
            await interaction.followup.send(err, ephemeral=True)
