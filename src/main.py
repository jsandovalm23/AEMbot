# ===============================
# src/main.py
# ===============================
# src/main.py — Discord bot bootstrap (discord.py 2.x)
from __future__ import annotations
import os
import logging
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Local modules
from .config import BOT_TOKEN, GUILD_ID, ANNOUNCE_ENABLED

# Core schedulers (automation)
from .scheduler import Scheduler as EventScheduler
from .scheduler_train import TrainScheduler

# Commands: points/draw/weekend/status/reset/csv/weeks (assumed existing in your project)
# If any are not present, comment out their imports/add_command lines.
from .commands.points import points  # /points <name> <amount> [day]
from .commands.draw import draw      # /draw <D|W>
from .commands.weekend_roles import weekend_roles
from .commands.status import status
from .commands.reset import reset
from .commands.csv_tools import csv_tools
from .commands.weeks import weeks
from .commands.help_aem import help_aem
from .commands.timeLW import time_lw
from .commands.reset_all import reset_all

# New commands (schedulers & train)
from .commands.mg_zs import mg, zs, mg_status, zs_status
from .commands.auto import auto
from .commands.redo import redo_d, redo_w
from .commands.train import (
    train_set_drivers, train_set_anchor, train_mode, train_show
)

# ---------------------- setup ----------------------
load_dotenv()
logging.basicConfig(level=logging.INFO)

intents = discord.Intents.default()
intents.guilds = True
intents.members = False
intents.message_content = False  # no es necesario para slash commands

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    try:
        guild_obj = discord.Object(id=GUILD_ID) if GUILD_ID else None

        if guild_obj:
            # Limpia comandos antiguos del guild y registra los actuales (iteración rápida)
            bot.tree.clear_commands(guild=guild_obj)

            # ----- add all commands (guild-scoped) -----
            bot.tree.add_command(points, guild=guild_obj)
            bot.tree.add_command(draw, guild=guild_obj)
            bot.tree.add_command(weekend_roles, guild=guild_obj)
            bot.tree.add_command(status, guild=guild_obj)
            bot.tree.add_command(reset, guild=guild_obj)
            bot.tree.add_command(csv_tools, guild=guild_obj)
            bot.tree.add_command(weeks, guild=guild_obj)

            bot.tree.add_command(mg, guild=guild_obj)
            bot.tree.add_command(zs, guild=guild_obj)
            bot.tree.add_command(mg_status, guild=guild_obj)
            bot.tree.add_command(zs_status, guild=guild_obj)
            bot.tree.add_command(auto, guild=guild_obj)
            bot.tree.add_command(redo_d, guild=guild_obj)
            bot.tree.add_command(redo_w, guild=guild_obj)
            bot.tree.add_command(train_set_drivers, guild=guild_obj)
            bot.tree.add_command(train_set_anchor, guild=guild_obj)
            bot.tree.add_command(train_mode, guild=guild_obj)
            bot.tree.add_command(train_show, guild=guild_obj)
            bot.tree.add_command(help_aem, guild=guild_obj)
            bot.tree.add_command(time_lw, guild=guild_obj)
            bot.tree.add_command(reset_all, guild=guild_obj)

            await bot.tree.sync(guild=guild_obj)
            logging.info("Slash commands synced to guild %s", GUILD_ID)
        else:
            # Sin GUILD_ID: registra global (propagación lenta ~1h). Limpia global antes.
            bot.tree.clear_commands()

            bot.tree.add_command(points)
            bot.tree.add_command(draw)
            bot.tree.add_command(weekend_roles)
            bot.tree.add_command(status)
            bot.tree.add_command(reset)
            bot.tree.add_command(csv_tools)
            bot.tree.add_command(weeks)

            bot.tree.add_command(mg)
            bot.tree.add_command(zs)
            bot.tree.add_command(mg_status)
            bot.tree.add_command(zs_status)
            bot.tree.add_command(auto)
            bot.tree.add_command(redo_d)
            bot.tree.add_command(redo_w)
            bot.tree.add_command(train_set_drivers)
            bot.tree.add_command(train_set_anchor)
            bot.tree.add_command(train_mode)
            bot.tree.add_command(train_show)
            bot.tree.add_command(help_aem)
            bot.tree.add_command(time_lw)

            await bot.tree.sync()
            logging.info("Slash commands synced globally")

        # Start schedulers
        event_scheduler = EventScheduler(bot)
        event_scheduler.start()
        train_scheduler = TrainScheduler(bot)
        train_scheduler.start()

        logging.info("Bot connected as %s", bot.user)
    except Exception:
        logging.exception("on_ready failed")


def main():
    token = BOT_TOKEN or os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN not set in .env")
    bot.run(token)


if __name__ == "__main__":
    main()
