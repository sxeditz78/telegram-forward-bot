import os

BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
ADMIN_USER_ID = int(os.environ.get("ADMIN_USER_ID", "0"))
DB_PATH       = "data/bot.db"
