import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://contactcreator:contactcreator@db:5432/contactcreator"
    )
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_model: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
    hunter_api_key: str = os.environ.get("HUNTER_API_KEY", "")
    hunter_monthly_search_limit: int = int(os.environ.get("HUNTER_MONTHLY_SEARCH_LIMIT", "25"))
    follow_up_business_days: int = int(os.environ.get("FOLLOW_UP_BUSINESS_DAYS", "6"))


settings = Settings()
