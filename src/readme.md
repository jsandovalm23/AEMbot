# Alliance Events Management Bot (Python, discord.py 2.x)

**Time model**: Pure UTC with **server-day cutover at 02:00 UTC** (00:00 server).

## Features

- VS points logging and CSV export.
- Draws: **D (daily)** and **W (weekly)** with CSV audit.
- Weekend roles (driver/passenger).
- Schedules & reminders for **MG (Marshall’s Guard)** and **ZS (Zombie Siege)**.
- **Automatic** daily/weekly draws under defined conditions.
- Train announcements (drivers + VIP passenger/backup) Mon–Fri.
- Weekly calendar (Sun 02:00 UTC) Mon–Sun.
- Runtime feature toggles via `/auto`.

## Prerequisites

- Python **3.11+**
- A Discord **Application** + **Bot Token**
- Role names created in your server (match `.env`): `Official`, `Admin` (or the names you choose)

## Setup

1. Clone the repo and create a venv (optional):
   ```bash
   python -m venv .venv && source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
   ```
2. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
3. Configure **.env** (see `AEM — .env (example)` canvas). Minimum:
   - `BOT_TOKEN`, `GUILD_ID`
   - `ANNOUNCE_CHANNEL_ID`, `ANNOUNCE_ENABLED=true`
4. Invite the bot to your server:
   - Developer Portal → OAuth2 → URL Generator
   - Scopes: `bot`, `applications.commands`
   - Permissions: `View Channels`, `Send Messages`, `Use Application Commands`
5. Run:
   ```bash
   python -m src.main
   ```

> Slash commands will sync to the **guild** defined by `GUILD_ID` (fast). If `GUILD_ID=0`, they sync globally (can take up to 1h).

## File Structure (suggested)

```
.env
requirements.txt
src/
  main.py
  config.py
  storage.py
  utils/
    date_utils.py
    csv_utils.py
    train_utils.py
  commands/
    points.py
    draw.py
    draw_daily.py
    draw_weekly.py
    weekend_roles.py
    status.py
    reset.py
    csv_cmd.py
    weeks.py
    mg_zs.py
    auto.py
    redo.py
    train.py
  scheduler.py
  scheduler_train.py
  announcer.py
  announcer_train.py
data/
  data.json (auto)
  VsYYYYMMDD_registros.csv (auto)
  VsYYYYMMDD_sorteos.csv (auto)
```

## Time Windows (server vs UTC)

- **00:00 server** = **02:00 UTC** (day cutover).
- **Auto Draw D**: **00:30 server** (02:30 UTC) if **no weekly W** recorded.
- **Auto Draw W**: **Sun 00:30 server** (Sun 02:30 UTC) **only** if Mon–Sat are present & pool ≥5.
- **VS reminder**: **23:45 server** (01:45 UTC) daily.
- **MG/ZS reminders**: T-24h / T-12h / T-10m / T-5m.
- **Train posts**: **01:00 server** (03:00 UTC) and **14:30 server** (16:30 UTC). If VIP missing at 01:00, it posts later when available.
- **Weekly calendar**: **Sun 02:00 UTC**, shows **Mon–Sun**.

## Permissions (roles)

Only users with role **Admin** or **Official** can run sensitive commands: draws, weekend_roles, reset, csv, weeks, schedules, auto/redo, train config.

## CSVs

- `VsYYYYMMDD_registros.csv`: `fecha_dia,nombre_comandante,puntos`
- `VsYYYYMMDD_sorteos.csv`: `fecha,semana,tipo,detalle`
- Files append automatically as points/sorteos happen.

## Troubleshooting

- Commands not showing? Check **GUILD_ID**, bot invite scopes/perms, and wait for sync.
- Time mismatches? Ensure server time model is unchanged (`GAME_CUTOVER_UTC=2`).
- No announcements? Verify `ANNOUNCE_CHANNEL_ID`, `ANNOUNCE_ENABLED=true`, and feature toggles `/auto`.

## Security

- Keep your `BOT_TOKEN` secret.
- Consider setting per-channel permissions for announcement channel.
