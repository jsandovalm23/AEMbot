# ===============================
# src/scheduler.py
# ===============================
# src/scheduler.py — auto Draw D/W, event reminders (24h/12h/10m/5m), VS 23:45, weekly calendar (Mon–Sun)
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import tasks
from .config import (
    ANNOUNCE_CHANNEL_ID, ANNOUNCE_ENABLED,
    AUTO_DRAW_D, AUTO_DRAW_W, AUTO_VS_REMINDER,
)
from .utils.date_utils import to_game_date, from_game_date
from .announcer import (
    send_event_before, send_event_before_urgent, send_week_calendar, send_vs_register_reminder,
)
from .storage import get_schedule, has_fired, mark_fired
from .utils.csv_utils import week_csv_names
from .storage import append_sorteo
from .storage import __all__ as _unused  # appease lints

# 🔧 Imports requeridos por _has_weekly_draw_written (se usan fuera de funciones)
import os, csv

UTC = timezone.utc

# 🔧 Ventana mínima sin escrituras antes de cualquier Auto Draw (para evitar correr con datos incompletos)
INGEST_QUIET_MINUTES = 5

EVENT_LABELS = {
    "MG": ("MG", "Marshall’s Guard / MG", 2),
    "ZS": ("ZS", "Zombie Siege / ZS", 3),
}

