# ===============================
# src/scheduler_train.py
# ===============================
# posts at 01:00 server and 14:30 server; waits if passenger missing
from __future__ import annotations
from datetime import datetime, timedelta, timezone, date
import os
import csv
import discord
from discord.ext import tasks

from .config import ANNOUNCE_CHANNEL_ID, ANNOUNCE_ENABLED, AUTO_TRAIN_POST
from .utils.date_utils import to_game_date, from_game_date
from .utils.train_utils import driver_for_day, read_draw_for_date
from .announcer_train import send_train_day, send_train_week
from .storage import get_train_config
from .utils.csv_utils import week_csv_names

UTC = timezone.utc

# -------------------------------------------------------
# Helpers locales para leer weekend (driver/pax) del CSV
# -------------------------------------------------------

def _parse_pipe_kv(detail: str) -> dict[str, str]:
    # Convierte "weekend|for:YYYYMMDD|driver:...|driver_backup:...|passenger:...|passenger_backups:A,B"
    # a {"for": "...", "driver": "...", "driver_backup": "...", "passenger": "...", "passenger_backups": "..."}
    s = detail or ""
    if s.startswith(("W|", "D|", "weekend|")):
        s = s.split("|", 1)[1] if "|" in s else ""
    out: dict[str, str] = {}
    for part in s.split("|"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip().lower()] = v.strip()
    return out

def _utc_from_date(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)

def _prev_sunday_ref(d: date) -> datetime:
    # Sunday inmediatamente anterior al lunes de la semana de `d`
    monday = d - timedelta(days=d.weekday())  # Monday=0
    prev_sunday = monday - timedelta(days=1)
    return _utc_from_date(prev_sunday)

def _this_week_ref(d: date) -> datetime:
    return _utc_from_date(d)

def _read_weekend_for_date(real_day: date) -> tuple[str | None, str | None, str | None, str | None]:
    """
    Lee un registro 'weekend' para 'real_day' (sábado o domingo).
    Devuelve: (driver, driver_backup, passenger, passenger_backup_1)
    Si no encuentra, regresa (None, None, None, None)
    """
    target = real_day.strftime("%Y%m%d")
    # El bot escribe weekend en la semana de trabajo vigente (domingo previo),
    # así que buscamos primero en el CSV del domingo previo; si no, en el actual.
    for ref in (_prev_sunday_ref(real_day), _this_week_ref(real_day)):
        path = week_csv_names(ref)["sorteos"]
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row.get("tipo") or "").strip().lower() != "weekend":
                        continue
                    kv = _parse_pipe_kv(row.get("detalle") or "")
                    if kv.get("for") == target:
                        drv = (kv.get("driver") or "").strip() or None
                        drv_b = (kv.get("driver_backup") or "").strip() or None
                        pax = (kv.get("passenger") or "").strip() or None
                        pax_b1 = None
                        backs = kv.get("passenger_backups") or ""
                        if backs:
                            first = (backs.split(",")[0] or "").strip()
                            pax_b1 = first or None
                        return drv, drv_b, pax, pax_b1
        except Exception:
            continue
    return (None, None, None, None)

