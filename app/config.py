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
    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username: str = os.environ.get("SMTP_USERNAME", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    smtp_from_email: str = os.environ.get("SMTP_FROM_EMAIL", "") or os.environ.get(
        "SMTP_USERNAME", ""
    )
    daily_email_send_limit: int = int(os.environ.get("DAILY_EMAIL_SEND_LIMIT", "20"))


settings = Settings()
