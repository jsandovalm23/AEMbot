# ===============================
# src/announcer_train.py
# ===============================
# src/announcer_train.py — train messages
# - Tolera valores faltantes (muestra "Pending" o "—")
# - Muestra backup si se provee
# - Para la vista semanal, acepta 5 (Mon–Fri) o 7 (Mon–Sun) entradas
#   y cambia el título automáticamente.
# - Es retrocompatible: cada entrada puede ser:
#     (day_label, driver, pax)  ó  (day_label, driver, pax, backup)

from __future__ import annotations
from typing import Iterable, Sequence

def _fmt_name(s: str | None, pending: str = "Pending", dash_as_pending: bool = True) -> str:
    if not s:
        return pending
    s = s.strip()
    if not s or (dash_as_pending and s == "—"):
        return pending
    return s

async def send_train_day(channel, *, day_label: str, driver: str, passenger: str, backup: str, when_title: str):
    drv = _fmt_name(driver, pending="—", dash_as_pending=False)
    pax = _fmt_name(passenger, pending="Pending")
    bkp = _fmt_name(backup, pending="—", dash_as_pending=False)
    await channel.send(
        f"🚆 **Train — {when_title}**\n"
        f"• Driver: **{drv}**\n"
        f"• Passenger VIP: **{pax}** (backup **{bkp}**)"
    )

async def send_train_week(channel, entries: Iterable[Sequence[str]]):
    entries = list(entries)
    title = "📅 **Train — Weekly Lineup (Mon–Sun)**" if len(entries) >= 7 else "📅 **Train — Weekly Lineup (Mon–Fri)**"

    lines = []
    for e in entries:
        if len(e) >= 4:
            day_label, driver, pax, bkp = e[0], e[1], e[2], e[3]
        else:
            day_label, driver, pax = e[0], e[1], e[2]
            bkp = None

        drv = _fmt_name(driver, pending="—", dash_as_pending=False)
        pax_fmt = _fmt_name(pax, pending="Pending")
        bkp_fmt = _fmt_name(bkp, pending=None) if bkp else None

        drv_txt = drv if drv == "Pending" else f"**{drv}**"
        pax_txt = pax_fmt if pax_fmt == "Pending" else f"**{pax_fmt}**"
        bkp_txt = f" (_{bkp_fmt}_)" if bkp_fmt else ""

        lines.append(f"• {day_label} | Driver = {drv_txt} — VIP = {pax_txt}{bkp_txt}")

    await channel.send(title + "\n" + "\n".join(lines))