class Scheduler:
    def __init__(self, bot: discord.Client):
        self.bot = bot

    def channel(self):
        return self.bot.get_channel(ANNOUNCE_CHANNEL_ID) if ANNOUNCE_CHANNEL_ID else None

    def start(self):
        if ANNOUNCE_ENABLED:
            self.tick_loop.start()

    @tasks.loop(minutes=1)
    async def tick_loop(self):
        ch = self.channel()
        if not ch:
            return
        now = datetime.now(UTC)
        gd = to_game_date(now)
        hhmm = now.strftime("%H:%M")

        # 01) VS reminder at 23:45 server (01:45 UTC next day)
        if hhmm == "01:45" and AUTO_VS_REMINDER:
            key = f"VS:{gd.isoformat()}:2345"
            if not has_fired(key):
                await send_vs_register_reminder(ch, gd.strftime("%Y-%m-%d"))
                mark_fired(key)

        # 02) Auto Draw D at 00:30 server = 02:30 UTC (if no weekly draw present)
        if hhmm == "02:30" and AUTO_DRAW_D:
            # 🔧 Solo corre si hubo un periodo de silencio de ingesta (sin escrituras recientes)
            if self._ingest_quiet_period_ok(INGEST_QUIET_MINUTES):
                await self._maybe_auto_draw_d(gd)

        # 03) Auto Draw W at Sunday 00:30 server (02:30 UTC) if full week dataset
        if hhmm == "02:30" and gd.isoweekday() == 7 and AUTO_DRAW_W:
            # 🔧 Solo corre si hubo un periodo de silencio de ingesta (sin escrituras recientes)
            if self._ingest_quiet_period_ok(INGEST_QUIET_MINUTES):
                await self._maybe_auto_draw_w(gd)

        # 04) Event reminders (MG/ZS) 24h/12h/10m/5m
        for kind in ("MG", "ZS"):
            await self._handle_event(now, ch, kind=kind)

        # 05) Weekly calendar at start of game Sunday (02:00 UTC)
        if hhmm == "02:00" and gd.isoweekday() == 7:
            await self._maybe_send_week_calendar(now, ch)

    # ---------- helpers ----------
    async def _handle_event(self, now: datetime, ch, *, kind: str):
        sched = get_schedule(kind)
        if not sched:
            return
        try:
            first = datetime.fromisoformat(sched["first_utc"]).astimezone(UTC)
        except Exception:
            return
        code, full, repeat_days = EVENT_LABELS[kind]
        hhmm_default = sched.get("hhmm_server", "0000")
        hhmm_weekend = sched.get("weekend_hhmm") or hhmm_default

        gd_today = to_game_date(now)
        first_gd = to_game_date(first)
        for day_offset in range(-1, 8):
            gd_candidate = gd_today + timedelta(days=day_offset)
            delta_days = (gd_candidate - first_gd).days
            if delta_days < 0 or (delta_days % repeat_days) != 0:
                continue
            is_weekend = gd_candidate.isoweekday() in (6, 7)
            hhmm = hhmm_weekend if is_weekend else hhmm_default
            try:
                hh, mm = int(hhmm[:2]), int(hhmm[2:])
            except Exception:
                continue
            event_utc_hour = (hh + 2) % 24
            base = from_game_date(gd_candidate)
            event_dt = base.replace(hour=event_utc_hour, minute=mm)

            await self._maybe_fire(ch, kind, code, full, gd_candidate, hhmm, event_dt, now, label="24h", delta=timedelta(hours=24))
            await self._maybe_fire(ch, kind, code, full, gd_candidate, hhmm, event_dt, now, label="12h", delta=timedelta(hours=12))
            await self._maybe_fire(ch, kind, code, full, gd_candidate, hhmm, event_dt, now, label="10m", delta=timedelta(minutes=10))
            await self._maybe_fire(ch, kind, code, full, gd_candidate, hhmm, event_dt, now, label="5m",  delta=timedelta(minutes=5))

    async def _maybe_fire(self, ch, kind: str, code: str, full: str, gd_candidate, hhmm_server: str, event_dt: datetime, now: datetime, *, label: str, delta: timedelta):
        mark_time = event_dt - delta
        if abs((now - mark_time).total_seconds()) <= 59:
            key = f"{kind}:{gd_candidate.isoformat()}:T-{label}"
            if has_fired(key):
                return
            server_date_str = gd_candidate.strftime("%Y-%m-%d")
            server_time_str = f"{hhmm_server[:2]}:{hhmm_server[2:]}"
            eta_seconds = int((event_dt - now).total_seconds())
            if label in ("10m", "5m"):
                await send_event_before_urgent(ch, code, full, server_date_str, server_time_str, eta_seconds, final=(label=="5m"))
            else:
                await send_event_before(ch, code, full, server_date_str, server_time_str, eta_seconds)
            mark_fired(key)

    async def _maybe_send_week_calendar(self, now: datetime, ch):
        from .storage import get_schedule
        entries = []
        gd_sun = to_game_date(now)
        gd_mon = gd_sun - timedelta(days=6)
        week_key = (gd_sun.isocalendar().year, gd_sun.isocalendar().week)
        if has_fired(f"CAL:{week_key}"):
            return
        for kind in ("MG", "ZS"):
            sched = get_schedule(kind)
            if not sched:
                continue
            try:
                upd = datetime.fromisoformat(sched.get("updated_at")).astimezone(UTC)
            except Exception:
                upd = None
            if upd and to_game_date(upd) >= gd_mon:
                continue
            first = datetime.fromisoformat(sched["first_utc"]).astimezone(UTC)
            first_gd = to_game_date(first)
            code, full, interval = EVENT_LABELS[kind]
            hhmm_default = sched.get("hhmm_server", "0000")
            hhmm_weekend = sched.get("weekend_hhmm") or hhmm_default
            for i in range(7):  # Mon..Sun
                gdi = gd_mon + timedelta(days=i)
                delta_days = (gdi - first_gd).days
                if delta_days >= 0 and (delta_days % interval) == 0:
                    is_weekend = gdi.isoweekday() in (6, 7)
                    hhmm = hhmm_weekend if is_weekend else hhmm_default
                    day_label = gdi.strftime("%a %d/%m")
                    time_label = f"{hhmm[:2]}:{hhmm[2:]} (server)"
                    entries.append((day_label, time_label, f"{code} ({full})"))
        entries.sort(key=lambda x: ("Mon Tue Wed Thu Fri Sat Sun".split().index(x[0].split()[0]), x[1]))
        if entries:
            await send_week_calendar(ch, entries)
            mark_fired(f"CAL:{week_key}")

    # ---------- auto draw D/W ----------
    def _has_weekly_draw_written(self, week_dt: datetime) -> bool:
        names = week_csv_names(week_dt)
        path = names["sorteos"]
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if (row.get("tipo") or "").upper() == "W":
                    return True
        return False

    def _has_full_week_data(self, week_dt: datetime) -> bool:
        # basic check via weekly_summary to see Mon..Sat present and pool >=5
        from .storage import weekly_summary
        s = weekly_summary()  # ← API actual: usa la semana actual de juego

        per_days = s.get("days", {})  # { 'YYYYMMDD': [ ... ] }
        days_present = list(per_days.keys())

        # Expect at least 6 days (Mon..Sat) present
        if len(days_present) < 6:
            return False

        # Check each Mon..Sat has records
        from .utils.date_utils import game_week_monsat, yyyymmdd_from_date
        ok = True
        for d in game_week_monsat(week_dt):
            if yyyymmdd_from_date(d) not in per_days:
                ok = False
                break
        if not ok:
            return False

        # Pool por promedios >= 7.2M (s['averages'] ya es nombre -> número)
        pool = [n for n, avg in s.get("averages", {}).items() if avg >= 7_200_000]
        return len(pool) >= 5

    async def _maybe_auto_draw_d(self, gd_today: date):
        import random  # se usa localmente aquí
        # base is yesterday game-day
        base = gd_today - timedelta(days=1)
        if base.isoweekday() == 7:
            return  # never based on Sunday
        from .utils.date_utils import yyyymmdd_from_date, from_game_date
        from .storage import weekly_summary
        week_dt = from_game_date(base)

        # Skip if a weekly draw exists for this week
        if self._has_weekly_draw_written(week_dt):
            return

        # If already have D for today, skip
        today_key = yyyymmdd_from_date(gd_today)
        names = week_csv_names(week_dt)
        path = names["sorteos"]
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if (row.get("tipo") or "").upper() == "D" and f"for:{today_key}" in (row.get("detalle") or ""):
                        return

        # Build eligibles from base day (usa la clave actual 'eligibles_by_day')
        s = weekly_summary()  # semana actual
        base_key = yyyymmdd_from_date(base)
        eligibles = list(set(s.get("eligibles_by_day", {}).get(base_key, [])))
        if not eligibles:
            return

        random.shuffle(eligibles)
        passenger = eligibles[0]
        backups = eligibles[1:3]
        detail = f"D|for:{today_key}|passenger:{passenger}|backups:{','.join(backups)}"
        append_sorteo(week_dt, "D", detail)

    async def _maybe_auto_draw_w(self, gd_sun: date):
        import random  # se usa localmente aquí
        from .utils.date_utils import from_game_date, game_week_monsat, yyyymmdd_from_date
        week_dt = from_game_date(gd_sun)
        if self._has_weekly_draw_written(week_dt):
            return
        if not self._has_full_week_data(week_dt):
            return

        # Build pool by averages ≥ 7.2M
        from .storage import weekly_summary
        s = weekly_summary()  # semana actual
        averages = [n for n, avg in s.get("averages", {}).items() if avg >= 7_200_000]
        if len(averages) < 5:
            return

        pool = averages.copy()
        random.shuffle(pool)
        days = game_week_monsat(week_dt)
        for d in days[:5]:
            if not pool:
                break
            passenger = pool.pop(0)
            bks = []
            if pool: bks.append(pool.pop(0))
            if pool: bks.append(pool.pop(0))
            detail = f"W|for:{yyyymmdd_from_date(d)}|passenger:{passenger}|backups:{','.join(bks)}"
            append_sorteo(week_dt, "W", detail)

    # 🔧 Helper para quiet period de ingesta (señal de escrituras recientes en storage)
    def _ingest_quiet_period_ok(self, minutes: int) -> bool:
        """
        Devuelve True si no ha habido escrituras recientes en el storage.
        Usa el mtime de data.json como indicador de actividad.
        """
        try:
            from .config import DATA_DIR
            data_path = os.path.join(DATA_DIR, "data.json")
            mtime = os.path.getmtime(data_path)
        except FileNotFoundError:
            # Si no existe aún el archivo, consideramos que está “quiet”
            return True
        except Exception:
            # Ante cualquier error inesperado, sé conservador y no dispares el draw
            return False

        last_write = datetime.fromtimestamp(mtime, UTC)
        return (datetime.now(UTC) - last_write) >= timedelta(minutes=minutes)
