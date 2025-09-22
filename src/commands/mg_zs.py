# ===============================
# src/commands/mg_zs.py
# ===============================
# /mg and /zs scheduling (optional weekend HHmm) + /mg_status and /zs_status
# Repeats: MG every 2 days, ZS every 3 days. Server clock = UTC-2 (00:00 server == 02:00 UTC)
from __future__ import annotations
import math
from datetime import datetime, timedelta, timezone, time as dtime
import discord
from discord import app_commands
from ..config import ROLE_ADMIN, ROLE_OFFICIAL
from ..storage import set_schedule, get_schedule

UTC = timezone.utc

# ---------- Roles (local, NOT centralized) ----------
def _to_role_list(v) -> list[str]:
    # Accept string ("R5,R4") or list from config
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []

def has_role(member: discord.Member) -> bool:
    names = {r.name for r in getattr(member, "roles", [])}
    allow = set(_to_role_list(ROLE_ADMIN) + _to_role_list(ROLE_OFFICIAL))
    return any(n in allow for n in names)

# ---------- Helpers ----------
def _parse_hhmm(hhmm: str) -> dtime | None:
    s = (hhmm or "").strip()
    if len(s) not in (3, 4) or not s.isdigit():
        return None
    s = s.zfill(4)
    hh, mm = int(s[:2]), int(s[2:])
    if 0 <= hh < 24 and 0 <= mm < 60:
        return dtime(hour=hh, minute=mm)
    return None

def _server_now_utc() -> datetime:
    # Now in UTC; server clock is UTC-2
    return datetime.now(UTC)

def _server_dt_to_utc(dt_server: datetime) -> datetime:
    return dt_server + timedelta(hours=2)

def _utc_to_server_dt(dt_utc: datetime) -> datetime:
    return dt_utc - timedelta(hours=2)

def _weekday_is_weekend(dt_server_date: datetime) -> bool:
    # Saturday=5, Sunday=6 (isoweekday: Mon=1..Sun=7)
    wd = dt_server_date.isoweekday()
    return wd in (6, 7)  # Sat(6), Sun(7)

def _format_server(dt_utc: datetime) -> str:
    # Show YYYY-MM-DD HH:MM in server clock
    sv = _utc_to_server_dt(dt_utc)
    return sv.strftime("%Y-%m-%d %H:%M (server)")

def _maybe_avoid_overlap_with_mg(candidate_utc: datetime,
                                 base_date,
                                 is_weekend: bool) -> tuple[datetime, bool]:
    mg_cfg = get_schedule("MG")
    if not mg_cfg:
        return candidate_utc, False

    try:
        mg_first_utc = datetime.fromisoformat(mg_cfg["first_utc"]).replace(tzinfo=UTC)
    except Exception:
        return candidate_utc, False

    mg_repeat = int(mg_cfg.get("repeat_days") or 0)
    if mg_repeat <= 0:
        return candidate_utc, False

    mg_first_server = _utc_to_server_dt(mg_first_utc)
    delta_days = (base_date - mg_first_server.date()).days
    if delta_days < 0 or (delta_days % mg_repeat) != 0:
        return candidate_utc, False

    mg_hhmm = mg_cfg.get("weekend_hhmm") if (is_weekend and mg_cfg.get("weekend_hhmm")) else mg_cfg.get("hhmm_server")
    t_mg = _parse_hhmm(mg_hhmm or "")
    if not t_mg:
        return candidate_utc, False

    mg_server_dt = datetime.combine(base_date, t_mg, tzinfo=UTC)
    mg_utc_dt = _server_dt_to_utc(mg_server_dt)

    if mg_utc_dt == candidate_utc:
        return candidate_utc + timedelta(minutes=30), True

    return candidate_utc, False

def _next_occurrences(kind: str, count: int = 3) -> list[tuple[datetime, str]]:
    """
    Returns up to `count` upcoming occurrences for schedule `kind` ('MG'|'ZS').
    Each item: (occurrence_utc, note) with note indicating if weekend hour applied.
    """
    cfg = get_schedule(kind)
    if not cfg:
        return []
    first_utc_iso = cfg.get("first_utc")
    hhmm_server = cfg.get("hhmm_server") or ""
    weekend_hhmm = cfg.get("weekend_hhmm") or None
    repeat_days = int(cfg.get("repeat_days") or 0)
    if not first_utc_iso or repeat_days <= 0:
        return []

    try:
        first_utc = datetime.fromisoformat(first_utc_iso).replace(tzinfo=UTC)
    except Exception:
        return []

    # Convert first occurrence to server clock (baseline date)
    first_server = _utc_to_server_dt(first_utc)
    # We step by repeat_days on the DATE in server clock, choosing the hour per weekday
    now_utc = _server_now_utc()
    now_server = _utc_to_server_dt(now_utc)

    # Find k0 = smallest k such that candidate >= now (in server clock)
    # Start by estimating days since first date
    if now_server.date() <= first_server.date():
        k = 0
    else:
        diff_days = (now_server.date() - first_server.date()).days
        k = max(0, math.floor(diff_days / repeat_days))

    out: list[tuple[datetime, str]] = []
    tried = 0
    # Safety cap
    while len(out) < count and tried < 365:
        tried += 1
        base_date = first_server.date() + timedelta(days=k * repeat_days)
        # Choose hour for this base_date (server)
        is_weekend = _weekday_is_weekend(datetime.combine(base_date, dtime(0, 0), tzinfo=UTC))
        use_hhmm = weekend_hhmm if (is_weekend and weekend_hhmm) else hhmm_server
        t = _parse_hhmm(use_hhmm)
        if not t:
            # if invalid time config, stop
            break
        candidate_server = datetime.combine(base_date, t, tzinfo=UTC)  # server tz emulated (UTC tzinfo, but values are in server clock)
        candidate_utc = _server_dt_to_utc(candidate_server)

        # ✅ Ajuste anti-solape: solo para ZS
        note_extra = ""
        if kind == "ZS":
            candidate_utc, adjusted = _maybe_avoid_overlap_with_mg(candidate_utc, base_date, is_weekend)
            if adjusted:
                note_extra = " (After MG)"

        if candidate_utc >= now_utc:
            note = "Special hour" if (is_weekend and weekend_hhmm) else "Regular hour"
            out.append((candidate_utc, note + note_extra))

        k += 1

    return out

