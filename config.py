"""
Loads all settings from environment variables (.env file).
Nothing secret is ever hard-coded here — it all comes from .env.
"""

import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
ADMIN_TELEGRAM_ID = int(os.getenv("ADMIN_TELEGRAM_ID", "0"))

TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL", "YOUR_TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN", "YOUR_TURSO_AUTH_TOKEN")

MINI_APP_URL = os.getenv("MINI_APP_URL", "YOUR_MINI_APP_URL")
BACKEND_URL = os.getenv("BACKEND_URL", "YOUR_BACKEND_URL")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "YOUR_WEBHOOK_SECRET")

CURRENCY = "ETB"
SITE_NAME = "Marageli"
SITE_NAME_AMHARIC = "ማራጌሊ"