class TrainScheduler:
    """
    Publica el tren:
      - 01:00 server (03:00 UTC): anuncio del día. Si falta VIP, avisa y queda 'pendiente';
        publicará automáticamente cuando aparezca el VIP.
      - 14:30 server (16:30 UTC): recordatorio del día.
      - Lunes a las 01:00 server: publica la semana completa **Mon–Sun** (configurable).
    """
    def __init__(self, bot: discord.Client):
        self.bot = bot
        self._posted_today_0100: date | None = None
        self._posted_today_1430: date | None = None
        self._pending_day: date | None = None
        self._posted_weekly_for_monday: date | None = None  # lunes (game-day) para el que ya se publicó resumen

    def channel(self):
        return self.bot.get_channel(ANNOUNCE_CHANNEL_ID) if ANNOUNCE_CHANNEL_ID else None

    def start(self):
        if ANNOUNCE_ENABLED and AUTO_TRAIN_POST:
            self.loop.start()

    @tasks.loop(minutes=1)
    async def loop(self):
        ch = self.channel()
        if not ch:
            return

        now = datetime.now(UTC)
        gd = to_game_date(now)  # fecha de juego (server-day con corte 02:00 UTC)
        hhmm = now.strftime("%H:%M")

        # 01:00 server == 03:00 UTC
        if hhmm == "03:00" and self._posted_today_0100 != gd:
            ok = await self._try_post_for_day(ch, gd, when_title="Today 01:00 server")
            if not ok:
                await self._safe_send(ch, "📝 Falta pasajero VIP hoy. Registra puntos y/o corre `draw D` para publicar el tren.")
                self._pending_day = gd
            self._posted_today_0100 = gd

            # Si es lunes (game-day) y está habilitado, publicar semanal Mon–Sun una vez
            if gd.isoweekday() == 1 and self._posted_weekly_for_monday != gd:
                await self.post_weekly_if_enabled(ch, gd)
                self._posted_weekly_for_monday = gd

        # 14:30 server == 16:30 UTC
        if hhmm == "16:30" and self._posted_today_1430 != gd:
            await self._try_post_for_day(ch, gd, when_title="Today 14:30 server (reminder)")
            self._posted_today_1430 = gd

        # Si quedó pendiente, intentamos publicar cuando aparezca el VIP (mismo game day)
        if self._pending_day is not None and self._pending_day == to_game_date(now):
            ok = await self._try_post_for_day(ch, gd, when_title="Update — Train (passenger available)")
            if ok:
                self._pending_day = None

        # Limpieza: si cambió de game-day, reiniciar flags de día (por si el bot estuvo pausado)
        if self._posted_today_0100 and self._posted_today_0100 != gd and self._pending_day and self._pending_day != gd:
            self._pending_day = None

    async def _try_post_for_day(self, ch: discord.abc.MessageableChannel, game_day: date, *, when_title: str) -> bool:
        """
        Publica el mensaje del día si:
         - Es lunes a viernes (1..5).
         - Hay configuración de conductores + ancla.
         - Existe pasajero VIP (y backup) para ese día (buscado en CSV por fecha).
        Devuelve True si publicó; False si faltaba algo (especialmente el VIP).
        """
        if game_day.isoweekday() not in (1, 2, 3, 4, 5):
            return True  # No hay tren en fin de semana

        cfg = get_train_config()
        drivers10 = cfg.get("drivers", [])
        anchor = cfg.get("anchor_monday")
        if not anchor or not drivers10:
            return False

        # ancla (ISO) → date
        from datetime import date as _date
        try:
            anchor_d = _date.fromisoformat(anchor)
        except Exception:
            return False

        # Conductor según rotación 2 semanas
        driver = driver_for_day(drivers10, anchor_d, game_day) or "—"

        # Pasajero/backup: se lee del CSV de sorteos (D/W) para ese día de calendario real
        pax, backup = read_draw_for_date(from_game_date(game_day))  # from_game_date(game_day) -> date real
        if not pax:
            return False

        await self._safe_send_embed_or_text(
            ch,
            title=f"🚆 Train — {when_title}",
            lines=[
                f"• Driver: **{driver}**",
                f"• Passenger VIP: **{pax}** (backup **{(backup or '—')}**)"
            ],
        )
        return True

    async def post_weekly_if_enabled(self, ch: discord.abc.MessageableChannel, game_day: date):
        """
        (Opcional) Publica la lista completa **Mon–Sun** el lunes, si está habilitado en config.
        - Mon–Fri: driver por rotación + VIP desde CSV (D/W) si existe (o 'Pending').
        - Sat/Sun: driver/pax desde CSV 'weekend' si existe (o 'Pending').
        """
        cfg = get_train_config()
        if not cfg.get("post_full_on_monday", True):
            return

        drivers10 = cfg.get("drivers", [])
        anchor = cfg.get("anchor_monday")
        if not anchor or not drivers10:
            return

        from datetime import date as _date
        try:
            anchor_d = _date.fromisoformat(anchor)
        except Exception:
            return

        # lunes de la semana del game_day
        monday_gameday = game_day - timedelta(days=(game_day.isoweekday() - 1))
        monday_real = from_game_date(monday_gameday)

        # Construir entradas Mon–Sun
        entries: list[tuple[str, str, str]] = []
        labels = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
        for i in range(7):
            day_game = monday_gameday + timedelta(days=i)
            day_real = from_game_date(day_game)
            label = f"{labels[i]} {day_real.strftime('%d/%m')}"

            if 1 <= day_game.isoweekday() <= 5:
                # Rotación + D/W
                drv = driver_for_day(drivers10, anchor_d, day_game) or "Pending"
                pax, bkp = read_draw_for_date(day_real)
                pax_label = f"{pax} (Bkp: {bkp})" if pax else "Pending"
                entries.append((label, drv if drv.strip() else "Pending", pax_label))
            else:
                # Weekend (desde CSV weekend)
                drv_wk, drv_bk_wk, pax_wk, pax_b1_wk = _read_weekend_for_date(day_real)
                drv_label = drv_wk or "Pending"
                if pax_wk:
                    pax_label = f"{pax_wk}" + (f" (Bkp: {pax_b1_wk})" if pax_b1_wk else "")
                else:
                    pax_label = "Pending"
                entries.append((label, drv_label, pax_label))

        # Enviar
        try:
            await send_train_week(ch, entries)
        except Exception:
            # fallback simple si el mensaje rico falla por cualquier razón
            lines = "\n".join(f"• {d}: Driver **{drv}** — {pax}" for d, drv, pax in entries)
            await self._safe_send(ch, "📅 **Train — Weekly Lineup (Mon–Sun)**\n" + lines)

    # -----------------------------
    # helpers para envío seguro
    # -----------------------------
    async def _safe_send(self, ch: discord.abc.MessageableChannel, content: str):
        try:
            await ch.send(content)
        except discord.Forbidden:
            # Missing permissions — silenciar para que el loop no muera
            pass
        except Exception:
            pass

    async def _safe_send_embed_or_text(self, ch: discord.abc.MessageableChannel, title: str, lines: list[str]):
        # Enviamos en texto simple por simplicidad/compatibilidad
        await self._safe_send(ch, f"{title}\n" + "\n".join(lines))
