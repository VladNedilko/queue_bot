from dataclasses import dataclass
import os
from dotenv import load_dotenv

@dataclass(frozen=True)
class Settings:
    token: str
    database_url: str
    offer_ttl_seconds: int
    log_level: str
    bootstrap_admin_ids: tuple[int, ...]
    allow_multiple_proxies: bool

def load_settings() -> Settings:
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        raise RuntimeError("BOT_TOKEN is not set; copy .env.example to .env")
    ids = tuple(int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip())
    allow_multiple = os.getenv("ALLOW_MULTIPLE_PROXIES", "true").strip().lower() in {"1", "true", "yes"}
    return Settings(token, os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./queue_bot.db"),
                    int(os.getenv("OFFER_TTL_SECONDS", "300")), os.getenv("LOG_LEVEL", "INFO"), ids,
                    allow_multiple)

