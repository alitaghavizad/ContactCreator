import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    database_url: str = os.environ.get(
        "DATABASE_URL", "postgresql://contactcreator:contactcreator@db:5432/contactcreator"
    )
    anthropic_api_key: str = os.environ.get("ANTHROPIC_API_KEY", "")
    claude_model: str = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
    apollo_api_key: str = os.environ.get("APOLLO_API_KEY", "")
    apollo_monthly_credit_limit: int = int(os.environ.get("APOLLO_MONTHLY_CREDIT_LIMIT", "60"))


settings = Settings()
