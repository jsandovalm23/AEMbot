# ===============================
# src/config.py
# ===============================
# src/config.py — robust toggles and constants (server=UTC+00 with 02:00 cutover)
import os
from dotenv import load_dotenv

# Load .env file (if present)
load_dotenv()

# Data directory (for JSON/CSV persistence)
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# Discord
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
ANNOUNCE_CHANNEL_ID = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))
ANNOUNCE_ENABLED = os.getenv("ANNOUNCE_ENABLED", "true").lower() == "true"

# VS rules
THRESHOLD = int(os.getenv("THRESHOLD", "7200000"))  # 7.2M

# Time model (server day cutover at 02:00 UTC)
GAME_CUTOVER_UTC = int(os.getenv("GAME_CUTOVER_UTC", "2"))  # 02:00 UTC

# Feature toggles (admin controllable via /auto)
AUTO_DRAW_D = os.getenv("AUTO_DRAW_D", "true").lower() == "true"
AUTO_DRAW_W = os.getenv("AUTO_DRAW_W", "true").lower() == "true"
AUTO_VS_REMINDER = os.getenv("AUTO_VS_REMINDER", "true").lower() == "true"
AUTO_TRAIN_POST = os.getenv("AUTO_TRAIN_POST", "true").lower() == "true"

# Optional mentions for urgent reminders (e.g., @RaidTeam). Leave empty to disable.
MENTION_URGENT = os.getenv("MENTION_URGENT", "")  # e.g. "<@&123456789012345678>"

# Roles
ROLE_OFFICIAL = [r.strip() for r in os.getenv("ROLE_OFFICIAL", "Official").split(",")]
ROLE_ADMIN = [r.strip() for r in os.getenv("ROLE_ADMIN", "Admin").split(",")]