# ---------- Commands ----------
@app_commands.command(name="mg", description="Schedule MG: /mg <yyyymmdd> <hhmm> [<hhmm_weekend>] (server); repeats every 2 days")
@app_commands.describe(date_yyyymmdd="YYYYMMDD (server date)", time_hhmm="HHmm (server time)", weekend_hhmm="HHmm for Sat/Sun if different")
async def mg(interaction: discord.Interaction, date_yyyymmdd: str, time_hhmm: str, weekend_hhmm: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)

    # Parse date/time (server → UTC + 2h)
    try:
        dt_server = datetime.strptime(date_yyyymmdd + time_hhmm, "%Y%m%d%H%M").replace(tzinfo=UTC)
    except Exception:
        return await interaction.response.send_message("Invalid format. Use /mg <yyyymmdd> <hhmm> [<hhmm_weekend>]", ephemeral=True)

    if not _parse_hhmm(time_hhmm):
        return await interaction.response.send_message("Invalid HHmm for weekday.", ephemeral=True)
    if weekend_hhmm and not _parse_hhmm(weekend_hhmm):
        return await interaction.response.send_message("Invalid HHmm for weekend.", ephemeral=True)

    first_utc = _server_dt_to_utc(dt_server)
    set_schedule("MG", first_utc.isoformat(), time_hhmm, 2, weekend_hhmm)
    tail = f" (weekend {weekend_hhmm})" if weekend_hhmm else ""
    await interaction.response.send_message(
        f"✅ MG scheduled {date_yyyymmdd} at {time_hhmm}{tail} (server). Repeats every 2 days. Pre-warnings: 24h, 12h, 10m, 5m."
    )

@app_commands.command(name="zs", description="Schedule ZS: /zs <yyyymmdd> <hhmm> [<hhmm_weekend>] (server); repeats every 3 days")
@app_commands.describe(date_yyyymmdd="YYYYMMDD (server date)", time_hhmm="HHmm (server time)", weekend_hhmm="HHmm for Sat/Sun if different")
async def zs(interaction: discord.Interaction, date_yyyymmdd: str, time_hhmm: str, weekend_hhmm: str | None = None):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)

    try:
        dt_server = datetime.strptime(date_yyyymmdd + time_hhmm, "%Y%m%d%H%M").replace(tzinfo=UTC)
    except Exception:
        return await interaction.response.send_message("Invalid format. Use /zs <yyyymmdd> <hhmm> [<hhmm_weekend>]", ephemeral=True)

    if not _parse_hhmm(time_hhmm):
        return await interaction.response.send_message("Invalid HHmm for weekday.", ephemeral=True)
    if weekend_hhmm and not _parse_hhmm(weekend_hhmm):
        return await interaction.response.send_message("Invalid HHmm for weekend.", ephemeral=True)

    first_utc = _server_dt_to_utc(dt_server)
    set_schedule("ZS", first_utc.isoformat(), time_hhmm, 3, weekend_hhmm)
    tail = f" (weekend {weekend_hhmm})" if weekend_hhmm else ""
    await interaction.response.send_message(
        f"✅ ZS scheduled {date_yyyymmdd} at {time_hhmm}{tail} (server). Repeats every 3 days. Pre-warnings: 24h, 12h, 10m, 5m."
    )

# ---------- Status commands ----------
def _format_status(kind: str) -> str:
    cfg = get_schedule(kind)
    if not cfg:
        return f"• {kind}: not scheduled."
    wkd = cfg.get("hhmm_server") or "—"
    wknd = cfg.get("weekend_hhmm") or "—"
    rep = int(cfg.get("repeat_days") or 0)

    upcoming = _next_occurrences(kind, count=3)
    if not upcoming:
        return f"• {kind}: configured (every {rep}d, weekday {wkd}, weekend {wknd}) — no upcoming found."

    lines = [
        f"• {kind}: every {rep}d — weekday {wkd}, weekend {wknd}"
    ]
    for (dt_u, note) in upcoming:
        lines.append(f"   ↳ next: {_format_server(dt_u)}  [{note}]")
    return "\n".join(lines)

@app_commands.command(name="mg_status", description="Show upcoming MG occurrences and config")
async def mg_status(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    msg = "📅 **MG Status**\n" + _format_status("MG")
    await interaction.response.send_message(msg, ephemeral=True)

@app_commands.command(name="zs_status", description="Show upcoming ZS occurrences and config")
async def zs_status(interaction: discord.Interaction):
    if not isinstance(interaction.user, discord.Member) or not has_role(interaction.user):
        return await interaction.response.send_message("No permission.", ephemeral=True)
    msg = "📅 **ZS Status**\n" + _format_status("ZS")
    await interaction.response.send_message(msg, ephemeral=True)
