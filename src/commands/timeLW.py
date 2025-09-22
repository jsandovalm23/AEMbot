# ===============================
# src/commands/timelw.py
# ===============================
# src/commands/timelw.py — show current game/server time and convert server-time to all TZs in a country
from __future__ import annotations
import unicodedata
from datetime import datetime, timedelta, timezone
import discord
from discord import app_commands
import pytz
import pycountry

from ..utils.date_utils import now_utc, to_game_date, yyyymmdd_from_date

UTC = timezone.utc


def _strip_accents(s: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def _country_to_alpha2(country_input: str) -> str | None:
    if not country_input:
        return None
    s = country_input.strip()
    # Direct 2-letter code
    if len(s) == 2:
        return s.upper()
    # Try exact / fuzzy with pycountry
    try:
        c = pycountry.countries.lookup(s)
        return c.alpha_2
    except Exception:
        pass
    # Try without accents, case-insensitive
    s2 = _strip_accents(s).lower()
    for c in pycountry.countries:
        names = [c.name] + [a.common_name for a in [c] if hasattr(c, 'common_name')] + list(getattr(c, 'official_name', '') and [c.official_name] or [])
        for nm in names:
            if _strip_accents(nm).lower() == s2:
                return c.alpha_2
    # Fallback: fuzzy search
    try:
        matches = pycountry.countries.search_fuzzy(s)
        if matches:
            return matches[0].alpha_2
    except Exception:
        pass
    return None


def _format_dt(dt: datetime) -> str:
    return dt.strftime('%Y%m%d %H:%M')


@app_commands.command(name="time_lw", description="Show server time now or convert a server-date/time to all TZs for a country")
@app_commands.describe(yyyymmdd="Server date YYYYMMDD", hhmm="Server time HHmm (24h)", country="Country name or ISO-3166 code")
async def time_lw(interaction: discord.Interaction, yyyymmdd: str | None = None, hhmm: str | None = None, country: str | None = None):
    # Case 1: no params → show NOW
    if not yyyymmdd and not hhmm and not country:
        nowdt = now_utc()  # UTC now
        game_date = to_game_date(nowdt)

        # Server clock = UTC - 2h (00:00 server == 02:00 UTC)
        server_now = nowdt - timedelta(hours=2)

        # Server midnight in *server clock*
        server_midnight_server = server_now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Its equivalent in UTC (solo para claridad)
        server_day_start_utc = server_midnight_server + timedelta(hours=2)

        msg = (
            "🕒 **Last War Time**\n"
            f"• UTC now: {nowdt.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            f"• Server now: {server_now.strftime('%Y-%m-%d %H:%M')} (server)\n"
        )
        return await interaction.response.send_message(msg, ephemeral=True)

    # Case 2: conversion mode — need all three params
    if not (yyyymmdd and hhmm and country):
        return await interaction.response.send_message("Usage: `/time_lw <yyyymmdd> <HHmm> <Country>` — all three are required for conversion.", ephemeral=True)

    # Parse server date/time (server→UTC = +2h)
    if len(yyyymmdd) != 8 or len(hhmm) not in (3, 4):
        return await interaction.response.send_message("Date must be YYYYMMDD and time HHmm (24h).", ephemeral=True)
    try:
        if len(hhmm) == 3:  # e.g., 010 → 00:10
            hhmm = hhmm.zfill(4)
        dt_server_naive = datetime.strptime(yyyymmdd + hhmm, "%Y%m%d%H%M")
    except Exception:
        return await interaction.response.send_message("Invalid date/time format.", ephemeral=True)

    # Convert from server time to UTC by adding 2 hours
    dt_utc = (dt_server_naive.replace(tzinfo=UTC) + timedelta(hours=2))

    # Resolve country to alpha-2
    alpha2 = _country_to_alpha2(country)
    if not alpha2:
        # Build a small hint list
        some = ', '.join(c.name for c in list(pycountry.countries)[:8]) + ', ...'
        return await interaction.response.send_message(
            f"Country not recognized. Try ISO code (e.g., MX, US) or full name. Example: `Mexico`, `México`, `United States`.\nSome examples: {some}",
            ephemeral=True,
        )

    tz_list = pytz.country_timezones.get(alpha2)
    if not tz_list:
        return await interaction.response.send_message(f"No time zones found for country `{alpha2}`.", ephemeral=True)

    # Build per-timezone local times
    items = []
    for tzname in tz_list:
        tz = pytz.timezone(tzname)
        local_dt = dt_utc.astimezone(tz)
        # Show also UTC offset
        offset = local_dt.strftime('%z')  # e.g. -0500
        offset_fmt = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC±00:00"
        items.append((tzname, local_dt, offset_fmt))

    # Sort by offset then tz name
    items.sort(key=lambda t: (t[1].utcoffset() or timedelta(0), t[0]))

    # Render
    header = (
        f"🕒 **Server→Local Time Conversion**\n"
        f"• Input (server): {yyyymmdd} {hhmm[:2]}:{hhmm[2:]}\n"
        f"• Server→UTC (+2h): {dt_utc.strftime('%Y%m%d %H:%M')}\n"
        f"• Country: {alpha2} — {len(items)} time zone(s)"
    )
    lines = [f"• {tz}: {_format_dt(ldt)} ({off})" for tz, ldt, off in items]
    text = header + "\n" + "\n".join(lines)

    # Discord message size safety: chunk if needed
    if len(text) > 1900:
        await interaction.response.send_message(header, ephemeral=True)
        chunk = []
        size = 0
        for line in lines:
            if size + len(line) + 1 > 1900:
                await interaction.followup.send("\n".join(chunk), ephemeral=True)
                chunk, size = [], 0
            chunk.append(line)
            size += len(line) + 1
        if chunk:
            await interaction.followup.send("\n".join(chunk), ephemeral=True)
        return

    await interaction.response.send_message(text, ephemeral=True)
